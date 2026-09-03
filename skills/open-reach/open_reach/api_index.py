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

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import __version__, observe, policy, transport, yamlio
from .policy import DEFAULT_ROBOTS_MODE

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

# R5 — 쿼리 값 위치의 금지 문자. 경로 금지 집합에 `&`·`=` 를 더한다. 값이 쿼리
# **구조**(파라미터 경계·키/값 경계)를 바꿀 수 없게 하기 위해서다 (AC-B-010-11 R5).
QUERY_FORBIDDEN = SEGMENT_FORBIDDEN + ("&", "=")

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


def _check_request_template(
    template: str, what: str, *, allow_query_placeholders: bool = False
) -> None:
    """AC-B-010-12 — 스킴과 호스트는 응답에서 오지 않는다.

    치환자는 기본적으로 **경로에만** 둔다. 쿼리에 두면 응답이 쿼리 구조를 바꿀 수
    있고, 스킴·호스트에 두면 응답이 우리를 다른 서버로 보낼 수 있다.

    예외(AC-B-010-11 R5 개정): chain 없는 endpoints 템플릿의 치환 입력은 입력 URL
    캡처 그룹뿐이라 "응답이 쿼리 구조를 바꾼다"가 성립하지 않는다 — 그 호출자만
    allow_query_placeholders=True 를 넘긴다 (실측: Bluesky XRPC 는 쿼리 파라미터
    전용이라 이 예외 없이는 표현할 수 없다). 값의 `&`·`=` 는 substitute 가
    QUERY_FORBIDDEN 으로 막고, 프래그먼트는 어느 쪽이든 거부한다.
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
    checked = [("프래그먼트", parts.fragment)]
    if allow_query_placeholders:
        _check_query_placeholders(parts.query, what, template)
    else:
        checked.append(("쿼리", parts.query))
    for field_name, value in checked:
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


def _check_query_placeholders(query: str, what: str, template: str) -> None:
    """R5 예외의 폭 — 치환자는 쿼리 **값 위치**에만. 파라미터 이름은 정적이다.

    이름 위치 치환자(`?{key}=1`)는 값의 금지 문자(`&`·`=`)와 무관하게, 캡처가
    "어떤 파라미터를 세팅할지" 자체를 고르게 한다 — 요청 의미가 입력 URL 에
    좌우된다. R5 가 연 것은 값 위치뿐이므로 이름 위치는 로드 시점에 거부한다.
    치환자가 되다 만 중괄호(`{bad-name}` 등)도 리터럴로 새 나가기 전에 거부한다.
    (codex 리뷰 R5-H2)
    """
    for param in query.split("&"):
        name, _, value = param.partition("=")
        if "{" in name or "}" in name:
            raise IndexLoadError(
                f"{what}: 쿼리 파라미터 이름 위치에 치환자·중괄호를 쓸 수 없다 — "
                f"값 위치만 허용된다 (AC-B-010-11 R5) — {template!r}"
            )
        residue = _PLACEHOLDER.sub("", value)
        if "{" in residue or "}" in residue:
            raise IndexLoadError(
                f"{what}: 쿼리 값의 중괄호가 올바른 치환자가 아니다 — {template!r}"
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


def _check_provenance(mapping: dict[str, Any], label: str) -> None:
    """AC-B-010-15 — 출처와 확인 시점이 없는 항목은 검증할 수 없는 주장이다.

    검색 선언(AC-B-014-4)도 같은 의무를 진다 — 요청을 만들지 않는 선언이라도
    "이 URL 이 검색이다"는 주장이며, 주장은 출처 없이는 성립하지 않는다.
    """
    source = _require_str(mapping.get("source"), f"{label}.source")
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
    # 포트가 범위(0..65535)를 벗어나면 `.port` 접근이 ValueError 를 낸다. 이 검사를
    # 빼면 `https://example.invalid:99999/docs` 처럼 **열 수 없는** URL 이 "검증 가능한
    # 출처"로 통과한다 — 출처는 사람이 확인하러 가는 주소이므로 열리지 않으면 주장이
    # 성립하지 않는다 (라운드 10 MEDIUM, R2-R10-M1).
    try:
        source_parts.port
    except ValueError:
        raise IndexLoadError(
            f"{label}.source: 포트가 범위(0..65535)를 벗어났다 (AC-B-010-15) — {source!r}"
        ) from None
    verified_at = _require_str(mapping.get("verified_at"), f"{label}.verified_at")
    if not _DATE.match(verified_at):
        raise IndexLoadError(f"{label}.verified_at: YYYY-MM-DD 여야 한다 — {verified_at!r}")


def _check_host(value: Any, label: str) -> str:
    """host 선언 공통 검사 — 치환자·userinfo 금지 (codex 리뷰 R5-M1 잔존 경로).

    `user@h.invalid` 를 선언에 적으면 `_host_matches` 의 netloc 정확 일치 분기가
    자격증명 실린 URL 을 통과시킨다 — 선언 쪽에서 로드 시점에 막아야 런타임
    가드("@ 실린 URL 은 매치 안 됨")와 합쳐 경로가 완전히 닫힌다.
    """
    host = _require_str(value, f"{label}.host")
    if "{" in host:
        raise IndexLoadError(f"{label}.host: 치환자를 쓸 수 없다")
    if "@" in host:
        raise IndexLoadError(
            f"{label}.host: userinfo(@)를 쓸 수 없다 — 이 도구는 자격증명을 취급하지 않는다"
        )
    return host


def _check_search(decl: Any, index: int) -> None:
    """AC-B-014 — 검색 선언. 판정 전용이라 요청을 만들지 않지만, 출처 의무는 진다."""
    label = f"search[{index}]"
    if not isinstance(decl, dict):
        raise IndexLoadError(f"{label}: 매핑이어야 한다")
    _check_host(decl.get("host"), label)
    pattern = _require_str(decl.get("url_pattern"), f"{label}.url_pattern")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise IndexLoadError(f"{label}.url_pattern: 컴파일 실패 — {exc}") from exc
    _check_provenance(decl, label)


_SOURCE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# 점 표기 경로 (select_scalar 규약). 대문자를 허용하는 것은 Crossref 의 `URL` 처럼
# 실재하는 필드명 때문이다. 슬래시·중괄호는 허용하지 않는다 — 경로는 응답 안을
# 가리킬 뿐, URL 을 만들거나 치환에 참여하지 않는다.
_POINTER = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")
LINK_TRANSFORMS = ("none", "percent")

# 종류별로 의미 있는 키. 여기에 없는 키가 실리면 로드 시점에 거절한다 — html 소스에
# `result_pointer` 를 붙여 놓고 "왜 결과가 안 나오지" 하는 조용한 무동작을 막는다.
_SOURCE_COMMON = frozenset(
    {
        "name",
        "host",
        "kind",
        "query_template",
        "exclude_hosts",
        "source",
        "verified_at",
        "note",
    }
)
_SOURCE_BY_KIND = {
    "json": frozenset({"result_pointer", "link_pointer", "title_pointer"}),
    "html": frozenset({"result_link_pattern", "link_transform", "title_pattern"}),
}


def _check_pointer(value: Any, label: str) -> str:
    pointer = _require_str(value, label)
    if not _POINTER.match(pointer):
        raise IndexLoadError(f"{label}: 점 표기 경로여야 한다 — {pointer!r}")
    return pointer


def _check_capture_pattern(raw: Any, label: str) -> None:
    """캡처 그룹이 정확히 하나여야 한다 — 무엇을 링크로 볼지가 모호하면 안 된다."""
    pattern = _require_str(raw, label)
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise IndexLoadError(f"{label}: 컴파일 실패 — {exc}") from exc
    if compiled.groups != 1:
        raise IndexLoadError(
            f"{label}: 캡처 그룹이 정확히 1개여야 한다 (현재 {compiled.groups}개)"
        )


_EXCLUDE_HOST = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")
MAX_EXCLUDE_HOSTS = 8


def _check_exclude_hosts(value: Any, label: str) -> tuple[str, ...]:
    """후보에서 걷어낼 호스트 목록 — 소스가 **자기 기계장치를 결과처럼 내는** 경우용.

    실측 계기: DuckDuckGo lite 는 광고를 유기적 결과와 **똑같은** `/l/?uddg=` 래퍼와
    `class='result-link'` 로 감싸 내보낸다. 정규식으로는 갈라낼 수 없고, 갈라지는
    지점은 래핑이 풀린 **목적지**다 — 광고의 목적지는 `duckduckgo.com/y.js` 로,
    검색 엔진 자신이다. 광고를 검색 결과라고 내놓는 것은 사실이 아닌 주장이라
    (NG-10) 걷어낸다.

    코드에 벤더 이름을 박지 않고 **선언**으로 두는 이유: 이런 규칙은 벤더마다 다르고
    시간이 지나면 바뀐다. 인덱스에 적혀 있으면 `source`·`verified_at` 과 같은 자리에서
    함께 검토된다.
    """
    if value is None:
        return ()
    if not isinstance(value, list):
        raise IndexLoadError(f"{label}.exclude_hosts: 리스트여야 한다")
    if len(value) > MAX_EXCLUDE_HOSTS:
        raise IndexLoadError(
            f"{label}.exclude_hosts: 최대 {MAX_EXCLUDE_HOSTS} 개다 (현재 {len(value)})"
        )
    hosts: list[str] = []
    for position, raw in enumerate(value):
        host = _require_str(raw, f"{label}.exclude_hosts[{position}]")
        if not _EXCLUDE_HOST.match(host):
            raise IndexLoadError(
                f"{label}.exclude_hosts[{position}]: 소문자 호스트명이어야 한다 "
                f"(스킴·포트·경로 없이) — {host!r}"
            )
        hosts.append(host)
    return tuple(hosts)


def _check_search_source(decl: Any, index: int) -> None:
    """R6/W5 — 질의를 URL 후보 목록으로 바꾸는 소스 선언.

    기존 `search:` 와 **다른 섹션**이다. 그쪽은 "이 URL 은 검색 결과 페이지다"라는
    판정 전용 선언이라 요청을 만들지 않는다(AC-B-014-1). 이쪽은 실제로 요청한다 —
    한 섹션에 섞으면 "요청 없음" 계약이 어느 항목에 걸린 것인지 읽는 사람이 알 수 없다.

    `query_template` 의 치환자는 **사용자 질의 하나뿐**이고, 값 위치에만 놓인다.
    스킴·호스트·파라미터 이름에 치환자를 못 쓰는 것은 entries 와 같은 규칙이며
    (AC-B-010-11·12), 런타임 치환은 `substitute` 가 아니라 퍼센트 인코딩이다 —
    이유는 search.build_url 에 적었다.
    """
    label = f"search_sources[{index}]"
    if not isinstance(decl, dict):
        raise IndexLoadError(f"{label}: 매핑이어야 한다")

    name = _require_str(decl.get("name"), f"{label}.name")
    if not _SOURCE_NAME.match(name):
        raise IndexLoadError(f"{label}.name: 소문자·숫자·-_ 로만 이뤄져야 한다 — {name!r}")

    host = _check_host(decl.get("host"), label)
    kind = _require_str(decl.get("kind"), f"{label}.kind")
    if kind not in RESPONSE_KINDS:
        raise IndexLoadError(f"{label}.kind: {RESPONSE_KINDS} 중 하나여야 한다 — {kind!r}")

    allowed = _SOURCE_COMMON | _SOURCE_BY_KIND[kind]
    extra = sorted(set(decl) - allowed)
    if extra:
        raise IndexLoadError(f"{label}: kind={kind} 에 쓰이지 않는 키가 있다 — {extra}")

    template = _require_str(decl.get("query_template"), f"{label}.query_template")
    _check_request_template(
        template, f"{label}.query_template", allow_query_placeholders=True
    )
    names = set(_PLACEHOLDER.findall(template))
    if names != {"query"}:
        raise IndexLoadError(
            f"{label}.query_template: 치환자는 {{query}} 하나뿐이어야 한다 — {sorted(names)}"
        )
    # 선언한 host 와 템플릿의 netloc 이 다르면 `--sources` 로 고른 것과 실제로
    # 두드리는 곳이 갈린다. 정확 일치를 요구한다 — 포트를 쓰려면 host 에도 적는다.
    if urlsplit(template).netloc.lower() != host.lower():
        raise IndexLoadError(
            f"{label}: query_template 의 호스트가 선언과 다르다 — "
            f"{urlsplit(template).netloc!r} != {host!r}"
        )

    _check_exclude_hosts(decl.get("exclude_hosts"), label)

    if kind == "json":
        _check_pointer(decl.get("result_pointer"), f"{label}.result_pointer")
        if "link_pointer" in decl:
            _check_pointer(decl["link_pointer"], f"{label}.link_pointer")
        if "title_pointer" in decl:
            _check_pointer(decl["title_pointer"], f"{label}.title_pointer")
    else:
        _check_capture_pattern(decl.get("result_link_pattern"), f"{label}.result_link_pattern")
        if "title_pattern" in decl:
            _check_capture_pattern(decl["title_pattern"], f"{label}.title_pattern")
        transform = decl.get("link_transform", "none")
        if transform not in LINK_TRANSFORMS:
            raise IndexLoadError(
                f"{label}.link_transform: {LINK_TRANSFORMS} 중 하나여야 한다 — {transform!r}"
            )

    _check_provenance(decl, label)


def _check_entry(entry: Any, index: int) -> None:
    label = f"entries[{index}]"
    if not isinstance(entry, dict):
        raise IndexLoadError(f"{label}: 매핑이어야 한다")

    _check_host(entry.get("host"), label)

    pattern = _require_str(entry.get("url_pattern"), f"{label}.url_pattern")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise IndexLoadError(f"{label}.url_pattern: 컴파일 실패 — {exc}") from exc

    _check_provenance(entry, label)

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
        # endpoints 항목에는 chain 이 없다(위 상호배타 검사) — 응답 유래 값이 섞일
        # 수 없는 유일한 템플릿이라서만 쿼리 치환자를 허용한다 (AC-B-010-11 R5).
        _check_request_template(
            _require_str(endpoint, f"{label}.endpoints[{position}]"),
            f"{label}.endpoints[{position}]",
            allow_query_placeholders=True,
        )
    kind = entry.get("response_kind")
    if kind not in RESPONSE_KINDS:
        raise IndexLoadError(f"{label}.response_kind: {RESPONSE_KINDS} 중 하나여야 한다")
    if kind == "json":
        _require_str(entry.get("content_pointer"), f"{label}.content_pointer")


@dataclass(frozen=True)
class ApiIndex:
    """로드 검증을 통과한 인덱스 전체 — 라우팅 항목과 검색 선언 (R5).

    검색 선언은 판정 전용이다(AC-B-014 — 요청을 만들지 않는다). entries 만 쓰던
    호출자가 선언의 존재를 모른 채 지나치지 않도록 한 타입에 함께 담는다.
    """

    entries: tuple[dict[str, Any], ...] = ()
    search: tuple[dict[str, Any], ...] = ()
    # R6/W5 — 질의를 URL 후보로 바꾸는 소스. `search` 와 달리 실제로 요청한다.
    search_sources: tuple[dict[str, Any], ...] = ()


def load(path: Path | None = None) -> ApiIndex:
    """인덱스를 읽고 로드 시점 제약을 전부 확인한다. 위반은 IndexLoadError (exit 3).

    출하 인덱스가 아직 없으면 빈 인덱스다 — Phase 0 이 조용히 꺼질 뿐 실패가 아니다.
    """
    target = path or observe.api_index_path()
    if path is None and not target.exists():
        return ApiIndex()
    if not target.exists():
        raise IndexLoadError(f"API 인덱스가 없다: {target}")

    try:
        data = yamlio.loads(target.read_text(encoding="utf-8"))
    except yamlio.YamlError as exc:
        raise IndexLoadError(f"API 인덱스 파싱 실패: {exc}") from exc
    if data is None:
        return ApiIndex()
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise IndexLoadError("API 인덱스 최상위는 `entries:` 리스트여야 한다")

    entries = data["entries"]
    search = data.get("search")
    if search is None:
        search = []
    if not isinstance(search, list):
        raise IndexLoadError("API 인덱스 `search:` 는 리스트여야 한다")
    sources = data.get("search_sources")
    if sources is None:
        sources = []
    if not isinstance(sources, list):
        raise IndexLoadError("API 인덱스 `search_sources:` 는 리스트여야 한다")
    if len(entries) + len(search) + len(sources) > MAX_ENTRIES:
        # AC-B-010-15 (R5 개정) — 상한은 entries·search **합산**이다. NG-9 가
        # 지문표에서 막은 "사이트 목록의 무한 증식"을 인덱스에서는 상한으로 막는데,
        # 선언을 따로 세면 같은 증식이 search 쪽으로 우회한다. 인덱스는 호스트를
        # 적는 것이 존재 이유라 리터럴 금지 린트를 쓸 수 없기 때문이다.
        raise IndexLoadError(
            f"API 인덱스는 entries·search·search_sources 합산 최대 {MAX_ENTRIES} 항목이다 "
            f"(현재 {len(entries)}+{len(search)}+{len(sources)}) — AC-B-010-15"
        )
    for index, entry in enumerate(entries):
        _check_entry(entry, index)
    for index, decl in enumerate(search):
        _check_search(decl, index)
    for index, decl in enumerate(sources):
        _check_search_source(decl, index)
    # 이름은 `--sources` 의 주소다. 중복되면 어느 선언이 선택된 것인지 알 수 없다.
    names = [decl.get("name") for decl in sources]
    duplicated = sorted({n for n in names if names.count(n) > 1})
    if duplicated:
        raise IndexLoadError(f"search_sources 이름이 중복됐다 — {duplicated}")
    return ApiIndex(
        entries=tuple(entries), search=tuple(search), search_sources=tuple(sources)
    )


_cache: dict[str, ApiIndex] = {}


def load_cached(path: str | None) -> ApiIndex:
    """engine 이 선검증하고 fetcher 가 다시 부르는 구조라 같은 파일을 두 번 파싱하지 않는다.

    캐시 키에 mtime 을 섞지 않는다 — 한 프로세스 안에서 인덱스가 바뀌는 상황을
    지원할 이유가 없고, 섞으면 "검증한 것"과 "실행한 것"이 달라질 수 있다.
    """
    key = path or ""
    if key not in _cache:
        _cache[key] = load(Path(path) if path else None)
    # 캐시 원본을 내주지 않는다 — entries·search 의 dict 는 가변이라, 원본을 돌리면
    # 한 호출자의 변형이 검증·출처·상한을 거치지 않은 채 이후 판정(entry_for·
    # nav_shell 면제)에 스며든다. 복사본 변형은 그 호출자 안에서 끝난다.
    # (codex 리뷰 R5-L1. 항목 수 상한이 20이라 복사 비용은 무시할 수준이다.)
    return copy.deepcopy(_cache[key])


# ── 매칭 ────────────────────────────────────────────────────────────────


def _match_target(parts) -> str:
    """패턴 매칭 대상 — `경로?쿼리` (R5 개정).

    HN `/item?id=N` 처럼 식별자가 쿼리에 있는 표현형을 담으려면 경로만으로는
    부족하다. 쿼리 없는 URL 은 이전과 동일하게 경로만 남으므로 기존 패턴은
    그대로 매치된다 (무회귀 — 출하 stackoverflow 패턴은 미앵커 prefix 매치).
    """
    path = parts.path or "/"
    return path + ("?" + parts.query if parts.query else "")


def _host_matches(declared: str, parts) -> bool:
    """host 선언 대조 (codex 리뷰 R5-M1).

    규칙은 둘이다:
    ① 포트를 적은 선언(`127.0.0.1:8080`)은 netloc 정확 일치 — 다른 포트에
       업히지 않는다.
    ② 포트 없는 선언(`h.invalid`)은 그 호스트의 **모든 포트**를 뜻한다 — 동결
       픽스처 인덱스(us-b-009, SPEC 「SSRF 예외」의 유일한 루프백 예외)가
       `127.0.0.1` 로 선언하는데 픽스처 서버는 매 실행 임시 포트에 뜨므로
       포트를 미리 적는 것이 불가능하다. 선언의 단위는 호스트(운영 주체)다.

    어느 쪽이든 userinfo 실린 URL(`u:p@h.invalid`)은 매치하지 않는다 — 이 도구는
    자격증명을 취급하지 않으므로(NG-1 인접) 인증 의미가 실린 URL 을 "확인된
    선언 대상"으로 판정할 수 없다. hostname 은 urlsplit 이 userinfo 를 걷어낸
    값이라, hostname 비교 단독으로는 이 케이스가 소리 없이 통과한다.
    """
    netloc = (parts.netloc or "").lower()
    hostname = (parts.hostname or "").lower()
    if "@" in netloc:
        # netloc 정확 일치 분기보다 먼저 — 선언 검사(_check_host)가 @ 를 거부하긴
        # 하지만, 이 함수는 선언 출처를 가정하지 않고 스스로 fail-closed 여야 한다.
        return False
    if declared == netloc:
        return True
    return declared == hostname


def entry_for(
    entries: tuple[dict[str, Any], ...] | list[dict[str, Any]], url: str
) -> tuple[dict[str, Any], dict[str, str]] | None:
    """AC-B-010-2 — 인덱스에 항목이 없으면 시도하지 않는다. URL 을 추측하지 않는다."""
    parts = urlsplit(url)
    target = _match_target(parts)
    for entry in entries:
        host = str(entry.get("host", "")).lower()
        if not _host_matches(host, parts):
            continue
        match = re.search(str(entry["url_pattern"]), target)
        if match is None:
            continue
        return entry, {k: v for k, v in match.groupdict().items() if v is not None}
    return None


def is_explicit_search(index: ApiIndex | None, url: str) -> bool:
    """AC-B-014-1·2 — 주어진 URL 이 선언된 검색 엔드포인트인가. 판정 전용, 요청 없음.

    호출자의 계약(AC-B-014-2, 양방향): 명시성을 **얻는** 판정은 입력 URL 로만
    한다 — 리디렉트 도착 URL 로 얻으면 "우발적 검색 페이지 도착"이 명시가 된다.
    반대로 **잃는** 판정에는 도착 URL 을 넣는다 — 선언된 검색 URL 이 선언 밖으로
    리디렉트되면 도착지는 우발이라 면제가 꺼진다(codex 리뷰 R5-H1). 선언이 주는
    것은 detect 의 nav_shell 면제 하나뿐이고, 챌린지 판별·길이 하한은
    그대로다(AC-B-014-3).
    """
    if index is None:
        return False
    parts = urlsplit(url)
    target = _match_target(parts)
    for decl in index.search:
        host = str(decl.get("host", "")).lower()
        if not _host_matches(host, parts):
            continue
        if re.search(str(decl["url_pattern"]), target) is not None:
            return True
    return False


# ── 조립 ────────────────────────────────────────────────────────────────


def substitute(template: str, binds: dict[str, str]) -> str:
    """치환자를 채운다. 위치별 금지 문자를 어기는 값은 거부한다 (AC-B-010-11).

    경로 위치의 값은 세그먼트 1개를 벗어날 수 없고, 쿼리 위치의 값(R5)은 거기에
    `&`·`=` 가 더해진다. 템플릿의 첫 `?` 가 경로와 쿼리를 가르는데, 경로 값의
    `?` 는 금지 문자이므로 이 분할은 치환 뒤에도 유지된다 — 값이 자신의 위치를
    옮길 수 없다.
    """

    def _fill(where: str, forbidden: tuple[str, ...]):
        def _one(match: re.Match) -> str:
            name = match.group(1)
            if name not in binds:
                raise Rejected(f"치환할 값이 없다: {{{name}}}")
            value = binds[name]
            if not value:
                raise Rejected(f"빈 값으로 치환할 수 없다: {{{name}}}")
            for bad in forbidden:
                if bad in value:
                    raise Rejected(
                        f"{{{name}}} 값에 {where} 를 벗어나는 문자 {bad!r} 가 있다 (AC-B-010-11)"
                    )
            if any(ch.isspace() for ch in value):
                raise Rejected(
                    f"{{{name}}} 값에 공백류가 있다 — 서버가 떼어 내면 {where} 가 달라진다 (AC-B-010-11)"
                )
            if value in SEGMENT_DOT_ONLY:
                raise Rejected(
                    f"{{{name}}} 값이 상대 경로 세그먼트 {value!r} 다 (AC-B-010-11)"
                )
            return value

        return _one

    prefix, sep, query = template.partition("?")
    rendered = _PLACEHOLDER.sub(_fill("경로 세그먼트", SEGMENT_FORBIDDEN), prefix)
    if sep:
        rendered += "?" + _PLACEHOLDER.sub(_fill("쿼리 값", QUERY_FORBIDDEN), query)
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


def _guard(url: str, *, timeout: float, robots_mode: str) -> None:
    """AC-B-010-13 — 조립된 URL 도 SSRF 가드와 robots 를 **새로** 통과해야 한다.

    첫 요청이 통과했다는 사실은 두 번째 요청의 근거가 아니다. 호스트가 다를 수 있고
    (AC-B-010-3), 같은 호스트라도 경로가 다르면 robots 판정이 다르다.

    R6: SSRF 재검사는 모드와 무관하게 항상 돈다 (NG-11 은 개정 대상이 아니다).
    robots 만 모드를 따르며, 기본 `off` 에서는 조회 요청이 나가지 않는다.
    """
    try:
        verdict = policy.check_url(url)
    except policy.UnresolvableHost as exc:
        raise _Blocked("private_range", str(exc)) from exc
    if not verdict.allowed:
        raise _Blocked(verdict.rule, verdict.detail)
    robots = policy.robots_gate(url, timeout=timeout, mode=robots_mode)
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


def _same_origin_hop(origin: str, robots_mode: str = DEFAULT_ROBOTS_MODE):
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
        policy.hop_guard_for(robots_mode)(next_url)

    return _check


def _reserve(budget: list[int]) -> None:
    """요청 예산이 남았는지 **요청을 준비하기 전에** 확인한다 (AC-B-010-14)."""
    if budget[0] <= 0:
        raise _BudgetExhausted


def _request(
    url: str,
    *,
    kind: str,
    timeout: float,
    budget: list[int],
    on_attempt=None,
    robots_mode: str = DEFAULT_ROBOTS_MODE,
) -> transport.Response:
    _reserve(budget)
    budget[0] -= 1
    origin = policy.origin_of(url)
    if origin is None:
        raise Rejected(f"오리진을 판정할 수 없는 URL: {url}")

    def _on_dispatch(hop_url: str, status: int, elapsed_ms: int) -> None:
        # 실제로 추종한 중간 3xx 홉 (같은 오리진 검사로 차단되는 홉 포함). 최종 응답은
        # `_emit_attempt` 가 따로 남기므로 여기서는 중간 홉만 감사에 남는다 — 일반 fetch
        # 경로와 동일한 완전성 (SC-9).
        if on_attempt is not None:
            on_attempt(hop_url, kind, status, elapsed_ms, "redirect")

    return transport.request(
        url,
        timeout=timeout,
        impersonate=None,          # AC-B-010-4 — 임퍼소네이션 없음
        user_agent=HONEST_UA,
        accept=_accept_for(kind),
        hop_check=_same_origin_hop(origin, robots_mode),
        on_dispatch=_on_dispatch,
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
        except (ValueError, TypeError, RecursionError):
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
    robots_mode: str = DEFAULT_ROBOTS_MODE,
) -> Phase0Outcome:
    """항목 하나를 실행한다. `on_attempt(status, elapsed_ms, outcome)` 로 시도를 알린다."""
    budget = [REQUEST_BUDGET]
    outcome = Phase0Outcome()

    try:
        with transport.dispatch_budget(DISPATCH_BUDGET):
            if entry.get("chain") is not None:
                return _run_chain(entry, captures, intent=intent, timeout=timeout,
                                  budget=budget, on_attempt=on_attempt, outcome=outcome,
                                  robots_mode=robots_mode)
            return _run_endpoints(entry, captures, intent=intent, timeout=timeout,
                                  budget=budget, on_attempt=on_attempt, outcome=outcome,
                                  robots_mode=robots_mode)
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
    except Exception as exc:  # noqa: BLE001
        # 계약: run() 은 어떤 실패도 밖으로 던지지 않는다 (전 단계 격리 — Phase 0 이
        # 뒤 단계·CLI 를 오염시키면 안 된다). 위 분류에 안 걸린 예상 밖 예외
        # (비정상 깊이 JSON 의 RecursionError, 조립 URL 의 포트 범위 초과 등)도
        # outcome 에 종류를 그대로 남기고 정상 종료한다 (NG-10 — 다른 이유로 세탁 금지).
        outcome.notes.append(f"internal: {type(exc).__name__}: {exc}")
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


def _run_chain(entry, captures, *, intent, timeout, budget, on_attempt, outcome,
               robots_mode=DEFAULT_ROBOTS_MODE):
    chain = entry["chain"]
    binds = dict(captures)
    for index, step in enumerate(chain):
        url = substitute(str(step["request"]), binds)
        _reserve(budget)          # 라운드 4 — `_guard` 의 robots 요청보다 먼저 센다
        _guard(url, timeout=timeout, robots_mode=robots_mode)
        kind = str(step.get("response_kind") or entry.get("response_kind") or "html")
        response = _request(url, kind=kind, timeout=timeout, budget=budget,
                            on_attempt=on_attempt, robots_mode=robots_mode)
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
        except (ValueError, TypeError, RecursionError) as exc:
            raise Rejected(f"step{index}: JSON 이 아니다 — {exc}") from exc
        pointer = str(step["select"])
        value = _as_scalar(select_scalar(payload, pointer), pointer)
        pattern = str(step["value_pattern"])
        # fullmatch 다. `$` 하나만 믿으면 끝에 개행이 붙은 값이 그대로 통과한다.
        if re.fullmatch(pattern, value) is None:
            raise Rejected(f"step{index}: {pointer} 값이 value_pattern 과 다르다 (AC-B-010-10)")
        binds[str(step["bind"])] = value
    return outcome


def _run_endpoints(entry, captures, *, intent, timeout, budget, on_attempt, outcome,
                   robots_mode=DEFAULT_ROBOTS_MODE):
    kind = str(entry["response_kind"])
    pointer = entry.get("content_pointer")
    for endpoint in entry["endpoints"]:
        url = substitute(str(endpoint), captures)
        # 예산 확인이 `_guard` **앞**이다. `_guard` 는 robots.txt 를 받으러 나가므로,
        # 순서를 뒤집으면 이미 예산이 0 인 상태에서 네 번째 오리진의 robots 를 실제로
        # 두드린 뒤에야 예산 소진을 알린다 — "오리진 수 <= 요청 수"가 거짓이 되고,
        # 쏘지 않기로 한 엔드포인트의 정책 판정이 항목의 결과로 보고된다 (라운드 4).
        _reserve(budget)
        _guard(url, timeout=timeout, robots_mode=robots_mode)
        response = _request(url, kind=kind, timeout=timeout, budget=budget,
                            on_attempt=on_attempt, robots_mode=robots_mode)
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
