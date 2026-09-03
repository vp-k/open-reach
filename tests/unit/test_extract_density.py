"""R6/W6 — 밀도 폴백 추출 + 수확률 판정의 **변이 사멸** 테스트.

이 라운드에서 유일하게 **기존 성공을 실패로 뒤집을 수 있는** 변경이라, 여기서는
"새로 잡는 것" 만큼 "건드리지 않기로 한 것" 을 같은 무게로 고정한다. 특히 실측으로
성공이라 정해 둔 영역 — 짧은 줄로만 이뤄진 진짜 본문(소스 코드 뷰·이슈 목록·블로그
인덱스, NAV_SHELL_MAX_CHARS 주석) — 이 그대로 남는지가 회귀 방벽이다.
"""

import pathlib
import sys

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import detect, extract  # noqa: E402

_PROSE = (
    "Clean Architecture keeps the domain independent of frameworks and delivery "
    "mechanisms. The dependency rule points inward, so an inner layer never names "
    "an outer one. This makes the core testable without a database or a web server, "
    "and it lets infrastructure choices change without rewriting business rules. "
)
_LINKS = "".join(f'<a href="/x/{i}">Section {i}</a> ' for i in range(40))


def _container_counts(parser) -> list[tuple[int, int]]:
    """컨테이너별 (텍스트 글자, 링크 글자) — `_density_markdown` 내부와 같은 집계."""
    totals: dict[int, list[int]] = {}
    for index, (_, text, _) in enumerate(parser.blocks):
        for container in parser.block_paths[index]:
            bucket = totals.setdefault(container, [0, 0])
            bucket[0] += len(text)
            bucket[1] += parser.block_links[index]
    return [(t, l) for t, l in totals.values()]


def _padding(size: int) -> str:
    """추출에 걸리지 않는 부피 — 수확률의 분모만 키운다."""
    return "<!--" + ("x" * size) + "-->"


# ── ① 밀도 폴백 ──────────────────────────────────────────────────────────


def test_density_picks_article_subtree_over_whole_document():
    """죽여야 할 변이: 시맨틱 태그가 없으면 문서 전체를 본문으로 쓰기.

    발행자가 `<main>`/`<article>` 을 안 쓰면 지금까지의 대안은 "전부" 였고, 그러면
    메뉴 링크가 본문에 섞인다. 길이 하한은 넘으니 통과는 하는데, 돌려주는 것은
    기사가 아니라 기사와 잡음의 합이다.
    """
    html = (
        "<html><body>"
        f'<div id="menu">{_LINKS}</div>'
        f'<div id="content"><p>{_PROSE * 3}</p></div>'
        "</body></html>"
    )
    markdown, _ = extract.extract(html)
    assert "Clean Architecture keeps the domain" in markdown
    assert "Section 0" not in markdown, "메뉴 링크가 본문에 섞였다"


def test_density_returns_nothing_when_whole_document_is_already_clean():
    """죽여야 할 변이: 데드밴드를 빼고 항상 서브트리로 좁히기.

    이득이 미미한데 좁히면 본문 일부를 조용히 버리는 손해가 더 크다.
    """
    html = f"<html><body><div><p>{_PROSE * 3}</p></div></body></html>"
    parser = extract._collect(html)
    assert extract._density_markdown(parser) == ""
    # 좁히지 않아도 본문은 그대로 나온다
    markdown, _ = extract.extract(html)
    assert len(markdown) >= detect.MIN_ARTICLE_CHARS


def test_main_tag_still_wins_over_density():
    """죽여야 할 변이: 밀도 폴백을 main 앞에 두기 — 발행자의 명시적 선언을 무시한다."""
    html = (
        "<html><body>"
        f'<div id="menu">{_LINKS}</div>'
        f"<main><p>{_PROSE * 2}</p></main>"
        "</body></html>"
    )
    markdown, _ = extract.extract(html)
    assert markdown.startswith("Clean Architecture keeps the domain")
    assert "Section 0" not in markdown


def test_density_does_not_trade_the_body_for_a_clean_scrap():
    """죽여야 할 변이: 분량 하한을 절대치(`MIN_ARTICLE_CHARS`)만으로 두기.

    실측 회귀(2026-09-03 www.bankofamerica.com, `bench --tier 1`): 문서 전체 3,566자
    중 **625자짜리 앱스토어 개인정보 안내**가 링크가 없어 밀도 1위였다. 밀도 게인
    데드밴드는 비율만 보므로 이것을 통과시켰고, 본문의 83%가 조용히 버려진 결과
    수확률 판정에까지 걸려 **멀쩡한 성공이 validation_failed 로 뒤집혔다**
    (rate_http_only 1.000 → 0.917).

    우리가 고르는 것은 "가장 깨끗한 조각"이 아니라 "본문이 있는 자리"다.
    """
    notice = "Before you leave our site, please review their practices. " * 6
    html = (
        "<html><body>"
        f"<div id='nav'>{_LINKS}</div>"
        f"<div id='body'><p>{_PROSE * 6}</p>"
        '<p><a href="/a">terms</a> <a href="/b">privacy</a></p></div>'
        f"<div id='scrap'><p>{notice}</p></div>"
        "</body></html>"
    )
    parser = extract._collect(html)
    counts = _container_counts(parser)
    scrap_density = max(extract._density(t, l) for t, l in counts if l == 0 and t < 500)
    body_density = max(extract._density(t, l) for t, l in counts if t > 1_000)
    # 전제 고정: 조각이 실제로 밀도 1위다. 아니면 이 테스트는 아무것도 안 지킨다.
    assert scrap_density > body_density

    markdown, _ = extract.extract(html)
    assert "Clean Architecture keeps the domain" in markdown, "본문이 버려졌다"
    assert "Before you leave" not in markdown, "본문 대신 깨끗한 조각이 채택됐다"
    assert "Section 0" not in markdown, "메뉴가 본문에 섞였다"


def test_density_subtree_below_article_length_is_not_chosen():
    """죽여야 할 변이: 분량 하한을 빼기 — 링크 하나 없는 짧은 문단이 문서를 대표한다."""
    html = (
        "<html><body>"
        f'<div id="menu">{_LINKS}</div>'
        '<div id="tiny"><p>Short and clean.</p></div>'
        "</body></html>"
    )
    parser = extract._collect(html)
    assert extract._density_markdown(parser) == ""


# ── ② 컨테이너 경로 기록 ─────────────────────────────────────────────────


def test_container_stack_is_not_corrupted_by_dropped_regions():
    """죽여야 할 변이: 태그 **이름만** 보고 컨테이너 스택을 pop 하기.

    `<nav><div>…</div></nav>` 의 안쪽 div 는 버려진 영역이라 누른 적이 없는데,
    이름만 보고 pop 하면 바깥 컨테이너가 깎여 블록 경로가 어긋난다. nav 안의 div 는
    실제 문서에서 흔하므로 이 변이는 조용히 밀도 계산을 망가뜨린다.
    """
    html = (
        "<html><body><div id='outer'>"
        f"<nav><div>{_LINKS}</div></nav>"
        f"<p>{_PROSE * 3}</p>"
        "</div></body></html>"
    )
    parser = extract._collect(html)
    assert parser.blocks, "본문 블록이 하나도 안 잡혔다"
    # nav 를 빠져나온 뒤에도 바깥 div 가 경로에 남아 있어야 한다
    assert all(path for path in parser.block_paths)
    assert len(parser.block_paths) == len(parser.blocks) == len(parser.block_links)


def test_link_chars_are_counted_only_inside_anchors():
    html = (
        "<html><body><div>"
        f"<p>{_PROSE}</p>"
        '<p><a href="/a">clickable text here</a></p>'
        "</div></body></html>"
    )
    parser = extract._collect(html)
    by_text = {text: parser.block_links[i] for i, (_, text, _) in enumerate(parser.blocks)}
    prose_key = next(k for k in by_text if k.startswith("Clean Architecture"))
    assert by_text[prose_key] == 0
    link_key = next(k for k in by_text if "clickable" in k)
    assert by_text[link_key] == len("clickable text here")


def test_link_chars_never_exceed_block_length():
    """죽여야 할 변이: 상한을 빼기 — 밀도가 음수 방향으로 튄다."""
    html = "<html><body><div><p><a href='/a'>  spaced  </a></p></div></body></html>"
    parser = extract._collect(html)
    for index, (_, text, _) in enumerate(parser.blocks):
        assert parser.block_links[index] <= len(text)


# ── ③ 수확률 판정 ────────────────────────────────────────────────────────


def test_starved_page_is_not_success():
    """죽여야 할 변이: 수확률 축을 빼기 (R6 실측: search.naver.com).

    HTML 713,695자를 받고 226자를 건졌는데 그 226자는 검색 결과가 아니라 "AI 생성
    결과는 정확하지 않을 수 있습니다" 안내문이었다. 문장 형태라 문단 검사를 통과하고
    200자를 넘겨 **성공으로 계상**됐다 — 새 돌파 없이 돌파율만 오르는 경로다.
    """
    notice = "AI가 생성한 결과는 정확하지 않거나 최신 정보가 아닐 수 있습니다. " * 6
    html = f"<html><body>{_padding(200_000)}<div><p>{notice}</p></div></body></html>"
    markdown, _ = extract.extract(html)
    assert len(markdown) >= detect.MIN_ARTICLE_CHARS  # 길이 하한은 넘긴다
    verdict = detect.classify(200, html, markdown)
    assert verdict.outcome == "error"
    assert verdict.reason == "validation_failed"


def test_explicit_search_does_not_exempt_starvation():
    """죽여야 할 변이: R5 검색 면제를 수확률 축까지 확대하기.

    면제는 nav_shell 하나뿐이다 (AC-B-014-3). 70만 자를 받고 226자를 건진 것은
    "결과 목록을 본문으로 인정" 이 아니라 결과 목록을 못 받은 것이다.
    """
    notice = "검색 이용이 일시적으로 제한되었습니다. 잠시 후 다시 시도해 주세요. " * 5
    html = f"<html><body>{_padding(200_000)}<div><p>{notice}</p></div></body></html>"
    markdown, _ = extract.extract(html)
    verdict = detect.classify(200, html, markdown, explicit_search=True)
    assert verdict.reason == "validation_failed"


def test_short_body_in_small_document_is_still_success():
    """죽여야 할 변이: 문서 크기 조건을 빼기 — 작은 문서의 짧은 글은 그냥 짧은 글이다."""
    html = f"<html><body><div><p>{_PROSE}</p></div></body></html>"
    markdown, _ = extract.extract(html)
    assert detect.classify(200, html, markdown).outcome == "success"


def test_long_short_line_body_in_big_document_is_still_success():
    """회귀 방벽: 실측으로 성공이라 정해 둔 영역(짧은 줄로만 된 진짜 본문)을 지킨다.

    blog.rust-lang.org·이슈 목록·소스 코드 뷰가 여기 해당한다. 이들은 큰 문서에서
    나오지만 추출량도 크므로 NAV_SHELL_MAX_CHARS 위에 있고, 수확률 판정은 그 위를
    보지 않는다.
    """
    lines = "".join(f"<li>Announcing release {i}</li>" for i in range(400))
    html = f"<html><body>{_padding(200_000)}<div><ul>{lines}</ul></div></body></html>"
    markdown, _ = extract.extract(html)
    assert len(markdown) >= detect.NAV_SHELL_MAX_CHARS
    assert detect.classify(200, html, markdown).outcome == "success"


def test_is_starved_boundaries():
    big = "x" * detect.MIN_YIELD_HTML_CHARS
    ratio_chars = int(detect.MIN_YIELD_RATIO * len(big))
    # 정확히 비율선 위는 통과한다 — `<` 비교를 `<=` 로 바꾸는 off-by-one 을 죽인다
    assert not detect._is_starved("y" * ratio_chars, big)
    assert detect._is_starved("y" * (ratio_chars - 1), big)
    # 문서가 하한보다 작으면 판정 자체를 하지 않는다
    small = "x" * (detect.MIN_YIELD_HTML_CHARS - 1)
    assert not detect._is_starved("y", small)
    # 추출이 1,000자를 넘으면 보지 않는다
    assert not detect._is_starved("y" * detect.NAV_SHELL_MAX_CHARS, "x" * 10_000_000)
