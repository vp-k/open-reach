"""`<noscript>` 안내문이 성공으로 계상되지 않는지 고정한다 (R11 리뷰 MAJOR-1).

추출기가 `<noscript>` 를 본문 후보에 넣으면서, 안내문이 200자를 넘고 문장 형태이면
분류기의 길이·문단 검사를 둘 다 통과해 `success` 가 되는 경로가 생겼다. 실제 공개
본문은 한 글자도 못 받았는데 돌파율만 오르는 경로라 회귀로 고정해 둔다.
"""

import pathlib
import sys

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import detect, extract  # noqa: E402

# 실물 형태: 앱 컨테이너 하나 + 200자를 넘는 안내문. crates.io 형이다.
_NOTICE = (
    "This application requires JavaScript to run. Please enable JavaScript in your "
    "browser settings and reload this page. Without JavaScript the package listing, "
    "search, and documentation links on this site cannot be displayed at all."
)
JS_SHELL_PAGE = (
    "<html><head><title>crate</title></head><body>"
    '<div id="app"></div>'
    f"<noscript><p>{_NOTICE}</p></noscript>"
    "</body></html>"
)

_PROSE = (
    "Progressive enhancement means the page works before the scripts arrive. "
    "We ship the article body in the initial HTML response, then let the client "
    "layer add the interactive table of contents on top of it once it is ready. "
    "Readers who enable JavaScript get the extras; everyone else still gets the text."
)
REAL_ARTICLE_MENTIONING_JS = (
    "<html><head><title>Progressive enhancement</title></head><body>"
    f"<main><h1>Progressive enhancement</h1><p>{_PROSE}</p></main>"
    "<noscript><p>Enable JavaScript for the interactive table of contents.</p></noscript>"
    "</body></html>"
)


def test_noscript_notice_is_not_a_success():
    extracted, _ = extract.extract(JS_SHELL_PAGE)
    assert len(extracted) >= detect.MIN_ARTICLE_CHARS, (
        "이 픽스처는 길이 검사를 통과해야 의미가 있다 — 통과하지 못하면 "
        "다른 이유로 우연히 걸린 것이라 회귀를 못 잡는다"
    )

    verdict = detect.classify(200, JS_SHELL_PAGE, extracted)
    assert verdict.outcome != "success"
    assert verdict.reason == "validation_failed"
    assert "js_shell" in verdict.signals


def test_an_article_that_merely_talks_about_javascript_still_succeeds():
    """본문이 따로 있는 문서는 걸리지 않아야 한다 — 아니면 정상 기사를 버린다."""
    extracted, _ = extract.extract(REAL_ARTICLE_MENTIONING_JS)
    verdict = detect.classify(200, REAL_ARTICLE_MENTIONING_JS, extracted)
    assert verdict.outcome == "success"
    assert verdict.reason is None


def test_text_outside_noscript_ignores_scripts_and_styles():
    """스크립트 본문을 글자로 세면 어떤 셸이든 '본문이 있다' 가 된다."""
    html = (
        "<html><body><script>var x = 'a very long string of javascript source';</script>"
        "<style>.a{color:red}</style>"
        "<noscript><p>Please enable JavaScript to continue.</p></noscript>"
        "<div id=root></div></body></html>"
    )
    assert detect._text_outside_noscript(html).strip() == ""


def test_js_notice_needs_both_axes():
    """안내문 문구만으로는 셸이 아니다 — 문서에 본문이 남아 있으면 통과시킨다."""
    extracted, _ = extract.extract(REAL_ARTICLE_MENTIONING_JS)
    assert detect._is_js_notice(extracted, REAL_ARTICLE_MENTIONING_JS) is False

    shell_extracted, _ = extract.extract(JS_SHELL_PAGE)
    assert detect._is_js_notice(shell_extracted, JS_SHELL_PAGE) is True
