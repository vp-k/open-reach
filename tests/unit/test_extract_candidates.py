"""본문 추출 후보 우선순위 회귀 테스트 (R1 실측 격차 4건).

R1 대조에서 원본과의 격차 7건 중 4건이 **차단이 아니라 추출 실패**였다. 서버가 22만~26만
자를 정상으로 내줬는데 추출기가 0~17자를 돌려줬고, 분류기는 그 빈약함을 로그인월로
오해했다. 여기 픽스처는 그때 실제로 받은 문서의 **구조**만 최소로 재현한 것이다.
"""

import pathlib
import sys

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import detect, extract  # noqa: E402

_FILLER = "본문 문장이 이어진다. " * 30  # MIN_ARTICLE_CHARS 를 넉넉히 넘긴다

# Discourse 계열: 본문 전체가 `<noscript>` 안에 있다. JS 없는 클라이언트를 위해
# 발행자가 준비해 둔 것이므로 HTTP 티어에서는 이것이 곧 본문이다.
NOSCRIPT_ONLY = f"""<html><head><title>Django Forum</title></head><body>
<div id="d-splash"></div>
<noscript><header><a href="/">Django Forum</a></header>
<div id="main-outlet" role="main"><h3>Using Django</h3><p>{_FILLER}</p></div></noscript>
</body></html>"""

# `<main>` 은 있지만 제목 한 줄뿐이고 실제 본문은 그 밖에 있다.
THIN_MAIN = f"""<html><head><title>Engineering</title></head><body>
<main><h6>The Latest</h6></main>
<div><h3>Available Positions</h3><p>{_FILLER}</p></div>
</body></html>"""

# 정상 문서: main 안에 본문이 있고, noscript 는 안내문일 뿐이다.
NORMAL_MAIN = f"""<html><head><title>Article</title></head><body>
<noscript>Please enable JavaScript for the best experience.</noscript>
<nav>홈 소개 연락</nav>
<main><h1>제목</h1><p>{_FILLER}</p></main>
<footer>저작권</footer>
</body></html>"""

# 클라이언트 렌더 셸: 어디에도 본문이 없다. 재시도가 아니라 브라우저 티어가 답이다.
JS_SHELL = """<html><head><title>crates.io: Rust Package Registry</title></head><body>
<noscript>For full functionality of this site it is necessary to enable JavaScript.</noscript>
<div id="app"></div></body></html>"""


@pytest.mark.parametrize(
    ("name", "html", "needle"),
    [
        ("noscript_only", NOSCRIPT_ONLY, "Using Django"),
        ("thin_main", THIN_MAIN, "Available Positions"),
        ("normal_main", NORMAL_MAIN, "제목"),
    ],
)
def test_substantial_body_is_recovered(name, html, needle):
    markdown, _title = extract.extract(html)
    assert len(markdown) >= detect.MIN_ARTICLE_CHARS, f"{name}: {len(markdown)}자만 추출"
    assert needle in markdown


def test_normal_document_prefers_main_over_boilerplate():
    """main 이 본문을 담고 있으면 문서 전체로 내려가지 않는다 — 잡음이 섞이면 안 된다."""
    markdown, _ = extract.extract(NORMAL_MAIN)
    assert "저작권" not in markdown
    assert "Please enable JavaScript" not in markdown


def test_thin_main_no_longer_reads_as_login_wall():
    """추출 실패가 `auth_wall` 오분류로 번지던 2차 피해를 막는다 (NG-1 은 진짜 월에만)."""
    markdown, _ = extract.extract(THIN_MAIN)
    verdict = detect.classify(200, THIN_MAIN, markdown)
    assert verdict.reason is None, f"공개 문서를 {verdict.reason} 로 판정"


def test_js_shell_is_distinguished_from_empty_body():
    """사유 집합은 닫혀 있으므로 신호로만 가른다 — 다음 수가 다르기 때문이다."""
    markdown, _ = extract.extract(JS_SHELL)
    verdict = detect.classify(200, JS_SHELL, markdown)
    assert verdict.reason == "validation_failed"
    assert verdict.signals == ("js_shell",)
