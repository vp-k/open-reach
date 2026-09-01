"""SPEC Data Model 의 1:1 구현 (frozen dataclass).

JSON 직렬화가 표와 1:1 대응하며, 불변식 위반은 예외로 즉시 드러낸다.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import asdict, dataclass, field
from typing import Any

# ── 닫힌 집합 ────────────────────────────────────────────────────────────

FAILURE_REASONS = (
    "auth_wall",
    "paywall",
    "policy_blocked",
    "waf_challenge",
    "rate_limited",
    "not_found",
    "server_error",
    "network",
    "validation_failed",
    "unsupported",
    "unknown",
)

# 종료 코드 매핑 (SPEC 실패 사유 분류표)
BOUNDARY_REASONS = ("auth_wall", "paywall", "policy_blocked")

ROUTES = ("policy", "phase0", "http", "browser")
# "redirect" 는 최종 응답이 아니라 우리가 실제로 추종한 중간 3xx 홉을 attempts 에
# 정직하게 남기기 위한 값이다 (감사 완전성 — 나간 요청은 모두 기록한다). 종료 코드나
# 실패 사유에는 관여하지 않는다: 최종 판정은 마지막 홉의 outcome 이 결정한다.
OUTCOMES = ("success", "challenge", "wall", "error", "blocked", "redirect")
URL_VARIANTS = ("original", "mobile", "rss", "json", "oembed", "amp")
INTENTS = ("article", "media", "raw")

WAF_VENDORS = (
    "cloudflare",
    "akamai",
    "datadome",
    "perimeterx",
    "imperva",
    "f5",
    "fastly",
    "aws_waf",
    "kasada",
)
VENDOR_VALUES = WAF_VENDORS + ("unknown_challenge", "none")

# R1 이 실제로 방출하는 값: scheme / private_range / robots / redirect_hop.
# `rate_limit` 은 차단이 아니라 페이싱(대기)으로 강제하므로 판정으로 나오지 않고,
# `browser_disabled` 는 브라우저 티어(R3)가 생겨야 판정할 대상이 존재한다.
# 둘은 SPEC PolicyVerdict 의 닫힌 집합에 있는 **예약값**이며, 없는 판정을 지어내지 않는다 (NG-10).
POLICY_RULES = (
    "scheme",
    "private_range",
    "robots",
    "rate_limit",
    "browser_disabled",
    "redirect_hop",
)
R1_EMITTED_POLICY_RULES = ("scheme", "private_range", "robots", "redirect_hop")

OBSERVATION_KEYS = (
    "ts",
    "host",
    "path",
    "waf_vendor",
    "route",
    "impersonate",
    "url_variant",
    "outcome",
)


class ObservationSchemaError(ValueError):
    """관측 레코드가 허용 필드 화이트리스트를 벗어났다 (NG-4)."""


class InvariantError(RuntimeError):
    """FetchResult 불변식 위반 — 프로그래밍 오류다."""


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_today() -> str:
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


# ── 데이터 모델 ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FetchRequest:
    url: str
    intent: str = "article"
    timeout_s: float = 20.0
    allow_browser: bool = False
    max_attempts: int = 6
    # A0 기준선(`baseline`)의 계약은 "표준 HTTP 클라이언트(임퍼소네이션 없음)만 사용한
    # 실패율"이다. 프로필 계획에 그대로 맡기면 curl_cffi 설치 여부에 따라 chrome
    # 임퍼소네이션이 섞여 들어가 같은 표본이 다른 수치를 낸다 — 개선 전 기준선이
    # 개선 후 수치와 뒤섞이면 중단 판정(ADR-005)의 근거가 무너진다.
    no_impersonate: bool = False
    # Phase 0 공개 API 인덱스의 대체 경로. 값은 **경로**이고 로드된 항목이 아니다 —
    # FetchRequest 는 frozen dataclass 라 가변 컨테이너를 담으면 불변식이 거짓말이 된다.
    api_index: str | None = None


@dataclass(frozen=True)
class Attempt:
    route: str
    impersonate: str | None
    referer: str | None
    url_variant: str
    status: int | None
    elapsed_ms: int
    outcome: str
    # 정책 계층이 내린 PolicyVerdict.rule 을 시도 이력에 남기는 통로.
    # FetchResult 는 최상위 필드를 늘리지 않으므로(응답 포맷 고정) 차단 규칙의
    # 식별은 차단 판정이 기록되는 자리인 attempts[0] 에서 이뤄진다.
    # 기본값 None 이라 기존 호출부는 그대로 둔다 — 정책 경로만 값을 채운다.
    rule: str | None = None
    # Phase 0 이 실제로 두드린 엔드포인트. AC-B-010-7 이 "어떤 엔드포인트를 썼는지
    # 보인다"를 요구하는데 `url_variant` 는 닫힌 집합이라 URL 을 담을 수 없다.
    endpoint: str | None = None

    def __post_init__(self) -> None:
        if self.route not in ROUTES:
            raise InvariantError(f"unknown route: {self.route}")
        if self.outcome not in OUTCOMES:
            raise InvariantError(f"unknown outcome: {self.outcome}")
        if self.url_variant not in URL_VARIANTS:
            raise InvariantError(f"unknown url_variant: {self.url_variant}")
        if self.elapsed_ms < 0:
            raise InvariantError("elapsed_ms must be >= 0")
        if self.rule is not None:
            # 값의 도메인은 PolicyVerdict 와 같은 닫힌 집합이고, 정책이 아닌
            # 계층이 규칙 ID 를 달고 나오는 것은 프로그래밍 오류다.
            if self.route != "policy":
                raise InvariantError(f"rule is only for route=policy: {self.route}")
            if self.rule not in POLICY_RULES:
                raise InvariantError(f"unknown policy rule: {self.rule}")
        if self.endpoint is not None and self.route != "phase0":
            raise InvariantError(f"endpoint is only for route=phase0: {self.route}")


@dataclass(frozen=True)
class FetchResult:
    url: str
    ok: bool
    content_markdown: str | None
    metadata: dict[str, Any] | None
    failure_reason: str | None
    attempts: list[Attempt]
    final_route: str | None

    def __post_init__(self) -> None:
        if self.ok:
            if self.failure_reason is not None:
                raise InvariantError("ok=true 인데 failure_reason 이 있다")
            if self.content_markdown is None:
                raise InvariantError("ok=true 인데 content_markdown 이 없다")
        else:
            if self.failure_reason not in FAILURE_REASONS:
                raise InvariantError(f"닫힌 집합 밖의 사유: {self.failure_reason}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def exit_code(self) -> int:
        if self.ok:
            return 0
        return 2 if self.failure_reason in BOUNDARY_REASONS else 1


@dataclass(frozen=True)
class WafVerdict:
    vendor: str
    confidence: float
    signals: list[str] = field(default_factory=list)
    capabilities_needed: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PolicyVerdict:
    allowed: bool
    rule: str | None
    detail: str


@dataclass(frozen=True)
class Observation:
    ts: str
    host: str
    path: str
    waf_vendor: str
    route: str
    impersonate: str | None
    url_variant: str
    outcome: str = "success"

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        extra = set(record) - set(OBSERVATION_KEYS)
        if extra:
            raise ObservationSchemaError(f"화이트리스트 밖 키: {sorted(extra)}")
        if record["outcome"] != "success":
            raise ObservationSchemaError("경계·실패 경로는 관측에 기록하지 않는다")
        return record
