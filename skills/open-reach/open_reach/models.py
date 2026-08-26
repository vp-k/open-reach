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
OUTCOMES = ("success", "challenge", "wall", "error", "blocked")
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


@dataclass(frozen=True)
class Attempt:
    route: str
    impersonate: str | None
    referer: str | None
    url_variant: str
    status: int | None
    elapsed_ms: int
    outcome: str

    def __post_init__(self) -> None:
        if self.route not in ROUTES:
            raise InvariantError(f"unknown route: {self.route}")
        if self.outcome not in OUTCOMES:
            raise InvariantError(f"unknown outcome: {self.outcome}")
        if self.url_variant not in URL_VARIANTS:
            raise InvariantError(f"unknown url_variant: {self.url_variant}")
        if self.elapsed_ms < 0:
            raise InvariantError("elapsed_ms must be >= 0")


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
