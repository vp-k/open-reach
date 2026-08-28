"""취득 오케스트레이션 — 정책 → 계획 → 시도 → 판정 → 관측.

경계(로그인월·페이월·정책)를 만나면 상위 티어로 올리지 않고 즉시 중단한다.
성공한 경로 1건만 관측에 남기고 본문은 어디에도 저장하지 않는다.
"""

from __future__ import annotations

import sys
import time
from email.utils import parsedate_to_datetime
from typing import Any

from . import detect, extract, observe, policy, profiles as profiles_mod, transport
from .models import Attempt, FetchRequest, FetchResult, utc_now

# 계획 단계를 더 밟아도 결과가 달라지지 않는 판정들
_TERMINAL_REASONS = frozenset({"auth_wall", "paywall", "rate_limited", "not_found"})

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
) -> tuple[transport.Response, str, str, str | None, detect.ContentVerdict] | None:
    """지문 1개로 한 번 시도한다. 429 면 예산 안에서 같은 지문으로 재시도한다.

    반환 None 은 네트워크 실패 — 다음 지문으로 넘어가도 된다.
    """
    while True:
        started = time.monotonic()
        try:
            response = transport.request(
                request.url,
                timeout=request.timeout_s,
                impersonate=step["impersonate"],
                hop_check=policy.hop_guard,
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
        verdict = detect.classify(response.status, html, markdown)

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


def fetch(request: FetchRequest) -> FetchResult:
    transport.warn_if_degraded()
    url = request.url
    attempts: list[Attempt] = []

    # ── 1. 정책 가드 (요청 전) ───────────────────────────────────────────
    if request.allow_browser:
        # R1 에는 브라우저 경로가 없다. 있는 척하지 않고 정책 사유로 명시한다 (NG-10)
        sys.stderr.write(
            "[open-reach] browser_disabled: R1 에는 브라우저 폴백 경로가 없다 — "
            "--allow-browser 는 무시된다\n"
        )

    try:
        verdict = policy.check_url(url)
    except policy.UnresolvableHost:
        # 검사할 주소 자체가 없다 — 정책 위반이 아니라 네트워크 실패다
        attempts.append(
            Attempt("http", None, None, "original", None, 0, "error")
        )
        return _failure(url, "network", attempts)

    if not verdict.allowed:
        attempts.append(_policy_attempt(rule=verdict.rule))
        return _failure(url, "policy_blocked", attempts)

    # ── 2. robots.txt ───────────────────────────────────────────────────
    robots = policy.robots_verdict(url, timeout=request.timeout_s)
    if not robots.allowed:
        attempts.append(_policy_attempt(rule=robots.rule))
        return _failure(url, "policy_blocked", attempts)

    # ── 3. 시도 계획 ────────────────────────────────────────────────────
    steps, _, table, _ = build_plan(url, max_attempts=request.max_attempts)

    deadline = time.monotonic() + request.timeout_s * max(1, request.max_attempts)
    last_reason = "unknown"
    budget = {"used": 0}

    for step in steps:
        if time.monotonic() >= deadline:
            last_reason = "network"
            break

        try:
            outcome = _attempt_step(request, step, deadline, attempts, budget)
        except transport.PolicyBlocked as exc:
            # 여기가 redirect_hop 이 나오는 유일한 자리다 — 선요청 후 차단이라
            # 규칙 ID 를 버리면 세 SSRF 차단이 출력에서 구분되지 않는다.
            attempts.append(_policy_attempt(rule=exc.rule))
            return _failure(url, "policy_blocked", attempts)
        except _RateLimitExhausted:
            last_reason = "rate_limited"
            break

        if outcome is None:
            last_reason = "network"
            continue

        response, html, markdown, title, content_verdict = outcome

        if content_verdict.reason is None:
            waf = detect.waf_verdict(response.status, response.headers, html, table)
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
        if content_verdict.terminal or last_reason in _TERMINAL_REASONS:
            # 경계·CAPTCHA·레이트리밋은 다음 지문으로 바꿔 다시 두드릴 대상이 아니다
            break

    return _failure(url, last_reason, attempts)
