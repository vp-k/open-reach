"""응답 진위 판별 — 상태 코드 단독으로 판정하지 않는다.

경계(로그인월·페이월)와 챌린지는 "돌파 대상"이 아니라 "즉시 중단 사유"다 (NG-1~NG-3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import WafVerdict

# 본문으로 인정하는 최소 길이 — AC-B-001-1 의 200자와 같은 기준을 쓴다
MIN_ARTICLE_CHARS = 200
# 문단 하나로 인정하는 최소 길이. 총 길이만 보면 "Sign in | Write | Search | Latest ×8 |
# 푸터 링크" 같은 **네비게이션 껍데기**가 268자로 기준을 넘어 성공이 된다(A1 실측:
# netflixtechblog). 기사에는 문장 길이의 덩어리가 최소 하나는 있다.
MIN_PROSE_BLOCK_CHARS = 80
# 다만 문단 길이만으로 가르면 **짧은 줄로만 이뤄진 진짜 본문**을 버린다 — 소스 코드 뷰
# (cpython tasks.py: 34,924자 / 최장 블록 74자), 이슈 목록(playwright: 2,475자 / 67자),
# 블로그 인덱스(blog.rust-lang.org: 16,199자 / 69자)가 전부 여기 해당한다. 그래서
# **문단이 없어도 양이 압도하면** 본문으로 인정한다. 실측 껍데기는 268자, 짧은 줄로만 된
# 진짜 본문 중 가장 작은 것은 2,475자였으므로 1,000 은 양쪽에서 2.4배 이상 떨어져 있다.
NAV_SHELL_MAX_CHARS = 1000
# 거대한 HTML 에서 **본문이 거의 안 나온** 경우의 하한. R6 실측 계기는 네이버 통합검색이다:
# HTML 713,695자를 받고 추출 226자가 나왔는데, 그 226자는 검색 결과가 아니라 "AI가 생성한
# 결과는 정확하지 않을 수 있습니다" 안내문이었다. 문장 형태라 문단 검사(_is_nav_shell)를
# 통과하고, 200자를 넘겨 성공으로 계상됐다 — 새 돌파 없이 돌파율만 오르는 경로다.
#
# 문장부호 밀도나 링크 비율로는 이것을 못 가른다(안내문은 산문이고 링크도 없다). 실제로
# 가르는 축은 **수확률**이다. 실측 분리도: 네이버 0.03% vs geeksforgeeks 3.3% ·
# blog.rust-lang.org 17% · blog.cleancoder.com 25% — 100배 떨어져 있다.
#
# 두 조건이 함께여야 발동한다. ① 추출이 짧다(NAV_SHELL_MAX_CHARS 미만) — 이미 "짧은 줄로만
# 된 진짜 본문"을 살리려고 1,000자를 하한으로 뒀으므로 그 위는 건드리지 않는다.
# ② 문서가 크다 — 작은 문서에서 짧은 본문은 그냥 짧은 글이다.
MIN_YIELD_RATIO = 0.005
MIN_YIELD_HTML_CHARS = 50_000

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
_EXPLICIT_TRUNCATION = re.compile(r"\[\s?\.\.\.\s?\]")
# `data-paywall="false"` 는 "페이월이 아니다"라는 **명시적 부정**이다. 속성이 있다는
# 사실만으로 신호로 세면 발행자의 부정을 긍정으로 뒤집어 읽게 된다. 따옴표를 `?` 로
# 두면 엔진이 따옴표를 안 쓴 쪽으로 물러나 부정 lookahead 를 빠져나가므로, 따옴표가
# 있는 경우와 없는 경우를 갈라서 고정한다.
_DATA_PAYWALL = re.compile(
    r"""(data-paywall\s*=\s*["'](?!(?:false|0|no|off)\b)"""
    r"""|data-paywall\s*=\s*(?!["'])(?!(?:false|0|no|off)\b)"""
    r"""|data-paywall\s*[/>\s])""",
    re.I,
)

_CLASS_OR_ID = re.compile(r"""(?:class|id)\s*=\s*["']([^"']*)["']""", re.I)
# 세그먼트 경계는 `-`·`_` 만이 아니다. `paywallPromo` 처럼 camelCase 로 붙여 쓰는
# 이름이 흔한데, 구분자만 보고 자르면 통째로 한 조각이 되어 아래 배제 목록을
# 그냥 지나친다 — 대소문자 경계도 같은 경계로 취급한다.
# 대소문자 경계는 두 규칙이 **모두** 있어야 한다. 소문자→대문자(`paywallPromo`)만
# 잡으면 약어 뒤에 단어가 붙는 표기(`paywallADBanner`·`paywallHTMLPromo`)에서
# 연속 대문자가 통째로 한 조각(`ADBanner`)이 되어 다시 배제 목록을 지나친다.
# 두 번째 규칙은 대문자 뒤에 `대문자+소문자` 가 오는 지점, 즉 약어가 끝나고 새
# 단어가 시작하는 지점을 자른다 — `paywallCTA` 처럼 약어로 끝나는 이름은 뒤에
# 소문자가 없으므로 영향을 받지 않는다.
_SEGMENTS = re.compile(r"[-_]+|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
# 이름이 **벽이 아니라 벽을 파는 배너**임을 드러내는 조각들. 여기 없는 이름은 벽으로
# 본다 — 방향을 이렇게 잡는 이유는 두 오류의 값이 다르기 때문이다. 거짓 음성(진짜
# 페이월을 success 로 계상)은 SC-3 의 "0건"을 깨는 hard fail 이고, 거짓 양성은 돌파율
# 이라는 **비율** 목표를 깎는다. 확실한 제약이 비율 목표를 이긴다.
#
# 화이트리스트(벽 이름을 열거)로 가면 `paywall-content`·`paywall-body` 처럼 열거에서
# 빠진 실제 벽이 조용히 success 가 된다 — 열거는 언제나 불완전한데, 불완전의 대가를
# hard fail 쪽에 지우는 배치다. 그래서 열거의 대상을 뒤집었다.
_SELLING_SEGMENTS = frozenset({
    "promo", "promotion", "banner", "cta", "ad", "ads", "advert", "advertisement",
    "upsell", "related", "recommend", "recommended", "newsletter", "signup",
    "teaser", "badge", "icon", "link", "links",
})


def _names_a_wall(token: str) -> bool:
    """class/id 토큰 하나가 **벽 자체**를 가리키는 이름인가.

    세그먼트를 자르기 **전에** 소문자로 바꾸면 camelCase 경계가 지워져 `paywallPromo`
    가 한 조각으로 남는다 — 자른 뒤에 각 조각을 소문자로 바꾼다.
    """
    lowered = token.lower()
    stems = (
        "paywall" in lowered
        or "truncated" in lowered
        or ("locked" in lowered and "content" in lowered)
    )
    if not stems:
        return False
    segments = [seg.lower() for seg in _SEGMENTS.split(token) if seg]
    return not any(seg in _SELLING_SEGMENTS for seg in segments)


def has_truncation_markup(html: str) -> bool:
    """본문이 잘렸다는 **마크업 증거**가 있는가 (읽히는 문구와는 독립인 신호)."""
    if _EXPLICIT_TRUNCATION.search(html) or _DATA_PAYWALL.search(html):
        return True
    for value in _CLASS_OR_ID.findall(html):
        if any(_names_a_wall(token) for token in value.split()):
            return True
    return False

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
    # Imperva 차단 페이지는 200 + 700자짜리 안내문으로 온다. 상태 코드도 길이도
    # 정상 문서와 구분되지 않아, 신호가 없으면 **차단을 돌파로 계상**한다
    # (R1 벤더 실측에서 imperva "성공" 2건이 전부 이 페이지였다).
    ("pardon our interruption", "challenge_interstitial"),
    ("made us think you were a bot", "challenge_interstitial"),
    # 같은 부류의 다른 문면. 이쪽은 200 + 640자에 **문장 형태**로 와서 아래 산문 요건도
    # 통과한다 — 길이나 형태로는 못 거르고 문면으로만 걸린다 (A1 실측: bloomberg).
    ("detected unusual activity from your computer network", "challenge_interstitial"),
    ("know you're not a robot", "challenge_captcha"),
    ("know you are not a robot", "challenge_captcha"),
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
    (`has_truncation_markup`) 로 갈라놓지 않으면 `class="paywall-ad"` 같은 substring
    하나가 양쪽을 동시에 켜서 AND 가 이름만 AND 로 남는다.

    반면 로그인월의 **문구 휴리스틱**("로그인"·"sign in")은 본문이 실제로 없을 때만
    쓴다 — 공개 기사 상단에 로그인 폼이 붙어 있다는 이유로 읽히는 본문을
    auth_wall(exit 2)로 버리면 돌파율이 그 자리에서 깎인다.
    """
    if _PAYWALL_JSONLD.search(html):
        return ContentVerdict("paywall", "wall", ("paywall_metadata",), True)

    if _PAYWALL_WORDS.search(html) and has_truncation_markup(html):
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


_JS_REQUIRED = re.compile(
    r"enable\s+javascript|requires?\s+javascript|javascript\s+(?:is\s+)?(?:required|disabled)",
    re.I,
)


def _is_js_shell(html: str) -> bool:
    """본문이 없는 이유가 '차단' 이 아니라 '클라이언트 렌더' 임을 구분한다.

    같은 `validation_failed` 라도 원인이 다르면 다음 수가 다르다 — 빈 응답은 재시도가
    답이고, JS 셸은 브라우저 티어가 답이다. 실패 사유 집합은 닫혀 있으므로(SPEC 분류표)
    새 사유를 만들지 않고 **신호**로만 갈라 둔다.
    """
    return bool(_JS_REQUIRED.search(html))


_NOSCRIPT_BLOCK = re.compile(r"<noscript\b.*?</noscript\s*>", re.I | re.S)
_INERT_BLOCK = re.compile(r"<(script|style|template)\b.*?</\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")


def _text_outside_noscript(html: str) -> str:
    """`<noscript>` 를 걷어낸 문서에 남는 글자. 태그 제거만 하는 거친 계측이다."""
    stripped = _NOSCRIPT_BLOCK.sub(" ", html)
    stripped = _INERT_BLOCK.sub(" ", stripped)
    return " ".join(_TAG.sub(" ", stripped).split())


def _is_js_notice(extracted: str, html: str) -> bool:
    """추출한 것이 본문이 아니라 **'JavaScript 를 켜라' 안내문 자체**인가.

    `<noscript>` 를 본문 후보에 넣으면서 생긴 구멍이다. 안내문이 200자를 넘고 문장
    형태이면 `_is_nav_shell` 도 통과해 **차단·셸을 성공으로 계상**한다 — 새 돌파 없이
    돌파율만 오르는 경로라 막는다 (R11 리뷰 MAJOR-1).

    `html` 전체에 정규식을 걸지 않는 이유: "JavaScript 를 켜라" 는 문구는 그것을
    설명하는 **진짜 기사**에도 나온다. 그래서 두 축이 겹칠 때만 셸로 본다 —
    ① 우리가 손에 쥔 본문이 그 안내문이고, ② `<noscript>` 를 걷어내면 문서에 기사라
    부를 만한 글자가 남지 않는다. ②가 있어서 본문이 따로 있는 문서는 걸리지 않는다.
    """
    if not _JS_REQUIRED.search(extracted):
        return False
    return len(_text_outside_noscript(html)) < MIN_ARTICLE_CHARS


def _is_nav_shell(extracted: str) -> bool:
    """받은 것이 본문이 아니라 **메뉴·목차 껍데기**인가.

    껍데기의 표지는 두 가지가 겹치는 것이다 — 문장 길이의 덩어리가 하나도 없고, 총량도
    적다. 둘 중 하나만 보면 각각 오판한다: 문단 길이만 보면 짧은 줄로만 이뤄진 진짜
    본문(소스 코드·이슈 목록)을 버리고, 총량만 보면 268자짜리 네비게이션이 통과한다.

    제목 줄(`#`)은 문단으로 세지 않는다 — 껍데기가 가장 많이 내놓는 것이 제목이고,
    "## Latest" 를 여덟 번 받은 것을 기사라 부르면 돌파율이 그만큼 부풀려진다.
    """
    if len(extracted) >= NAV_SHELL_MAX_CHARS:
        return False
    for block in extracted.split("\n\n"):
        block = block.strip()
        if block.startswith("#"):
            continue
        if len(block.lstrip("- ")) >= MIN_PROSE_BLOCK_CHARS:
            return False
    return True


def _is_starved(extracted: str, html: str) -> bool:
    """거대한 문서에서 부스러기만 건졌는가 — 그것을 본문이라 부르지 않는다 (R6/W6).

    상수 옆에 실측 근거를 적어 뒀다. 여기서 중요한 것은 이 판정이 **길이 하한을 겨우
    넘긴 짧은 추출**에만 붙는다는 점이다. 1,000자를 넘긴 것은 이미 "짧은 줄로만 이뤄진
    진짜 본문"(소스 코드 뷰·이슈 목록·블로그 인덱스)으로 인정하기로 실측해 정한 영역이라
    건드리지 않는다.
    """
    if len(extracted) >= NAV_SHELL_MAX_CHARS:
        return False
    if len(html) < MIN_YIELD_HTML_CHARS:
        return False
    return len(extracted) < MIN_YIELD_RATIO * len(html)


def classify(
    status: int, html: str, extracted: str, *, explicit_search: bool = False
) -> ContentVerdict:
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

    # 401 은 인증 필요 = 인증벽이다. 본문이 길어도 그것은 우리가 돌파한 공개 콘텐츠가
    # 아니라 로그인 뒤의 자원이므로, 성공(substantial) 판정보다 **먼저** auth_wall 로
    # 종료한다. 여기 순서를 넘기면 401+긴 본문이 success 로 새어 돌파율을 부풀리고
    # NG-1(로그인월 미돌파·감지만)을 깬다. 403 은 소프트 WAF 차단이라도 공개 본문을
    # 그대로 주는 경우가 있어 아래 success 예외(이 함수의 요점)를 유지한다.
    if status == 401:
        return ContentVerdict("auth_wall", "wall", ("http_401",), True)

    # R5(AC-B-014-1): 선언된 검색 URL 은 결과 목록(짧은 블록의 나열)이 곧 본문이므로
    # nav_shell 판정만 면제한다. 완화는 정확히 그 하나다 — 위의 wall·challenge 판별과
    # 길이 하한(MIN_ARTICLE_CHARS)은 검색 URL 이라도 그대로 적용된다 (AC-B-014-3).
    substantial = len(extracted) >= MIN_ARTICLE_CHARS and (
        explicit_search or not _is_nav_shell(extracted)
    )
    # 수확률 판정은 R5 검색 면제 **밖**에 둔다 (AC-B-014-3 의 "면제는 nav_shell 하나"를
    # 그대로 지킨다). 선언된 검색 URL 이라도 70만 자를 받고 226자를 건졌다면 그것은
    # "결과 목록을 본문으로 인정" 이 아니라 결과 목록을 못 받은 것이다.
    if (
        substantial
        and not _is_js_notice(extracted, html)
        and not _is_starved(extracted, html)
    ):
        return ContentVerdict(None, "success", (), False)

    if 500 <= status < 600:
        return ContentVerdict("server_error", "error", (f"http_{status}",), False)
    if status == 403:
        return ContentVerdict("waf_challenge", "blocked", (f"http_{status}",), False)
    if 400 <= status < 500:
        return ContentVerdict("not_found", "error", (f"http_{status}",), False)
    if 200 <= status < 300:
        if _is_js_shell(html):
            signal = "js_shell"
        elif len(extracted) >= MIN_ARTICLE_CHARS:
            # 길이는 넘겼는데 문단이 없다 = 메뉴·목록만 받았다. `empty_body` 로 적으면
            # "아무것도 못 받았다"로 읽혀서 다음 수(브라우저 티어)가 가려진다.
            signal = "nav_shell"
        else:
            signal = "empty_body"
        return ContentVerdict("validation_failed", "error", (signal,), False)
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
