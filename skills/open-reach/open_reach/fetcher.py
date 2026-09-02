"""취득 오케스트레이션 — 정책 → 계획 → 시도 → 판정 → 관측.

경계(로그인월·페이월·정책)를 만나면 상위 티어로 올리지 않고 즉시 중단한다.
성공한 경로 1건만 관측에 남기고 본문은 어디에도 저장하지 않는다.
"""

from __future__ import annotations

import sys
import time
from email.utils import parsedate_to_datetime
from typing import Any

from . import api_index, browser as browser_mod, detect, extract, observe, policy, profiles as profiles_mod, transport
from .models import POLICY_RULES, WAF_VENDORS, Attempt, FetchRequest, FetchResult, WafVerdict, utc_now

# 계획 단계를 더 밟아도 결과가 달라지지 않는 판정들
_TERMINAL_REASONS = frozenset({"auth_wall", "paywall", "rate_limited", "not_found"})

# 브라우저 티어(T2)가 오를 자리. curl_cffi 가 JS 를 실행하지 못해 막힌 두 경우만 대상이다:
#   ① waf_challenge — 클라이언트 사이드 챌린지(예: aws_waf·kasada·f5).
#   ② validation_failed + js_shell 신호 — 본문을 JS 가 클라이언트에서 렌더하는 SPA.
# 경계(auth_wall·paywall)·rate_limited·not_found 는 대상이 아니다 — 렌더한다고
# 로그인·구독·속도제한·부재가 뒤집히지 않으며 그 시도 자체가 NG-1/NG-6 이다. 같은
# validation_failed 라도 empty_body·nav_shell 은 브라우저로 안 넘긴다(원인이 렌더가 아니다).
def _browser_worthy(reason: str, signals: tuple) -> bool:
    if reason == "waf_challenge":
        return True
    if reason == "validation_failed" and "js_shell" in signals:
        return True
    return False

# Phase 0 을 **쓰면 안 되는** 판정들.
#   auth_wall·paywall — HTML 이 로그인·구독을 요구해서 못 준 본문을 API 로 대신
#     받아 오는 것은 그 벽을 우회하는 일이다 (NG-1). 감지하고 보고할 뿐 넘지 않는다.
#   rate_limited      — 상대가 속도를 줄이라고 말한 상태다. 같은 호스트의 다른 문을
#     대신 두드리는 것은 그 요청을 무시하는 것이다 (NG-6).
#   policy_blocked    — 이미 위에서 반환된다. 도달하지 않지만 의도를 남긴다.
# 나머지(waf_challenge·not_found·server_error·network 등)에서만 시도한다 (AC-B-010-1).
_PHASE0_NO_GO = frozenset({"auth_wall", "paywall", "rate_limited", "policy_blocked"})

# 429 재시도 정책 (SPEC CLI 계약): Retry-After 우선, 없으면 지수 백오프
_BACKOFF_BASE_S = 1.0
_BACKOFF_MAX_S = 30.0
_RATE_LIMIT_MAX_RETRIES = 3


def _policy_attempt(outcome: str = "blocked", rule: str | None = None) -> Attempt:
    return Attempt(
        route="policy",
        impersonate=None,
        referer=None,
        url_variant="original",
        status=None,
        elapsed_ms=0,
        outcome=outcome,
        rule=rule,
    )


def _explain_block(rule: str | None, detail: str) -> None:
    """차단 사유를 stderr 로 흘린다 — 규칙 ID 만으로는 원인을 못 찾는다.

    FetchResult 는 SPEC 이 고정한 포맷이라 `detail` 을 담을 자리가 없다. 그런데 규칙
    ID 는 같아도 원인은 여럿이다(`private_range` 하나에 사설 대역·메타데이터·연결 경로
    통제 불가가 모두 들어온다). 사유 문장을 버리면 "상대가 막았다"와 "우리 쪽이 그
    경로를 못 쓴다"가 출력에서 완전히 같아 보인다 — 실제로 그래서 임퍼소네이션 경로가
    죽은 채로 정책 차단인 척 보고된 적이 있다. 표준 출력(JSON 계약)은 건드리지 않고
    진단만 stderr 로 보낸다.
    """
    sys.stderr.write(f"[open-reach] policy_blocked/{rule or '-'}: {detail}\n")


def _failure(url: str, reason: str, attempts: list[Attempt]) -> FetchResult:
    return FetchResult(
        url=url,
        ok=False,
        content_markdown=None,
        metadata=None,
        failure_reason=reason,
        attempts=attempts,
        final_route=attempts[-1].route if attempts else None,
    )


def _retry_after_seconds(headers: dict[str, str]) -> float | None:
    """`Retry-After` 를 초로 해석한다. 초 표기와 HTTP-date 표기를 모두 받는다."""
    raw = (headers.get("retry-after") or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(int(raw)))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    import datetime as _dt

    now = _dt.datetime.now(_dt.timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.timezone.utc)
    return max(0.0, (when - now).total_seconds())


def build_plan(url: str, *, max_attempts: int) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]], dict | None]:
    """(계획, 벤더, 지문표, 직전 성공 관측). `explain` 과 `fetch` 가 같은 함수를 쓴다.

    계획 수립이 두 벌로 존재하면 `explain` 이 보여준 계획과 `fetch` 가 실제로 밟는
    계획이 조용히 갈라진다 — 설명이 설명이 아니게 된다.
    """
    table = profiles_mod.load()
    prior = observe.last_success_for(url)
    vendor = str(prior.get("waf_vendor")) if prior else "none"
    profile = profiles_mod.profile_for(table, vendor)
    steps = profiles_mod.build_plan(profile, max_attempts=max_attempts, prior=prior)
    return steps, vendor, table, prior


def plan_for(url: str, *, max_attempts: int) -> tuple[list[dict[str, Any]], str]:
    """계획과 WAF 힌트를 만든다 — 네트워크 요청 없이 (AC-B-007 계열, explain 용)."""
    steps, vendor, _, _ = build_plan(url, max_attempts=max_attempts)
    return steps, vendor


def _record_success_safely(url: str, **fields: Any) -> None:
    """관측 기록 실패가 이미 성공한 취득을 실패로 뒤집지 않게 한다.

    관측은 다음 실행을 빠르게 하려는 부가 기능이다. 디스크가 가득 찼다는 이유로
    호출자가 받아야 할 본문을 버리는 것은 우선순위가 뒤집힌 것이다.
    """
    try:
        observe.record_success(url, **fields)
    except (OSError, TimeoutError, ValueError) as exc:
        sys.stderr.write(f"[open-reach] 관측 기록 실패 (취득은 성공) — {exc}\n")


class _RateLimitExhausted(Exception):
    """429 재시도 예산을 다 썼다 — 지문을 바꿔 다시 두드릴 대상이 아니다."""


def _attempt_step(
    request: FetchRequest,
    step: dict[str, Any],
    deadline: float,
    attempts: list[Attempt],
    budget: dict[str, int],
    *,
    explicit_search: bool = False,
) -> tuple[transport.Response, str, str, str | None, detect.ContentVerdict] | None:
    """지문 1개로 한 번 시도한다. 429 면 예산 안에서 같은 지문으로 재시도한다.

    반환 None 은 네트워크 실패 — 다음 지문으로 넘어가도 된다.
    """
    def _record_redirect(hop_url: str, status: int, elapsed_ms: int) -> None:
        # 우리가 실제로 추종한 중간 3xx 홉 (차단으로 끝나는 홉 포함). 최종 응답은
        # 아래에서 verdict.outcome 으로 따로 기록하므로 여기서는 중간 홉만 남는다.
        # `endpoint` 에 **실제로 두드린 URL** 을 남긴다 — url_variant 는 닫힌 집합이라
        # 리디렉션이 우리를 보낸 경로(a→b/private→c)를 담을 수 없다. 이 값이 없으면
        # 감사(SC-9)가 최종 URL 만 보고 실제 회선에 나간 경로를 재구성할 수 없다.
        attempts.append(
            Attempt(
                "http",
                step["impersonate"],
                None,
                step["url_variant"],
                status,
                elapsed_ms,
                "redirect",
                endpoint=hop_url,
            )
        )

    while True:
        started = time.monotonic()
        try:
            response = transport.request(
                request.url,
                timeout=request.timeout_s,
                impersonate=step["impersonate"],
                hop_check=policy.hop_guard,
                on_dispatch=_record_redirect,
            )
        except transport.NetworkError:
            attempts.append(
                Attempt(
                    "http",
                    step["impersonate"],
                    None,
                    step["url_variant"],
                    None,
                    int((time.monotonic() - started) * 1000),
                    "error",
                )
            )
            return None

        html = response.text()
        markdown, title = extract.extract_for(request.intent, html, response.final_url)
        # AC-B-014-2 (양방향) — 면제는 입력 URL 이 선언과 매치하고 **도착 URL 도
        # 여전히 선언 안**일 때만 산다. 선언된 검색 URL 이 비선언 페이지로
        # 리디렉트되면 도착지는 우발이다 — nav_shell 판정이 원래대로 돌아온다.
        # (codex 리뷰 R5-H1. is_explicit_search 는 판정 전용이라 요청이 없다.)
        explicit_here = explicit_search and api_index.is_explicit_search(
            api_index.load_cached(request.api_index), response.final_url or request.url
        )
        verdict = detect.classify(
            response.status, html, markdown, explicit_search=explicit_here
        )

        attempts.append(
            Attempt(
                "http",
                step["impersonate"],
                None,
                step["url_variant"],
                response.status,
                response.elapsed_ms,
                verdict.outcome,
            )
        )

        if verdict.reason != "rate_limited":
            return response, html, markdown, title, verdict

        # 429 — 상대가 알려준 간격을 우선 존중하고, 없으면 지수 백오프
        delay = _retry_after_seconds(response.headers)
        if delay is None:
            delay = min(_BACKOFF_MAX_S, _BACKOFF_BASE_S * (2 ** budget["used"]))
        budget["used"] += 1
        if (
            budget["used"] > _RATE_LIMIT_MAX_RETRIES
            # 재시도도 시도다 — `--max-attempts` 를 넘겨서 두드리지 않는다
            or len(attempts) >= request.max_attempts
            or time.monotonic() + delay >= deadline
        ):
            raise _RateLimitExhausted
        time.sleep(delay)


def _try_phase0(request: FetchRequest, attempts: list[Attempt]) -> api_index.Phase0Outcome | None:
    """인덱스에 항목이 있을 때만 Phase 0 을 돌린다. 없으면 None — 추측하지 않는다 (AC-B-010-2)."""
    index = api_index.load_cached(request.api_index)
    if index is None or not index.entries:
        return None
    found = api_index.entry_for(index.entries, request.url)
    if found is None:
        return None
    entry, captures = found

    def on_attempt(endpoint: str, kind: str, status: int, elapsed_ms: int, outcome: str) -> None:
        attempts.append(
            Attempt(
                "phase0",
                None,
                None,
                "json" if kind == "json" else "original",
                status,
                elapsed_ms,
                outcome,
                endpoint=endpoint,
            )
        )

    outcome = api_index.run(
        entry,
        captures,
        intent=request.intent,
        timeout=request.timeout_s,
        on_attempt=on_attempt,
    )
    for note in outcome.notes:
        sys.stderr.write(f"[open-reach] phase0: {note}\n")
    return outcome


def _vendor_rank(vendor: str) -> int:
    """확신도를 비교하기 전에 **종류**를 먼저 본다.

    `unknown_challenge` 는 "막혔는데 누구인지 모른다"이고 `none` 은 "막히지 않았다"다.
    confidence 만으로 고르면 none(1.0) 이 unknown_challenge(0.4) 를 이겨서,
    리다이렉트 끝에 한 번이라도 평범한 응답을 받으면 차단 사실이 사라진다.
    """
    if vendor in WAF_VENDORS:
        return 2
    return 1 if vendor == "unknown_challenge" else 0


def _note_vendor(trace: dict[str, Any] | None, waf: WafVerdict, origin: str) -> None:
    """시도들 중 가장 강한 판정 하나를 trace 에 남긴다 (AC-B-009-4 의 대조 입력).

    판정과 함께 **그 판정을 만든 응답의 URL** 도 남긴다. 리디렉션이 다른 사이트로
    넘어가면 거기서 만난 WAF 가 원래 URL 의 판정으로 기록되고, 배터리는 그것을
    이 항목의 정답 라벨과 대조한다 — 사이트 A 의 감지 결과가 사이트 B 의 실력으로
    계상되는 자리다. 출처를 남기면 bench 가 귀속을 확인하고 걸러 낼 수 있다.
    """
    if trace is None:
        return
    prior = trace.get("waf_vendor")
    if prior is not None:
        current = (_vendor_rank(str(prior)), float(trace.get("waf_confidence") or 0.0))
        if current >= (_vendor_rank(waf.vendor), waf.confidence):
            return
    trace["waf_vendor"] = waf.vendor
    trace["waf_confidence"] = waf.confidence
    trace["waf_signals"] = list(waf.signals)
    trace["waf_origin"] = origin


def fetch(request: FetchRequest, *, trace: dict[str, Any] | None = None) -> FetchResult:
    transport.warn_if_degraded()
    url = request.url
    attempts: list[Attempt] = []

    # ── 1. 정책 가드 (요청 전) ───────────────────────────────────────────
    try:
        verdict = policy.check_url(url)
    except policy.UnresolvableHost:
        # 검사할 주소 자체가 없다 — 정책 위반이 아니라 네트워크 실패다
        attempts.append(
            Attempt("http", None, None, "original", None, 0, "error")
        )
        return _failure(url, "network", attempts)

    if not verdict.allowed:
        _explain_block(verdict.rule, verdict.detail)
        attempts.append(_policy_attempt(rule=verdict.rule))
        return _failure(url, "policy_blocked", attempts)

    # ── 2. robots.txt ───────────────────────────────────────────────────
    robots = policy.robots_verdict(url, timeout=request.timeout_s)
    if not robots.allowed:
        _explain_block(robots.rule, robots.detail)
        attempts.append(_policy_attempt(rule=robots.rule))
        return _failure(url, "policy_blocked", attempts)

    # ── 2.5 명시적 검색 판정 (AC-B-014) ──────────────────────────────────
    # 입력 URL 판정은 여기서 한 번뿐이다 — 리디렉트 도착 URL 로 명시성을 **얻을**
    # 수는 없다("우발적 검색 페이지 도착"이 명시가 되어 버린다, AC-B-014-2).
    # 반대로 **잃을** 수는 있다: 각 응답 판정 직전에 도착 URL 이 선언 안인지
    # 재확인해, 선언 밖으로 리디렉트된 도착지는 면제를 받지 못한다 (R5-H1).
    # 선언은 판정 전용이라 어느 쪽에서도 요청이 생기지 않는다 (AC-B-014-1).
    explicit_search = api_index.is_explicit_search(
        api_index.load_cached(request.api_index), url
    )

    # ── 3. 시도 계획 ────────────────────────────────────────────────────
    steps, _, table, _ = build_plan(url, max_attempts=request.max_attempts)

    if request.no_impersonate:
        # 표준 클라이언트 고정. 지문을 뺀 계획에서 url_variant 가 같은 단계들은
        # 전부 같은 요청이 된다 — 같은 요청의 반복은 시도가 아니다
        # (profiles.candidates_for 가 저하 모드에서 쓰는 것과 같은 근거).
        seen: set[str] = set()
        plain: list[dict[str, Any]] = []
        for step in steps:
            if step["url_variant"] in seen:
                continue
            seen.add(step["url_variant"])
            plain.append({**step, "impersonate": None, "order": len(plain) + 1})
        steps = plain

    deadline = time.monotonic() + request.timeout_s * max(1, request.max_attempts)
    last_reason = "unknown"
    # 마지막 판정의 신호까지 들고 있는다. `validation_failed` 는 원인이 js_shell(클라이언트
    # 렌더)·empty_body·nav_shell 로 갈리는데, 브라우저 티어가 답인 것은 js_shell 뿐이다.
    # 사유 문자열만으로는 그 셋을 구분할 수 없어 신호를 함께 남긴다.
    last_signals: tuple = ()
    budget = {"used": 0}

    for step in steps:
        if time.monotonic() >= deadline:
            last_reason = "network"
            break

        try:
            outcome = _attempt_step(
                request, step, deadline, attempts, budget,
                explicit_search=explicit_search,
            )
        except transport.PolicyBlocked as exc:
            # 여기가 redirect_hop 이 나오는 유일한 자리다 — 선요청 후 차단이라
            # 규칙 ID 를 버리면 세 SSRF 차단이 출력에서 구분되지 않는다.
            _explain_block(exc.rule, exc.detail)
            attempts.append(_policy_attempt(rule=exc.rule))
            return _failure(url, "policy_blocked", attempts)
        except _RateLimitExhausted:
            last_reason = "rate_limited"
            break

        if outcome is None:
            last_reason = "network"
            continue

        response, html, markdown, title, content_verdict = outcome

        # 벤더 판정은 성공·차단을 가리지 않고 **모든 응답에서** 한다. 차단된 응답이야말로
        # 벤더가 가장 잘 드러나는 자리인데, 성공 분기에서만 재면 감지 정확도(SC-8)의
        # 표본이 "이미 뚫린 것들"로만 채워져 미탐이 구조적으로 0 이 된다.
        waf = detect.waf_verdict(response.status, response.headers, html, table)
        _note_vendor(trace, waf, response.final_url or url)

        if content_verdict.reason is None:
            _record_success_safely(
                url,
                waf_vendor=waf.vendor,
                route="http",
                impersonate=step["impersonate"],
                url_variant=step["url_variant"],
            )
            return FetchResult(
                url=url,
                ok=True,
                content_markdown=markdown,
                metadata={
                    "title": title,
                    "final_url": response.final_url,
                    "content_type": response.headers.get("content-type", ""),
                    "fetched_at": utc_now(),
                },
                failure_reason=None,
                attempts=attempts,
                final_route="http",
            )

        last_reason = content_verdict.reason
        last_signals = tuple(content_verdict.signals)
        if content_verdict.terminal or last_reason in _TERMINAL_REASONS:
            # 경계·CAPTCHA·레이트리밋은 다음 지문으로 바꿔 다시 두드릴 대상이 아니다
            break

    # ── 4. Phase 0 공개 API 라우팅 (AC-B-010-1: HTTP 가 본문을 못 얻은 뒤에만) ──
    if last_reason not in _PHASE0_NO_GO:
        phase0 = _try_phase0(request, attempts)
        if phase0 is not None:
            if phase0.ok:
                metadata = {
                    "title": phase0.title,
                    "final_url": phase0.final_url,
                    "content_type": phase0.content_type,
                    "fetched_at": utc_now(),
                }
                if phase0.content_license:
                    # AC-B-010-18 — 원본이 명시한 라이선스만 싣는다. 없으면 없는 대로 둔다.
                    metadata["content_license"] = phase0.content_license
                # 관측에는 남기지 않는다. 관측은 "다음에 어떤 지문부터 시도할지"를
                # 위한 것이고 Phase 0 에는 지문이 없다. 재현할 수 없는 경로를
                # 직전 성공으로 기록하면 AC-B-006-4(직전 성공 경로가 attempts[0])가
                # 다음 실행에서 스스로 거짓이 된다.
                return FetchResult(
                    url=url,
                    ok=True,
                    content_markdown=phase0.markdown,
                    metadata=metadata,
                    failure_reason=None,
                    attempts=attempts,
                    final_route="phase0",
                )
            if phase0.reason == "policy_blocked":
                # AC-B-010-13 — 조립된 URL 이 SSRF·robots 에 걸렸다
                rule = phase0.policy_rule
                attempts.append(_policy_attempt(rule=rule if rule in POLICY_RULES else None))
                return _failure(url, "policy_blocked", attempts)
            if phase0.reason is not None:
                last_reason = phase0.reason
                # Phase 0 은 JSON API 라 js_shell 신호가 없다 — 신호를 물려주지 않는다.
                last_signals = ()

    # ── 5. 브라우저 티어 (T2, R3) — JS 챌린지에서만 오른다 (ADR-004) ──
    #   HTTP·Phase 0 가 모두 실패하고 마지막 판정이 waf_challenge 일 때만. curl_cffi 가
    #   JS 를 못 돌려 막힌 자리를 실제 렌더로 넘는다. 경계·레이트리밋은 대상이 아니다.
    if request.allow_browser and _browser_worthy(last_reason, last_signals):
        available, why = browser_mod.browser_available()
        if not available:
            # 지연 설치 대상이 없다 — 없는 돌파를 지어내지 않고 정책 사유로 명시한다 (NG-10)
            sys.stderr.write(
                f"[open-reach] browser_disabled: 브라우저 티어 미설치 — {why}. "
                "설치: python -m patchright install chromium\n"
            )
            attempts.append(_policy_attempt(rule="browser_disabled"))
            return _failure(url, last_reason, attempts)

        outcome = browser_mod.browser_fetch(url, timeout_s=request.timeout_s)
        if not outcome.ok:
            attempts.append(
                Attempt("browser", None, None, "original", None, outcome.elapsed_ms, "error")
            )
            return _failure(url, outcome.error or last_reason, attempts)

        # NG-11 재검사(2차 방어): 브라우저 route 가드가 홉별로 사설 대역을 이미 막지만,
        # 최종 도착지도 한 번 더 본다. UnresolvableHost 는 fail-closed 로 차단한다 —
        # 코드베이스 전역(hop_check·robots 프리체크)이 DNS 실패를 막는 것과 같은 관례다.
        try:
            final_verdict = policy.check_url(outcome.final_url)
        except policy.UnresolvableHost as exc:
            final_verdict = policy.PolicyVerdict(False, "private_range", str(exc))
        if not final_verdict.allowed:
            _explain_block(final_verdict.rule, final_verdict.detail)
            attempts.append(_policy_attempt(rule=final_verdict.rule))
            return _failure(url, "policy_blocked", attempts)

        markdown, title = extract.extract_for(request.intent, outcome.html, outcome.final_url)
        # HTTP 티어와 같은 이유(AC-B-014-2 양방향) — 브라우저 리디렉트 도착지도
        # 선언 밖이면 면제를 잃는다 (codex 리뷰 R5-H1).
        explicit_here = explicit_search and api_index.is_explicit_search(
            api_index.load_cached(request.api_index), outcome.final_url or url
        )
        content_verdict = detect.classify(
            outcome.status, outcome.html, markdown, explicit_search=explicit_here
        )
        # 벤더 판정은 HTTP 티어와 동일하게 성공·차단을 가리지 않고 한다 (SC-8 표본 편향 방지).
        waf = detect.waf_verdict(outcome.status, outcome.headers, outcome.html, table)
        _note_vendor(trace, waf, outcome.final_url)
        attempts.append(
            Attempt(
                "browser", None, None, "original",
                outcome.status, outcome.elapsed_ms, content_verdict.outcome,
            )
        )
        if content_verdict.reason is None:
            _record_success_safely(
                url,
                waf_vendor=waf.vendor,
                route="browser",
                impersonate=None,
                url_variant="original",
            )
            return FetchResult(
                url=url,
                ok=True,
                content_markdown=markdown,
                metadata={
                    "title": title,
                    "final_url": outcome.final_url,
                    "content_type": outcome.headers.get("content-type", "text/html"),
                    "fetched_at": utc_now(),
                },
                failure_reason=None,
                attempts=attempts,
                final_route="browser",
            )
        last_reason = content_verdict.reason

    return _failure(url, last_reason, attempts)
