"""질의 → 후보 URL (R6/W5).

open-reach 는 R5 까지 URL 하나를 받는 fetcher 였다. 이 모듈이 앞단을 연다 —
질의를 받아 공개 검색 소스에 물어보고, **URL 후보 목록**을 낸다. 취득은 하지 않는다.

**이 모듈은 취득된 본문을 보지 않는다.** 그것이 NG-5 개정판의 유일한 방벽인 "재귀
부재"를 구조로 만드는 방법이다: 후보를 만드는 코드가 기사 본문에 접근할 수 없으면
"본문에서 링크를 뽑아 다시 큐에 넣기"는 코드로 표현될 수 없다. 그래서 여기서는
`fetcher`·`batch`·`extract`·`alternates` 를 임포트하지 않는다. 호출부(engine)가
후보를 `batch` 로 넘기고, 그 결과는 다시 이 모듈로 돌아오지 않는다.

요청은 Phase 0 과 같은 규율을 따른다 — 임퍼소네이션 없음, `HONEST_UA` 로 신원을
밝힘, 홉마다 SSRF 재검사. 인덱스에 등재하는 조건도 같다: **정직한 UA 로 200 을 직접
실측**한 소스만 적는다 (AC-B-012-6). 브라우저 UA 를 요구하는 SERP 는 등재하지 않는다 —
등재해 놓고 런타임에만 다른 신원을 쓰면 실측이 거짓말이 된다 (NG-8·NG-13).
"""

from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from . import api_index, policy, transport
from .policy import DEFAULT_ROBOTS_MODE

DEFAULT_MAX_RESULTS = 10
MAX_RESULTS_CAP = 25
MAX_QUERY_CHARS = 256
# 소스 하나가 후보 전부를 채우면 팬아웃의 의미가 없다. 인터리브(아래 `_interleave`)와
# 짝을 이루는 상한이다.
PER_SOURCE_CAP = 25
MAX_SOURCE_FANOUT = 8


class SearchError(ValueError):
    """질의·소스 선택이 성립하지 않는다 — 요청 전에 거절한다."""


@dataclass(frozen=True)
class Candidate:
    url: str
    title: str | None
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "title": self.title, "source": self.source}


@dataclass(frozen=True)
class SourceOutcome:
    """소스 하나의 결과. 실패도 **그 자리에 남는다** (NG-10)."""

    name: str
    endpoint: str
    ok: bool
    status: int | None
    found: int
    elapsed_ms: int
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "endpoint": self.endpoint,
            "ok": self.ok,
            "status": self.status,
            "found": self.found,
            "elapsed_ms": self.elapsed_ms,
            "reason": self.reason,
        }


# ── 입력 검증 ────────────────────────────────────────────────────────────


def check_query(query: str) -> str:
    text = query.strip()
    if not text:
        raise SearchError("질의가 비어 있다")
    if len(text) > MAX_QUERY_CHARS:
        raise SearchError(f"질의는 {MAX_QUERY_CHARS} 자 이하여야 한다 (현재 {len(text)})")
    return text


def check_max_results(value: int) -> int:
    if not (1 <= value <= MAX_RESULTS_CAP):
        raise SearchError(f"--max-results 는 1..{MAX_RESULTS_CAP} 여야 한다")
    return value


def select_sources(
    index: api_index.ApiIndex, wanted: str | None
) -> list[dict[str, Any]]:
    """`--sources a,b` 로 고르거나, 지정이 없으면 선언된 전부.

    모르는 이름은 **조용히 무시하지 않는다**. 오타 하나로 팬아웃이 절반이 되어도
    출력만 보고는 알 수 없기 때문이다.
    """
    declared = list(index.search_sources)
    if not declared:
        raise SearchError(
            "인덱스에 `search_sources:` 선언이 없다 — 검색할 소스가 없다"
        )
    if wanted is None:
        return declared[:MAX_SOURCE_FANOUT]
    names = [part.strip() for part in wanted.split(",") if part.strip()]
    if not names:
        raise SearchError("--sources 가 비어 있다")
    known = {decl["name"]: decl for decl in declared}
    unknown = [name for name in names if name not in known]
    if unknown:
        raise SearchError(
            f"모르는 소스: {unknown} — 선언된 것은 {sorted(known)} 다"
        )
    # 중복 지정은 같은 소스를 두 번 두드리는 일이라 순서를 지킨 채 접는다.
    picked: list[dict[str, Any]] = []
    for name in names:
        if known[name] not in picked:
            picked.append(known[name])
    return picked[:MAX_SOURCE_FANOUT]


# ── URL 조립 ─────────────────────────────────────────────────────────────


def build_url(source: dict[str, Any], query: str) -> str:
    """질의를 템플릿에 넣는다. 치환은 **퍼센트 인코딩**이다.

    `api_index.substitute` 를 쓰지 않는 이유: 그 함수는 응답 캡처값을 위한 것이라
    `&`·`=`·`/`·`%` 를 금지 문자로 거절한다. 검색 질의에서 그 문자들은 정상적인
    입력이고("c++ vs c#", "a/b"), 거절하면 도구가 쓸모없어진다.

    안전성의 근거가 달라진다는 점이 중요하다. 캡처값은 **응답**에서 오므로 상대가
    통제하고, 그래서 문자 자체를 막았다. 질의는 **사용자**에게서 오고, `safe=""`
    퍼센트 인코딩을 거치면 결과 문자열은 정의상 비예약 문자와 `%XX` 뿐이라 구분자를
    합성할 수 없다. 스킴·호스트·파라미터 이름에 치환자를 못 쓰는 것은 로드 시점에
    이미 강제됐다 (`_check_search_source`).
    """
    url = source["query_template"].replace("{query}", quote(query, safe=""))
    if len(url) > policy.MAX_URL_LENGTH:
        raise SearchError(f"조립된 검색 URL 이 {policy.MAX_URL_LENGTH} 자를 넘었다")
    return url


def normalize(raw: Any) -> str | None:
    """후보 URL 정규화. 쓸 수 없는 것은 `None` 으로 떨어뜨린다.

    - http/https 가 아니면 버린다 (`javascript:`·`mailto:`·상대 경로)
    - userinfo(`@`)가 실린 URL 은 버린다 — 이 도구는 자격증명을 취급하지 않는다 (NG-4)
    - 프래그먼트는 떼어낸다. `#a` 와 `#b` 는 같은 문서라 dedupe 가 갈리면 안 된다
    """
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    if "@" in parts.netloc:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _excluded(url: str, source: dict[str, Any]) -> bool:
    """소스가 선언한 제외 호스트에 걸리는가 (하위 도메인 포함).

    `duckduckgo.com` 선언은 `lite.duckduckgo.com` 도 덮는다 — 걷어내려는 것은 특정
    호스트명이 아니라 **그 소스 자신의 기계장치**이고, 그것은 하위 도메인에 흩어져
    있기 때문이다. 접미사 비교는 점을 붙여서 한다: `notduckduckgo.com` 이 걸리면
    안 된다.
    """
    hosts = source.get("exclude_hosts") or ()
    if not hosts:
        return False
    hostname = (urlsplit(url).hostname or "").lower()
    return any(hostname == host or hostname.endswith("." + host) for host in hosts)


# ── 응답 파싱 ────────────────────────────────────────────────────────────


def _walk(payload: Any, pointer: str) -> Any:
    return api_index.select_scalar(payload, pointer)


def parse_json(source: dict[str, Any], payload: Any) -> list[Candidate]:
    node = _walk(payload, source["result_pointer"])
    if not isinstance(node, list):
        return []
    link_pointer = source.get("link_pointer")
    title_pointer = source.get("title_pointer")
    out: list[Candidate] = []
    for item in node[:PER_SOURCE_CAP]:
        raw = _walk(item, link_pointer) if link_pointer else item
        url = normalize(raw)
        if url is None:
            # 링크가 없는 항목은 그냥 건너뛴다 — HN 의 Ask HN 처럼 외부 URL 이 없는
            # 결과가 실재한다. 없는 링크를 지어내지 않는다 (NG-10).
            continue
        if _excluded(url, source):
            continue
        title = _walk(item, title_pointer) if title_pointer else None
        out.append(
            Candidate(url, title.strip() if isinstance(title, str) else None, source["name"])
        )
    return out


def parse_html(source: dict[str, Any], text: str) -> list[Candidate]:
    pattern = re.compile(source["result_link_pattern"])
    transform = source.get("link_transform", "none")
    titles = (
        re.compile(source["title_pattern"]).findall(text)
        if source.get("title_pattern")
        else []
    )
    out: list[Candidate] = []
    for position, captured in enumerate(pattern.findall(text)[:PER_SOURCE_CAP]):
        value = unquote(captured) if transform == "percent" else captured
        url = normalize(value)
        if url is None or _excluded(url, source):
            continue
        title = titles[position].strip() if position < len(titles) else None
        out.append(Candidate(url, title or None, source["name"]))
    return out


# ── 실행 ────────────────────────────────────────────────────────────────


def _ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _query_one(
    source: dict[str, Any], query: str, *, timeout: float, robots_mode: str
) -> tuple[SourceOutcome, list[Candidate]]:
    name = source["name"]
    started = time.monotonic()
    try:
        url = build_url(source, query)
    except SearchError as exc:
        return SourceOutcome(name, "", False, None, 0, _ms(started), str(exc)), []

    try:
        verdict = policy.check_url(url)
    except policy.UnresolvableHost as exc:
        return SourceOutcome(name, url, False, None, 0, _ms(started), str(exc)), []
    if not verdict.allowed:
        return (
            SourceOutcome(name, url, False, None, 0, _ms(started), verdict.detail),
            [],
        )
    robots = policy.robots_gate(url, timeout=timeout, mode=robots_mode)
    if not robots.allowed:
        return SourceOutcome(name, url, False, None, 0, _ms(started), robots.detail), []

    try:
        response = transport.request(
            url,
            timeout=timeout,
            impersonate=None,  # 기계용 문은 기계 신원으로 두드린다 (AC-B-010-4)
            user_agent=api_index.HONEST_UA,
            accept=api_index._accept_for(source["kind"]),
            hop_check=policy.hop_guard_for(robots_mode),
        )
    except transport.PolicyBlocked as exc:
        return SourceOutcome(name, url, False, None, 0, _ms(started), str(exc)), []
    except (transport.NetworkError, transport.BudgetExceeded) as exc:
        return SourceOutcome(name, url, False, None, 0, _ms(started), str(exc)), []

    if response.status != 200:
        return (
            SourceOutcome(name, url, False, response.status, 0, _ms(started), "non_200"),
            [],
        )

    try:
        if source["kind"] == "json":
            found = parse_json(source, json.loads(response.text()))
        else:
            found = parse_html(source, response.text())
    except (ValueError, re.error) as exc:
        return (
            SourceOutcome(name, url, False, response.status, 0, _ms(started), str(exc)),
            [],
        )
    return (
        SourceOutcome(name, url, True, response.status, len(found), _ms(started)),
        found,
    )


def _interleave(groups: Iterable[list[Candidate]]) -> list[Candidate]:
    """소스별 결과를 라운드로빈으로 섞는다.

    이어 붙이면 `--max-results 10` 이 첫 소스 하나로 다 차서, 팬아웃해 놓고 한 소스만
    쓰는 것과 결과가 같아진다. 절단은 마지막에 하므로 섞는 순서가 곧 우선순위다.
    """
    lists = [list(group) for group in groups]
    out: list[Candidate] = []
    for position in range(max((len(g) for g in lists), default=0)):
        for group in lists:
            if position < len(group):
                out.append(group[position])
    return out


def _blocked_rule(url: str) -> str | None:
    """후보로 내놓아도 되는 주소인가 (NG-11). 막을 이유가 있으면 그 규칙 이름.

    소스가 돌려준 주소라고 안전한 것이 아니다. 후보 목록은 `--urls-only` 로 그대로
    나가고 사람과 도구는 그것을 "열 수 있는 주소"로 읽으므로, 취득 시점의
    fail-closed 가드에만 기대지 않고 내놓기 전에 한 번 거른다. 검사는 절단 **전**
    후보에 걸리므로 보통은 `max_results` 건에서 멈추지만, 후보가 계속 걸러지면
    모아 둔 후보를 끝까지 훑는다 — 상한은 `PER_SOURCE_CAP × MAX_SOURCE_FANOUT`
    (25 × 8 = 200) 이고 그 이상은 구조적으로 불가능하다.

    이름이 안 풀리는 것은 **거르는 이유가 아니다**. 사설 대역을 가리키는 것과 다르고,
    못 푸는 주소는 취득 시점에 어차피 fail-closed 로 실패한다. 여기서 지우면
    일시적 DNS 실패가 조용히 결과를 깎는다.
    """
    try:
        verdict = policy.check_url(url)
    except policy.UnresolvableHost:
        return None
    return None if verdict.allowed else verdict.rule


def run(
    query: str,
    sources: list[dict[str, Any]],
    *,
    timeout: float = 20.0,
    max_results: int = DEFAULT_MAX_RESULTS,
    robots_mode: str = DEFAULT_ROBOTS_MODE,
) -> tuple[list[Candidate], list[SourceOutcome]]:
    """소스에 병렬로 물어보고, 인터리브 → dedupe → 절단한 후보를 돌려준다."""
    query = check_query(query)
    max_results = check_max_results(max_results)
    if not sources:
        raise SearchError("검색할 소스가 없다")

    workers = min(len(sources), MAX_SOURCE_FANOUT)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _query_one, source, query, timeout=timeout, robots_mode=robots_mode
            )
            for source in sources
        ]
        # 완료 순서가 아니라 선언 순서로 받는다 — 같은 질의가 실행마다 다른 후보 순서를
        # 내면 증적 비교가 불가능해진다 (batch.run 과 같은 이유).
        pairs = [future.result() for future in futures]

    outcomes = [outcome for outcome, _ in pairs]
    seen: set[str] = set()
    dropped: list[str] = []
    candidates: list[Candidate] = []
    for candidate in _interleave(found for _, found in pairs):
        if candidate.url in seen:
            continue
        seen.add(candidate.url)
        rule = _blocked_rule(candidate.url)
        if rule is not None:
            dropped.append(f"{candidate.url} — {rule}")
            continue
        candidates.append(candidate)
        if len(candidates) >= max_results:
            break

    for note in dropped:
        # 조용히 지우지 않는다 — 몇 건이 왜 빠졌는지 보이지 않으면 관측만 보고는
        # "소스가 적게 줬다"와 구분할 수 없다 (NG-10).
        sys.stderr.write(f"[open-reach] search: 후보 제외 — {note}\n")
    for outcome in outcomes:
        if not outcome.ok:
            sys.stderr.write(
                f"[open-reach] search: {outcome.name} 실패 — {outcome.reason}\n"
            )
    return candidates, outcomes
