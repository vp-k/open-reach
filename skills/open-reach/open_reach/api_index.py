"""Phase 0 공개 API 라우팅 — 인덱스 로드·검증과 조립 실행 (US-B-010).

이 모듈이 존재하는 이유는 하나다. **응답이 우리의 다음 요청 URL에 영향을 준다.**
리디렉션은 전송 계층의 `hop_guard` 가 보지만, 여기서 만드는 URL 은 우리가 자발적으로
조립하는 것이라 그 가드에 걸리지 않는다. 그래서 조립 규칙 전부(AC-B-010-8~14)를
한 곳에 모아 두고, 로드 시점에 막을 수 있는 것은 **요청을 시작하기 전에** 막는다.

경계는 그대로다. 인증·키를 요구하면 뚫지 않고 `auth_wall` 로 보고하며(NG-1, NG-4),
쿼터가 소진되면 키나 IP 를 바꾸지 않고 `rate_limited` 로 실패한다(NG-6).
기계용으로 열어 둔 문을 브라우저인 척하며 두드리지 않는다(NG-13, AC-B-010-4).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import __version__, observe, policy, transport, yamlio

# ── 로드 시점 상한 (AC-B-010-8·15) ───────────────────────────────────────
MAX_ENTRIES = 20
MAX_CHAIN = 2
REQUEST_BUDGET = 3  # AC-B-010-14 — 엔드포인트 + 체인 합산

# 계약의 3회는 **우리가 인덱스를 근거로 고른 요청**을 센다. 그런데 요청 하나가 리디렉션을
# 따라가면 회선에는 여러 번 나가고, robots 조회도 실제 요청이다 — 라운드 2 에서
# `3 endpoints x 5 hops = 18` 회의 증폭 경로가 지적됐다. 계약 문언을 조용히 넓히는 대신
# **실제 요청 총량**에 별도 상한을 둔다.
#
# 상한을 세우는 방법은 두 번 틀렸다. 라운드 2 의 7 은 "오리진 하나·홉 하나"를 **가정**만
# 하고 강제하지 않아 정상 항목이 막혔고(라운드 3), 라운드 3 은 그 가정을 참으로 만들려고
# robots 조회에까지 홉 상한을 걸었다가 **robots 의 fail-open 과 결합해 Disallow 를
# 우회**시켰다(라운드 4). 교훈은 하나다 — 상한은 **이미 강제되고 있는 것**에서만 유도한다.
#
#   · Phase 0 의 본 요청: `_same_origin_hop` 이 홉을 `PHASE0_MAX_REDIRECTS` 로 끊는다.
#   · robots 조회: 상한을 두지 않는다(정책 판정을 왜곡하므로). 전송 계층의
#     `transport.MAX_REDIRECTS` 가 유일한 상한이므로 그 값을 그대로 쓴다.
#   · robots 는 오리진당 1회(캐시)이고, 오리진 수는 요청 수를 넘지 못한다 —
#     `_run_endpoints`/`_run_chain` 이 `_guard` **전에** 예산을 확인하기 때문이다.
#
# 실질적인 보호는 이 미터가 아니라 위의 홉 상한이 한다. 미터는 상수가 흘렀을 때
# 조용히 넘어가지 않게 하는 백스톱이다 — 그 사실을 숨기지 않는다 (NG-10).
PHASE0_MAX_REDIRECTS = 2
RESPONSE_KINDS = ("html", "json")


def _dispatch_budget() -> int:
    """항목 하나가 회선에 낼 수 있는 요청 수의 상한.

    상수가 아니라 함수다 — 각 항이 다른 모듈의 **강제된 상한**을 참조하므로,
    그 값이 바뀌면 여기도 따라 바뀌어야 한다.
    """
    return (
        REQUEST_BUDGET * (1 + PHASE0_MAX_REDIRECTS)              # 본 요청 + 홉
        + REQUEST_BUDGET * (1 + transport.MAX_REDIRECTS)         # 오리진당 robots + 홉
    )


DISPATCH_BUDGET = _dispatch_budget()

# 정직한 UA (AC-B-010-4). 임퍼소네이션은 이 경로에서 아예 쓰지 않는다.
REPO_URL = "https://github.com/vp-k/open-reach"
HONEST_UA = f"open-reach/{__version__} (+{REPO_URL})"

# AC-B-010-11 — 넘겨받은 값이 경로 세그먼트 1개를 벗어나게 하는 문자.
# `value_pattern` 이 이미 막더라도 이중으로 검사한다. 패턴은 인덱스 저자가 쓰는 것이고
# 저자는 틀릴 수 있다 — 저자가 느슨하게 적어도 여기서 막혀야 계약이다.
# `/`·`%`·`:`·`?`·`#`·`\` 는 AC-B-010-11 이 열거한 그대로다 (SPEC:190).
# 아래 `;` 와 공백류는 계약이 열거하지 않았지만 추가로 막는다. 계약이 **허용한다고**
# 적은 적 없는 것을 막는 것이므로 허용 집합을 넓히지 않고, 따라서 개정 없이 넣는다.
# (라운드 8 정정: 예전 주석은 이를 "\ 가 목록에 없는데도 막는 선례" 로 정당화했는데
#  \ 는 처음부터 목록에 있었다. 없는 선례를 근거로 든 서술이라 지웠다 — NG-10.)
SEGMENT_FORBIDDEN = ("/", "%", ":", "?", "#", "\\", ";")
# 세미콜론을 넣는 이유는 서버 정규화다.
# Tomcat/Servlet 계열은 경로 파라미터(`;a=b`)를 **떼어 낸 뒤** 정규화하므로
# `..;a=b` 세그먼트가 서버에서 `..` 가 된다 — 우리 눈에는 점만 든 평범한 값이다.
# 식별자 세그먼트에 세미콜론이 필요한 경우는 없으므로 통째로 막는다.
# (라운드 7 HIGH. 점을 문자로 허용한 개정이 새로 연 표면이다.)
# 점은 **문자로는** 금지하지 않는다. `1.0.219` 같은 버전 문자열이 정상 세그먼트이고,
# 전면 금지는 2-hop 항목을 정의상 불가능하게 만들었다 (R2 SPEC 개정, 사용자 승인).
# 경로 탈출은 `.`·`..` **세그먼트 자체**를 거부하는 것으로 막는다 — 문자 금지가 아니다.
SEGMENT_DOT_ONLY = (".", "..")
# 공백류도 막는다. IIS 계열은 세그먼트 끝의 공백과 점을 떼어 내므로 `'.. '` 가
# `..` 가 된다. 문자 목록이 아니라 술어로 검사한다 — 탭·개행·유니코드 공백까지.

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 401 이 아닌 403 에서 "키를 받아 오라"는 안내를 가려내는 신호 (AC-B-010-5).
_KEY_HINTS = ("api key", "apikey", "api_key", "access token", "unauthorized",
              "authentication required", "register for a key")
# 쿼터 소진 (AC-B-010-6)
_QUOTA_HINTS = ("quota", "rate limit", "rate_limit", "throttle", "too many requests")


class IndexLoadError(ValueError):
    """인덱스를 신뢰할 수 없다 — 종료 코드 3. 요청은 한 건도 나가지 않는다."""


class Rejected(Exception):
    """조립 규칙 위반 — 요청하지 않고 중단한다 (AC-B-010-9·10·11)."""


@dataclass
class Phase0Outcome:
    """Phase 0 의 결과. `reason` 이 None 이면 '구제하지 못했다'는 뜻이다."""

    markdown: str | None = None
    title: str | None = None
    final_url: str | None = None
    content_type: str = ""
    content_license: str | None = None
    reason: str | None = None          # auth_wall / rate_limited / policy_blocked ...
    policy_rule: str | None = None     # reason == "policy_blocked" 일 때만
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.markdown is not None


# ── 로드와 검증 ──────────────────────────────────────────────────────────


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IndexLoadError(f"{what} 는 비어 있지 않은 문자열이어야 한다")
    return value.strip()


def _bad_path_segment(url: str) -> str | None:
    """실제로 쏠 URL 의 **경로**에서 규칙을 어긴 세그먼트를 찾는다. 없으면 None.

    값만 검사해서는 부족하다. 값은 멀쩡한데 템플릿의 리터럴 텍스트와 붙으면서
    세그먼트가 달라질 수 있기 때문이다 (라운드 8 HIGH):

        template = "https://api.example/public/%{hex}%2e/readme"
        hex      = "2e"                      # `%` 없음 — 값 단위 검사는 통과한다
        rendered = ".../public/%2e%2e/readme"

    Tomcat 은 `%xx` 를 디코드한 **뒤** URI 를 정규화하므로 이를 `/readme` 로 처리한다.
    우리가 robots 를 물어본 경로와 서버가 실제로 여는 경로가 갈라지는 것이다.
    그래서 값이 아니라 **보내는 것**을 검사한다 — 조합으로 만들어지는 계열이
    이 한 곳에서 닫힌다.
    """
    for segment in urlsplit(url).path.split("/"):
        if not segment:
            continue
        for bad in SEGMENT_FORBIDDEN:
            if bad in segment:
                return f"세그먼트 {segment!r} 에 {bad!r} 가 있다"
        if any(ch.isspace() for ch in segment):
            return f"세그먼트 {segment!r} 에 공백류가 있다"
        if segment in SEGMENT_DOT_ONLY:
            return f"세그먼트가 상대 경로 {segment!r} 다"
    return None


def _check_request_template(template: str, what: str) -> None:
    """AC-B-010-12 — 스킴과 호스트는 응답에서 오지 않는다.

    치환자는 **경로에만** 둔다. 쿼리에 두면 응답이 쿼리 구조를 바꿀 수 있고,
    스킴·호스트에 두면 응답이 우리를 다른 서버로 보낼 수 있다.
    """
    parts = urlsplit(template)
    if parts.scheme not in ("http", "https"):
        raise IndexLoadError(f"{what}: 스킴은 http/https 여야 한다 — {template!r}")
    if not parts.netloc:
        raise IndexLoadError(f"{what}: 호스트가 없다 — {template!r}")
    for field_name, value in (("스킴", parts.scheme), ("호스트", parts.netloc)):
        if "{" in value or "}" in value:
            raise IndexLoadError(
                f"{what}: {field_name} 에 치환자를 쓸 수 없다 (AC-B-010-12) — {template!r}"
            )
    for field_name, value in (("쿼리", parts.query), ("프래그먼트", parts.fragment)):
        if "{" in value or "}" in value:
            raise IndexLoadError(
                f"{what}: {field_name} 에 치환자를 쓸 수 없다 (AC-B-010-11) — {template!r}"
            )
    # 치환자를 안전한 토큰으로 바꿔 놓고 경로 규칙을 미리 건다. 리터럴 `%` 가
    # 치환자 옆에 있으면 응답값이 퍼센트 시퀀스를 **합성**할 수 있으므로,
    # 요청 시점이 아니라 로드 시점에 인덱스 저자에게 알린다 (라운드 8 HIGH).
    problem = _bad_path_segment(_PLACEHOLDER.sub("x", template))
    if problem is not None:
        raise IndexLoadError(
            f"{what}: 템플릿 경로가 세그먼트 규칙을 어긴다 — {problem} "
            f"(AC-B-010-11) — {template!r}"
        )


def _check_pattern(raw: Any, what: str) -> None:
    """AC-B-010-10 — 앵커된 `value_pattern` 은 필수다."""
    pattern = _require_str(raw, f"{what}.value_pattern")
    if not (pattern.startswith("^") and pattern.endswith("$")):
        raise IndexLoadError(f"{what}: value_pattern 은 ^ 와 $ 로 앵커해야 한다 — {pattern!r}")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise IndexLoadError(f"{what}: value_pattern 컴파일 실패 — {exc}") from exc


def _check_chain(chain: Any, what: str) -> None:
    if not isinstance(chain, list) or not chain:
        raise IndexLoadError(f"{what}: chain 은 비어 있지 않은 리스트여야 한다")
    if len(chain) > MAX_CHAIN:
        # AC-B-010-8 — 홉이 늘수록 "응답이 지시한 곳으로 간다"에 가까워진다.
        raise IndexLoadError(
            f"{what}: chain 길이는 최대 {MAX_CHAIN} 다 (현재 {len(chain)}) — AC-B-010-8"
        )
    for index, step in enumerate(chain):
        label = f"{what}.chain[{index}]"
        if not isinstance(step, dict):
            raise IndexLoadError(f"{label}: 매핑이어야 한다")
        _check_request_template(_require_str(step.get("request"), f"{label}.request"), label)
        kind = step.get("response_kind")
        if kind is not None and kind not in RESPONSE_KINDS:
            raise IndexLoadError(f"{label}: response_kind 는 {RESPONSE_KINDS} 중 하나다")
        is_last = index == len(chain) - 1
        select = step.get("select")
        if select is None:
            if not is_last:
                raise IndexLoadError(f"{label}: 마지막이 아닌 단계는 select 가 필수다")
            continue
        _require_str(select, f"{label}.select")
        _check_pattern(step.get("value_pattern"), label)
        _require_str(step.get("bind"), f"{label}.bind")
        if step.get("response_kind") != "json":
            raise IndexLoadError(f"{label}: 값을 뽑는 단계는 response_kind: json 이어야 한다")


def _check_entry(entry: Any, index: int) -> None:
    label = f"entries[{index}]"
    if not isinstance(entry, dict):
        raise IndexLoadError(f"{label}: 매핑이어야 한다")

    host = _require_str(entry.get("host"), f"{label}.host")
    if "{" in host:
        raise IndexLoadError(f"{label}.host: 치환자를 쓸 수 없다")

    pattern = _require_str(entry.get("url_pattern"), f"{label}.url_pattern")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise IndexLoadError(f"{label}.url_pattern: 컴파일 실패 — {exc}") from exc

    # AC-B-010-15 — 출처와 확인 시점이 없는 항목은 검증할 수 없는 주장이다.
    source = _require_str(entry.get("source"), f"{label}.source")
    # SPEC:278 은 `https` URL 을 요구한다. `http://` 출처는 중간자가 바꿔 쓸 수 있어
    # "검증 가능한 주장"이 되지 못한다 — 계약대로 https 만 받는다 (라운드 8 MEDIUM).
    # 접두사가 아니라 **파싱해서** 본다. `"https://"` 는 접두사 검사를 통과하지만
    # 호스트가 없어 아무것도 가리키지 않는다 — 출처 없는 항목과 같다 (라운드 9 MEDIUM).
    source_parts = urlsplit(source)
    if source_parts.scheme != "https" or not source_parts.hostname:
        raise IndexLoadError(
            f"{label}.source: 공식 문서는 호스트가 있는 https URL 이어야 한다 "
            f"(AC-B-010-15) — {source!r}"
        )
    verified_at = _require_str(entry.get("verified_at"), f"{label}.verified_at")
    if not _DATE.match(verified_at):
        raise IndexLoadError(f"{label}.verified_at: YYYY-MM-DD 여야 한다 — {verified_at!r}")

    has_endpoints = entry.get("endpoints") is not None
    has_chain = entry.get("chain") is not None
    if has_endpoints == has_chain:
        raise IndexLoadError(f"{label}: endpoints 와 chain 중 정확히 하나여야 한다")

    if has_chain:
        _check_chain(entry.get("chain"), label)
        return

    endpoints = entry.get("endpoints")
    if not isinstance(endpoints, list) or not endpoints:
        raise IndexLoadError(f"{label}.endpoints: 비어 있지 않은 리스트여야 한다")
    for position, endpoint in enumerate(endpoints):
        _check_request_template(
            _require_str(endpoint, f"{label}.endpoints[{position}]"),
            f"{label}.endpoints[{position}]",
        )
    kind = entry.get("response_kind")
    if kind not in RESPONSE_KINDS:
        raise IndexLoadError(f"{label}.response_kind: {RESPONSE_KINDS} 중 하나여야 한다")
    if kind == "json":
        _require_str(entry.get("content_pointer"), f"{label}.content_pointer")


def load(path: Path | None = None) -> list[dict[str, Any]]:
    """인덱스를 읽고 로드 시점 제약을 전부 확인한다. 위반은 IndexLoadError (exit 3).

    출하 인덱스가 아직 없으면 빈 목록이다 — Phase 0 이 조용히 꺼질 뿐 실패가 아니다.
    """
    target = path or observe.api_index_path()
    if path is None and not target.exists():
        return []
    if not target.exists():
        raise IndexLoadError(f"API 인덱스가 없다: {target}")

    try:
        data = yamlio.loads(target.read_text(encoding="utf-8"))
    except yamlio.YamlError as exc:
        raise IndexLoadError(f"API 인덱스 파싱 실패: {exc}") from exc
    if data is None:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise IndexLoadError("API 인덱스 최상위는 `entries:` 리스트여야 한다")

    entries = data["entries"]
    if len(entries) > MAX_ENTRIES:
        # AC-B-010-15 — NG-9 가 지문표에서 막은 "사이트 목록의 무한 증식"을
        # 인덱스에서는 상한으로 막는다. 인덱스는 호스트를 적는 것이 존재 이유라
        # 리터럴 금지 린트를 쓸 수 없기 때문이다.
        raise IndexLoadError(
            f"API 인덱스는 최대 {MAX_ENTRIES} 항목이다 (현재 {len(entries)}) — AC-B-010-15"
        )
    for index, entry in enumerate(entries):
        _check_entry(entry, index)
    return list(entries)


_cache: dict[str, list[dict[str, Any]]] = {}


def load_cached(path: str | None) -> list[dict[str, Any]]:
    """engine 이 선검증하고 fetcher 가 다시 부르는 구조라 같은 파일을 두 번 파싱하지 않는다.

    캐시 키에 mtime 을 섞지 않는다 — 한 프로세스 안에서 인덱스가 바뀌는 상황을
    지원할 이유가 없고, 섞으면 "검증한 것"과 "실행한 것"이 달라질 수 있다.
    """
    key = path or ""
    if key not in _cache:
        _cache[key] = load(Path(path) if path else None)
    return _cache[key]


# ── 매칭 ────────────────────────────────────────────────────────────────


def entry_for(entries: list[dict[str, Any]], url: str) -> tuple[dict[str, Any], dict[str, str]] | None:
    """AC-B-010-2 — 인덱스에 항목이 없으면 시도하지 않는다. URL 을 추측하지 않는다."""
    parts = urlsplit(url)
    netloc = (parts.netloc or "").lower()
    hostname = (parts.hostname or "").lower()
    path = parts.path or "/"
    for entry in entries:
        host = str(entry.get("host", "")).lower()
        if host not in (netloc, hostname):
            continue
        match = re.search(str(entry["url_pattern"]), path)
        if match is None:
            continue
        return entry, {k: v for k, v in match.groupdict().items() if v is not None}
    return None


# ── 조립 ────────────────────────────────────────────────────────────────


def substitute(template: str, binds: dict[str, str]) -> str:
    """치환자를 채운다. 세그먼트를 벗어나는 값은 거부한다 (AC-B-010-11)."""

    def _one(match: re.Match) -> str:
        name = match.group(1)
        if name not in binds:
            raise Rejected(f"치환할 값이 없다: {{{name}}}")
        value = binds[name]
        if not value:
            raise Rejected(f"빈 값으로 치환할 수 없다: {{{name}}}")
        for bad in SEGMENT_FORBIDDEN:
            if bad in value:
                raise Rejected(
                    f"{{{name}}} 값에 경로 세그먼트를 벗어나는 문자 {bad!r} 가 있다 (AC-B-010-11)"
                )
        if any(ch.isspace() for ch in value):
            raise Rejected(
                f"{{{name}}} 값에 공백류가 있다 — 서버가 떼어 내면 세그먼트가 달라진다 (AC-B-010-11)"
            )
        if value in SEGMENT_DOT_ONLY:
            raise Rejected(
                f"{{{name}}} 값이 상대 경로 세그먼트 {value!r} 다 (AC-B-010-11)"
            )
        return value

    rendered = _PLACEHOLDER.sub(_one, template)
    # 값 단위 검사를 통과한 값들이 리터럴과 붙어 만든 결과를 마지막으로 본다.
    # 로드 검사가 이미 걸렀더라도 이중으로 본다 — 값 검사와 같은 이유다.
    problem = _bad_path_segment(rendered)
    if problem is not None:
        raise Rejected(f"치환 결과가 세그먼트 규칙을 어긴다 — {problem} (AC-B-010-11)")
    return rendered


def select_scalar(payload: Any, pointer: str) -> Any:
    """점 표기 경로로 값을 하나 꺼낸다. 없으면 None."""
    node = payload
    for token in pointer.split("."):
        if isinstance(node, dict):
            if token not in node:
                return None
            node = node[token]
        elif isinstance(node, list):
            if not token.isdigit():
                return None
            position = int(token)
            if position >= len(node):
                return None
            node = node[position]
        else:
            return None
    return node


def _as_scalar(value: Any, pointer: str) -> str:
    """AC-B-010-9 — 다음 단계로 넘기는 값은 스칼라 1개뿐이다."""
    if isinstance(value, bool) or value is None:
        raise Rejected(f"{pointer}: 스칼라가 아니다 ({type(value).__name__})")
    if isinstance(value, (dict, list)):
        raise Rejected(
            f"{pointer}: 객체·배열은 다음 단계로 넘길 수 없다 (AC-B-010-9)"
        )
    if not isinstance(value, (str, int, float)):
        raise Rejected(f"{pointer}: 스칼라가 아니다 ({type(value).__name__})")
    return str(value)


# ── 실행 ────────────────────────────────────────────────────────────────


class _BudgetExhausted(Exception):
    """AC-B-010-14 — 항목당 요청 예산을 다 썼다."""


class _Blocked(Exception):
    def __init__(self, rule: str | None, detail: str) -> None:
        super().__init__(detail)
        self.rule = rule
        self.detail = detail


def _guard(url: str, *, timeout: float) -> None:
    """AC-B-010-13 — 조립된 URL 도 SSRF 가드와 robots 를 **새로** 통과해야 한다.

    첫 요청이 통과했다는 사실은 두 번째 요청의 근거가 아니다. 호스트가 다를 수 있고
    (AC-B-010-3), 같은 호스트라도 경로가 다르면 robots 판정이 다르다.
    """
    try:
        verdict = policy.check_url(url)
    except policy.UnresolvableHost as exc:
        raise _Blocked("private_range", str(exc)) from exc
    if not verdict.allowed:
        raise _Blocked(verdict.rule, verdict.detail)
    robots = policy.robots_verdict(url, timeout=timeout)
    if not robots.allowed:
        raise _Blocked(robots.rule, robots.detail)


def _classify_block(status: int, body: str, headers: dict[str, str]) -> str | None:
    """AC-B-010-5·6 — 인증·쿼터는 뚫는 대상이 아니라 보고하는 사실이다."""
    if status == 429:
        return "rate_limited"
    haystack = (body[:4096] + " " + " ".join(headers.values())).lower()
    if status == 403 and any(hint in haystack for hint in _QUOTA_HINTS):
        return "rate_limited"
    if status == 401:
        return "auth_wall"
    if status == 403 and any(hint in haystack for hint in _KEY_HINTS):
        return "auth_wall"
    return None


def _accept_for(kind: str) -> str:
    return "application/json,*/*;q=0.8" if kind == "json" else "text/html,*/*;q=0.8"


def _same_origin_hop(origin: str):
    """AC-B-010-12 — 리디렉션으로 오리진을 벗어나지 않는다.

    "스킴과 호스트는 응답에서 오지 않는다"는 계약은 **바인딩만** 두고 한 말이 아니다.
    `302 Location:` 은 응답이 우리를 다른 호스트로 보내는 가장 직접적인 수단이고,
    그렇게 옮겨 간 요청은 인덱스에 없는 호스트로 나가면서도 `endpoint` 에는 인덱스
    URL 만 남아 SC-9 의 "인덱스 외 요청 0건" 감사를 그대로 통과한다.
    같은 오리진 안의 리디렉션(끝 슬래시·경로 정규화)은 `PHASE0_MAX_REDIRECTS` 홉까지
    허용한다 — 그 경우에도 경로가 달라지므로 robots 는 `policy.hop_guard` 가 홉마다
    다시 본다. `http→https` 업그레이드는 **허용되지 않는다**: `policy.origin_of` 는
    스킴을 포함하므로 오리진 이탈로 걸린다. 그것이 맞다 — AC-B-010-12 는 스킴도
    응답에서 오지 않는다고 못박고 있고, 인덱스에 https 로 적으면 될 일이다.
    """

    hops = {"n": 0}

    def _check(next_url: str) -> None:
        # 오리진 검사가 **먼저**다. hop_guard 는 robots.txt 를 받으러 네트워크에 나가므로,
        # 순서를 뒤집으면 "인덱스 밖 호스트로는 요청하지 않는다"는 약속을 지키면서도
        # 그 호스트의 /robots.txt 는 이미 한 번 두드린 뒤가 된다 (리뷰 라운드 2, #1).
        if policy.origin_of(next_url) != origin:
            raise transport.PolicyBlocked(
                "redirect_hop",
                f"Phase 0 리디렉션이 오리진을 벗어났다: {next_url} (AC-B-010-12)",
            )
        # 홉 수도 여기서 **강제**한다. 전송 계층의 상한(5)은 일반 취득 기준이고,
        # 항목당 요청 총량(`DISPATCH_BUDGET`)은 Phase 0 이 홉을 좁게 묶는다는 전제
        # 위에 서 있다 — 그 전제를 가정으로 두면 상한 산식이 거짓이 된다 (라운드 3).
        # 상한은 2 다: 끝 슬래시 정규화 뒤 한 번 더 정규화하는 API 가 실재하므로
        # 1 로 잡으면 정상 항목이 정책 위반처럼 막힌다 (라운드 4).
        # 네트워크에 나가기 전에 센다.
        hops["n"] += 1
        if hops["n"] > PHASE0_MAX_REDIRECTS:
            raise transport.PolicyBlocked(
                "redirect_hop",
                f"Phase 0 리디렉션이 {PHASE0_MAX_REDIRECTS} 홉을 넘겼다: {next_url}",
            )
        policy.hop_guard(next_url)

    return _check


def _reserve(budget: list[int]) -> None:
    """요청 예산이 남았는지 **요청을 준비하기 전에** 확인한다 (AC-B-010-14)."""
    if budget[0] <= 0:
        raise _BudgetExhausted


def _request(url: str, *, kind: str, timeout: float, budget: list[int]) -> transport.Response:
    _reserve(budget)
    budget[0] -= 1
    origin = policy.origin_of(url)
    if origin is None:
        raise Rejected(f"오리진을 판정할 수 없는 URL: {url}")
    return transport.request(
        url,
        timeout=timeout,
        impersonate=None,          # AC-B-010-4 — 임퍼소네이션 없음
        user_agent=HONEST_UA,
        accept=_accept_for(kind),
        hop_check=_same_origin_hop(origin),
    )


def _license_of(payload: Any) -> str | None:
    """AC-B-010-18 — 원본이 라이선스를 명시하면 그대로 싣는다. 추측하지 않는다."""
    if isinstance(payload, dict):
        for pointer in ("content_license", "items.0.content_license"):
            value = select_scalar(payload, pointer)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _content_from(
    response: transport.Response, kind: str, pointer: str | None, intent: str
) -> tuple[str | None, str | None, str | None]:
    """(markdown, title, content_license). 본문을 못 찾으면 markdown 이 None."""
    from . import extract  # 순환 임포트 회피

    if kind == "json":
        try:
            payload = json.loads(response.text())
        except (ValueError, TypeError):
            return None, None, None
        license_value = _license_of(payload)
        raw = select_scalar(payload, pointer or "")
        if not isinstance(raw, str) or not raw.strip():
            return None, None, license_value
        # API 가 돌려주는 본문은 HTML 조각인 경우가 흔하다 (실측: StackExchange
        # `items[0].body`). 같은 추출기를 태워 HTML 경로와 같은 형태로 맞춘다.
        markdown, title = extract.extract_for(intent, raw, response.final_url)
        if not markdown or not markdown.strip():
            markdown = raw.strip()
        return markdown, title, license_value

    markdown, title = extract.extract_for(intent, response.text(), response.final_url)
    if not markdown or not markdown.strip():
        return None, None, None
    return markdown, title, None


def run(
    entry: dict[str, Any],
    captures: dict[str, str],
    *,
    intent: str,
    timeout: float,
    on_attempt,
) -> Phase0Outcome:
    """항목 하나를 실행한다. `on_attempt(status, elapsed_ms, outcome)` 로 시도를 알린다."""
    budget = [REQUEST_BUDGET]
    outcome = Phase0Outcome()

    try:
        with transport.dispatch_budget(DISPATCH_BUDGET):
            if entry.get("chain") is not None:
                return _run_chain(entry, captures, intent=intent, timeout=timeout,
                                  budget=budget, on_attempt=on_attempt, outcome=outcome)
            return _run_endpoints(entry, captures, intent=intent, timeout=timeout,
                                  budget=budget, on_attempt=on_attempt, outcome=outcome)
    except Rejected as exc:
        # 요청하지 않고 중단한 경우다 — 무엇이 막았는지는 남긴다.
        outcome.notes.append(f"rejected: {exc}")
        return outcome
    except _BudgetExhausted:
        outcome.notes.append(f"budget: 항목당 요청 {REQUEST_BUDGET} 회를 다 썼다")
        return outcome
    except transport.BudgetExceeded as exc:
        # 우리 상한이지 상대의 판정이 아니다 — `policy_blocked` 로 올리지 않는다.
        # 여기까지 왔다는 것은 홉·robots 상한 중 하나가 산식과 어긋났다는 뜻이므로
        # 사유를 그대로 남긴다 (NG-10 — 다른 이유로 세탁하지 않는다).
        outcome.notes.append(f"budget: 실제 요청 {exc.limit} 회를 넘겼다 ({exc.url})")
        return outcome
    except _Blocked as exc:
        outcome.reason = "policy_blocked"
        outcome.policy_rule = exc.rule
        outcome.notes.append(f"policy_blocked/{exc.rule or '-'}: {exc.detail}")
        return outcome
    except transport.PolicyBlocked as exc:
        outcome.reason = "policy_blocked"
        outcome.policy_rule = exc.rule
        outcome.notes.append(f"policy_blocked/{exc.rule}: {exc.detail}")
        return outcome
    except transport.NetworkError as exc:
        outcome.notes.append(f"network: {exc}")
        return outcome


def _emit_attempt(on_attempt, outcome, url, response, kind, blocked) -> None:
    """감사에는 **실제로 닿은 URL** 을 남긴다.

    리디렉션은 같은 오리진으로만 허용되지만(AC-B-010-12) 경로는 달라질 수 있다.
    요청한 URL 만 적으면 SC-9 감사가 보는 것은 우리의 의도이지 실제 요청이 아니다.
    """
    landed = response.final_url or url
    if landed != url:
        outcome.notes.append(f"redirect: {url} -> {landed}")
    on_attempt(landed, kind, response.status, response.elapsed_ms,
               "wall" if blocked == "auth_wall" else
               "challenge" if blocked else
               "success" if 200 <= response.status < 300 else "error")


def _run_chain(entry, captures, *, intent, timeout, budget, on_attempt, outcome):
    chain = entry["chain"]
    binds = dict(captures)
    for index, step in enumerate(chain):
        url = substitute(str(step["request"]), binds)
        _reserve(budget)          # 라운드 4 — `_guard` 의 robots 요청보다 먼저 센다
        _guard(url, timeout=timeout)
        kind = str(step.get("response_kind") or entry.get("response_kind") or "html")
        response = _request(url, kind=kind, timeout=timeout, budget=budget)
        blocked = _classify_block(response.status, response.text(), response.headers)
        _emit_attempt(on_attempt, outcome, url, response, kind, blocked)
        if blocked is not None:
            outcome.reason = blocked
            return outcome
        if not (200 <= response.status < 300):
            outcome.notes.append(f"step{index}: status={response.status}")
            return outcome

        if index == len(chain) - 1:
            markdown, title, license_value = _content_from(
                response, kind, step.get("content_pointer") or entry.get("content_pointer"), intent
            )
            outcome.markdown = markdown
            outcome.title = title
            outcome.final_url = response.final_url
            outcome.content_type = response.headers.get("content-type", "")
            outcome.content_license = license_value
            return outcome

        # 다음 단계로 넘길 값 — 스칼라 1개, 앵커 패턴 일치, 세그먼트 1개
        try:
            payload = json.loads(response.text())
        except (ValueError, TypeError) as exc:
            raise Rejected(f"step{index}: JSON 이 아니다 — {exc}") from exc
        pointer = str(step["select"])
        value = _as_scalar(select_scalar(payload, pointer), pointer)
        pattern = str(step["value_pattern"])
        # fullmatch 다. `$` 하나만 믿으면 끝에 개행이 붙은 값이 그대로 통과한다.
        if re.fullmatch(pattern, value) is None:
            raise Rejected(f"step{index}: {pointer} 값이 value_pattern 과 다르다 (AC-B-010-10)")
        binds[str(step["bind"])] = value
    return outcome


def _run_endpoints(entry, captures, *, intent, timeout, budget, on_attempt, outcome):
    kind = str(entry["response_kind"])
    pointer = entry.get("content_pointer")
    for endpoint in entry["endpoints"]:
        url = substitute(str(endpoint), captures)
        # 예산 확인이 `_guard` **앞**이다. `_guard` 는 robots.txt 를 받으러 나가므로,
        # 순서를 뒤집으면 이미 예산이 0 인 상태에서 네 번째 오리진의 robots 를 실제로
        # 두드린 뒤에야 예산 소진을 알린다 — "오리진 수 <= 요청 수"가 거짓이 되고,
        # 쏘지 않기로 한 엔드포인트의 정책 판정이 항목의 결과로 보고된다 (라운드 4).
        _reserve(budget)
        _guard(url, timeout=timeout)
        response = _request(url, kind=kind, timeout=timeout, budget=budget)
        blocked = _classify_block(response.status, response.text(), response.headers)
        _emit_attempt(on_attempt, outcome, url, response, kind, blocked)
        if blocked is not None:
            outcome.reason = blocked
            return outcome
        if not (200 <= response.status < 300):
            continue
        markdown, title, license_value = _content_from(response, kind, pointer, intent)
        if markdown is None:
            if license_value and outcome.content_license is None:
                outcome.content_license = license_value
            continue
        outcome.markdown = markdown
        outcome.title = title
        outcome.final_url = response.final_url
        outcome.content_type = response.headers.get("content-type", "")
        outcome.content_license = license_value
        return outcome
    return outcome
