"""응답 진위 판별 — 상태 코드 단독으로 판정하지 않는다.

경계(로그인월·페이월)와 챌린지는 "돌파 대상"이 아니라 "즉시 중단 사유"다 (NG-1~NG-3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import WafVerdict

# 본문으로 인정하는 최소 길이 — AC-B-001-1 의 200자와 같은 기준을 쓴다
MIN_ARTICLE_CHARS = 200

_AUTH_FORM = re.compile(r"""type\s*=\s*["']?password""", re.I)
_AUTH_WORDS = re.compile(
    r"(sign\s?in|log\s?in|로그인|登录|회원가입|create an account|continue reading)", re.I
)
_PAYWALL_JSONLD = re.compile(r"isaccessibleforfree\"?\s*:\s*false", re.I)
# **읽히는 문구**만 센다. 여기에 `paywall` 같은 마크업 토큰을 넣으면 아래 구조 신호와
# 같은 substring 에 함께 걸려서 "두 신호 AND" 가 사실은 신호 1개가 된다.
_PAYWALL_WORDS = re.compile(
    r"(subscribe to (continue|read)|구독.{0,6}(하시면|해야)|members? only|유료 (기사|콘텐츠))",
    re.I,
)
# 발행자가 본문을 **잘랐다는 구조적 표시**만 센다. `…<` 같은 표기는 정상 기사 요약에도
# 흔해서 신호가 아니라 잡음이고, 잡음을 근거로 삼으면 공개 기사를 페이월로 버리게 된다.
#
# class/id 는 **벽을 가리키는 이름**일 때만 신호다. `paywall-promo`·`paywall-related-ad`
# 처럼 벽이 아니라 벽을 파는 배너 이름이 훨씬 흔한데, 이름에 `paywall` 이 들어갔다는
# 이유로 공개 기사를 exit 2 로 버리면 돌파율이 그 자리에서 깎인다. 그래서 토큰이
# 끝나거나 벽을 뜻하는 접미사가 붙은 경우만 인정한다.
_WALL_NAME = (
    r"(?:truncated|locked-content|content-locked"
    r"|paywall(?:[-_](?:overlay|wall|blocker|gate|modal|barrier"
    r"|container|wrapper|screen|prompt|message|box))?)(?![\w-])"
)
_TRUNCATION = re.compile(
    r"""(\[\s?\.\.\.\s?\]"""
    rf"""|class\s*=\s*["'][^"']*{_WALL_NAME}"""
    rf"""|id\s*=\s*["'][^"']*{_WALL_NAME}"""
    # `data-paywall="false"` 는 "페이월이 아니다"라는 **명시적 부정**이다. 속성이
    # 있다는 사실만으로 신호로 세면 발행자의 부정을 긍정으로 뒤집어 읽게 된다.
    # 따옴표를 `?` 로 두면 엔진이 따옴표를 안 쓴 쪽으로 물러나 부정 lookahead 를
    # 빠져나가므로, 따옴표가 있는 경우와 없는 경우를 갈라서 고정한다.
    r"""|data-paywall\s*=\s*["'](?!(?:false|0|no|off)\b)"""
    r"""|data-paywall\s*=\s*(?!["'])(?!(?:false|0|no|off)\b)"""
    r"""|data-paywall\s*[/>\s])""",
    re.I,
)

_CAPTCHA_SIGNALS = (
    ("captcha-widget", "captcha_widget_markup"),
    ("g-recaptcha", "recaptcha_markup"),
    ("h-captcha", "hcaptcha_markup"),
    ("data-sitekey", "captcha_sitekey"),
    ("verify you are human", "captcha_prompt"),
    ("i am not a robot", "captcha_prompt"),
)

_CHALLENGE_SIGNALS = (
    ("just a moment", "challenge_title"),
    ("checking your browser", "challenge_interstitial"),
    ("enable javascript and cookies", "challenge_js_required"),
    ("challenge-running", "challenge_container"),
    ("attention required", "challenge_title"),
    ("access denied", "challenge_denied"),
    ("your request has been blocked", "challenge_denied"),
    ("请开启 javascript", "challenge_js_required"),
)


@dataclass(frozen=True)
class ContentVerdict:
    """응답 1건에 대한 판정. `reason=None` 이면 본문으로 인정한다."""

    reason: str | None
    outcome: str
    signals: tuple[str, ...]
    terminal: bool  # 더 시도해도 소용없다 (경계·CAPTCHA)


def _title_of(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return match.group(1).strip().lower() if match else ""


def detect_wall(html: str, extracted: str = "") -> ContentVerdict | None:
    """로그인월·페이월을 판정한다. 판정되면 즉시 중단이며 상위 티어로 올리지 않는다.

    JSON-LD 의 `isAccessibleForFree:false` 는 발행자가 스스로 선언한 것이므로 본문
    유무와 무관하게 권위 있는 근거다.

    페이월은 **구독 문구 + 구조적 잘림 표시**가 함께 있을 때 판정하며 본문 길이를 보지
    않는다. 미리보기를 200자 넘게 주는 페이월이 흔한데 길이로 거르면 그런 페이지가
    전부 success 가 되고, SC-3 의 "wall/paywall 을 success 로 판정 0건"이 깨진다.
    두 신호를 함께 요구하는 것으로 거짓 양성을 막는다 — 단, 두 신호는 **서로 다른
    증거**여야 한다. 하나는 읽히는 문구(`_PAYWALL_WORDS`), 하나는 마크업 구조
    (`_TRUNCATION`) 로 갈라놓지 않으면 `class="paywall-ad"` 같은 substring 하나가
    양쪽을 동시에 켜서 AND 가 이름만 AND 로 남는다.

    반면 로그인월의 **문구 휴리스틱**("로그인"·"sign in")은 본문이 실제로 없을 때만
    쓴다 — 공개 기사 상단에 로그인 폼이 붙어 있다는 이유로 읽히는 본문을
    auth_wall(exit 2)로 버리면 돌파율이 그 자리에서 깎인다.
    """
    if _PAYWALL_JSONLD.search(html):
        return ContentVerdict("paywall", "wall", ("paywall_metadata",), True)

    if _PAYWALL_WORDS.search(html) and _TRUNCATION.search(html):
        return ContentVerdict("paywall", "wall", ("paywall_copy_truncated",), True)

    thin = len(extracted) < MIN_ARTICLE_CHARS
    if thin and _AUTH_FORM.search(html) and _AUTH_WORDS.search(html):
        return ContentVerdict("auth_wall", "wall", ("login_form",), True)
    return None


def detect_challenge(html: str, status: int) -> ContentVerdict | None:
    """WAF 챌린지·CAPTCHA 를 판정한다. CAPTCHA 는 해결하지 않고 즉시 중단한다 (NG-3)."""
    haystack = (_title_of(html) + " " + html[:20000]).lower()

    captcha_hits = tuple(sig for needle, sig in _CAPTCHA_SIGNALS if needle in haystack)
    if captcha_hits:
        return ContentVerdict("waf_challenge", "challenge", captcha_hits, True)

    hits = tuple(sig for needle, sig in _CHALLENGE_SIGNALS if needle in haystack)
    if hits:
        return ContentVerdict("waf_challenge", "challenge", hits, False)

    if status in (503, 429) and len(html) < MIN_ARTICLE_CHARS:
        return ContentVerdict("waf_challenge", "challenge", ("thin_body_on_block_status",), False)
    return None


def classify(status: int, html: str, extracted: str) -> ContentVerdict:
    """상태 코드·본문·신호를 함께 보고 최종 판정한다.

    403 이지만 본문이 실제로 있는 경우를 성공으로 인정하는 것이 이 함수의 요점이다.
    """
    wall = detect_wall(html, extracted)
    if wall is not None:
        return wall

    if status == 429:
        return ContentVerdict("rate_limited", "error", ("http_429",), False)

    challenge = detect_challenge(html, status)
    if challenge is not None:
        return challenge

    substantial = len(extracted) >= MIN_ARTICLE_CHARS
    if substantial:
        return ContentVerdict(None, "success", (), False)

    if 500 <= status < 600:
        return ContentVerdict("server_error", "error", (f"http_{status}",), False)
    if status in (401, 403):
        return ContentVerdict("waf_challenge", "blocked", (f"http_{status}",), False)
    if 400 <= status < 500:
        return ContentVerdict("not_found", "error", (f"http_{status}",), False)
    if 200 <= status < 300:
        return ContentVerdict("validation_failed", "error", ("empty_body",), False)
    return ContentVerdict("unknown", "error", (f"http_{status}",), False)


def _haystacks(headers: dict[str, str], html: str) -> dict[str, str]:
    """detector.kind 별 검사 대상. 전부 한 덩어리로 합치면 귀속이 무너진다."""
    return {
        "header": " ".join(f"{k}: {v}" for k, v in headers.items()).lower(),
        "cookie": " ".join(
            v for k, v in headers.items() if k in ("set-cookie", "cookie")
        ).lower(),
        "body": html[:20000].lower(),
    }


def waf_verdict(status: int, headers: dict[str, str], html: str, profiles: list[dict]) -> WafVerdict:
    """지문표의 detector 규칙으로 벤더를 판정한다. 근거가 없으면 추정하지 않는다.

    `kind` 를 무시하고 헤더와 본문을 한 blob 으로 합치면, 벤더 이름을 **언급만 한**
    기사가 그 벤더의 방어를 받은 것으로 기록된다. 관측이 지문표를 갱신하는 구조에서는
    그 오귀속이 다음 실행의 계획으로 되먹임된다 — kind 별로 따로 본다.
    """
    haystacks = _haystacks(headers, html)

    for profile in profiles:
        vendor = profile.get("vendor")
        if vendor in (None, "none", "unknown_challenge"):
            continue
        signals: list[str] = []
        score = 0.0
        for detector in profile.get("detectors") or []:
            pattern = str(detector.get("pattern", "")).lower()
            if not pattern:
                continue
            kind = str(detector.get("kind") or "")
            if kind == "status":
                matched = str(status) == pattern
            elif kind in haystacks:
                matched = pattern in haystacks[kind]
            else:
                # 알 수 없는 kind 는 근거로 세지 않는다 (판정 불가는 가산하지 않는다)
                continue
            if matched:
                signals.append(str(detector.get("id")))
                score += float(detector.get("weight") or 0.0)
        if signals and score >= 1.0:
            return WafVerdict(vendor, min(1.0, score), signals, ["tls"])

    if detect_challenge(html, status) is not None or status in (401, 403, 429, 503):
        return WafVerdict("unknown_challenge", 0.4, ["unclassified_block"], ["tls"])
    return WafVerdict("none", 1.0, [], [])
