"""돌파율을 부풀리는 가장 값싼 경로 — **차단 페이지와 껍데기를 본문으로 세기** — 를 막는다.

A1 실측에서 성공 70건 중 3건이 이 부류였다: Imperva 인터스티셜(200 + 700자),
Bloomberg 봇 검사(200 + 640자, 문장 형태), Medium 계열 네비게이션 껍데기(268자).
셋 다 상태 코드로도 길이로도 정상 문서와 구분되지 않는다.
"""

import pathlib
import sys

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import detect  # noqa: E402

_PROSE = (
    "이 문단은 기사 본문에 해당한다. 문장 길이의 덩어리가 하나라도 있으면 기사로 인정한다. "
    "실측에서 진짜 본문의 최장 산문 블록은 176자 이상이었고, 껍데기 페이지의 최장 블록은 "
    "15자였다. 그 사이 어디에 선을 긋든 이 문단은 본문 쪽에 있어야 한다."
)

CHALLENGE_PAGES = {
    "imperva": "Pardon Our Interruption\n\n"
    "As you were browsing something about your browser made us think you were a bot. "
    "There are a few reasons this might happen.",
    "bloomberg": "We've detected unusual activity from your computer network\n\n"
    "To continue, please click the box below to let us know you're not a robot. "
    "Please make sure your browser supports JavaScript and cookies.",
}

# 실제 껍데기의 형태 — 제목과 짧은 링크만 있고 문단이 없다
NAV_SHELL = "\n\n".join(
    ["Open in app", "Sign in", "Write", "Search", "## Netflix TechBlog", "202K followers"]
    + ["## Latest"] * 8
    + ["Help", "Status", "About", "Careers", "Press", "Privacy", "Terms"]
)


@pytest.mark.parametrize("vendor", sorted(CHALLENGE_PAGES))
def test_challenge_page_is_not_a_success(vendor):
    """200 으로 오는 차단 페이지. 신호가 없으면 차단이 돌파로 계상된다."""
    body = CHALLENGE_PAGES[vendor]
    verdict = detect.classify(200, f"<html><body>{body}</body></html>", body)
    assert verdict.outcome != "success"
    assert verdict.reason == "waf_challenge"
    assert verdict.signals  # 왜 차단이라 봤는지가 남아야 한다


def test_nav_shell_is_not_a_success():
    """길이는 넘겼지만 문단이 없다 = 메뉴만 받았다."""
    assert len(NAV_SHELL) >= detect.MIN_ARTICLE_CHARS  # 길이 기준만으로는 통과한다
    verdict = detect.classify(200, f"<html><body>{NAV_SHELL}</body></html>", NAV_SHELL)
    assert verdict.outcome == "error"
    assert verdict.reason == "validation_failed"
    # `empty_body` 로 적으면 "아무것도 못 받았다"로 읽혀 다음 수가 가려진다
    assert verdict.signals == ("nav_shell",)


def test_real_article_still_passes():
    """산문 요건이 정상 기사를 잡지 않는지 — 이 테스트가 없으면 위 규칙은 그냥 문턱 상향이다."""
    body = "# 제목\n\n" + _PROSE + "\n\n" + _PROSE
    verdict = detect.classify(200, f"<html><body>{body}</body></html>", body)
    assert verdict.outcome == "success"
    assert verdict.reason is None


def test_long_page_of_short_lines_is_still_a_body():
    """짧은 줄로만 이뤄진 진짜 본문 — 소스 코드 뷰·이슈 목록·블로그 인덱스.

    문단 길이만으로 껍데기를 가르면 이 부류가 통째로 실패로 뒤집힌다. 실제로
    cpython 소스(34,924자)·playwright 이슈 목록(2,475자)이 그렇게 뒤집혔다.
    """
    body = "\n\n".join(f"- 항목 {i} 짧은 줄 하나" for i in range(120))
    assert max(len(b) for b in body.split("\n\n")) < detect.MIN_PROSE_BLOCK_CHARS
    verdict = detect.classify(200, f"<html><body>{body}</body></html>", body)
    assert verdict.outcome == "success"
    assert verdict.reason is None


def test_short_list_page_reports_empty_body_not_nav_shell():
    """200자에도 못 미치면 그건 껍데기가 아니라 빈 응답이다 — 신호를 섞지 않는다."""
    body = "- 하나\n\n- 둘"
    verdict = detect.classify(200, f"<html><body>{body}</body></html>", body)
    assert verdict.signals == ("empty_body",)
