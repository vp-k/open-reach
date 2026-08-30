"""본문 추출 — HTML 에서 잡음을 버리고 마크다운 근사치를 만든다.

취득 본문은 호출자에게 반환만 하고 어디에도 저장하지 않는다 (NG-12).
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

# "기사라 부를 만한 길이"는 추출기와 분류기가 **같은 값**을 써야 한다. 두 값이 갈라지면
# 추출기는 본문을 얻었다고 여기고 분류기는 `empty_body` 로 버리는 구간이 생긴다.
from .detect import MIN_ARTICLE_CHARS

# 텍스트를 통째로 버리는 태그 — 잡음이거나 사람이 읽는 본문이 아니다
DROP_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "nav",
        "footer",
        "header",
        "aside",
        "form",
        "svg",
        "iframe",
        "template",
        "button",
        "select",
        "figure",
    }
)

BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "main",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "tr",
        "blockquote",
        "pre",
        "td",
        "th",
    }
)

MAIN_TAGS = frozenset({"article", "main"})

VOID_TAGS = frozenset({"br", "img", "hr", "meta", "link", "input", "source"})


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str, bool]] = []  # (tag, text, in_main)
        self.title: str | None = None
        self._buffer: list[str] = []
        self._tag_stack: list[str] = []
        self._drop_depth = 0
        self._main_depth = 0
        self._in_title = False
        self._current_tag = "p"

    # ── 내부 ──
    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buffer)).strip()
        self._buffer = []
        if text:
            self.blocks.append((self._current_tag, text, self._main_depth > 0))

    # ── HTMLParser 훅 ──
    def handle_starttag(self, tag, attrs):  # noqa: D102 - stdlib signature
        tag = tag.lower()
        if tag in VOID_TAGS:
            if tag == "br":
                self._buffer.append(" ")
            return
        self._tag_stack.append(tag)
        if tag == "title":
            self._in_title = True
            return
        if tag in DROP_TAGS:
            self._flush()
            self._drop_depth += 1
            return
        if self._drop_depth:
            return
        if tag in BLOCK_TAGS:
            self._flush()
            self._current_tag = tag
        if tag in MAIN_TAGS:
            self._main_depth += 1

    def handle_endtag(self, tag):  # noqa: D102 - stdlib signature
        tag = tag.lower()
        if tag in VOID_TAGS:
            return
        if tag == "title":
            self._in_title = False
        if self._tag_stack and tag in self._tag_stack:
            while self._tag_stack:
                popped = self._tag_stack.pop()
                if popped in DROP_TAGS and self._drop_depth:
                    self._drop_depth -= 1
                if popped in MAIN_TAGS and self._main_depth:
                    self._flush()
                    self._main_depth -= 1
                if popped == tag:
                    break
        if self._drop_depth:
            return
        if tag in BLOCK_TAGS:
            self._flush()
            self._current_tag = "p"

    def handle_data(self, data):  # noqa: D102 - stdlib signature
        if self._in_title:
            self.title = ((self.title or "") + data).strip() or None
            return
        if self._drop_depth:
            return
        self._buffer.append(data)

    def close(self):  # noqa: D102 - stdlib signature
        super().close()
        self._flush()


def _as_markdown(blocks: list[tuple[str, str, bool]]) -> str:
    lines: list[str] = []
    for tag, text, _ in blocks:
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            lines.append("#" * int(tag[1]) + " " + text)
        elif tag == "li":
            lines.append("- " + text)
        else:
            lines.append(text)
    return "\n\n".join(lines).strip()


_NOSCRIPT_BLOCK = re.compile(r"<noscript[^>]*>(.*?)</noscript>", re.I | re.S)


def _collect(html: str) -> _Extractor:
    parser = _Extractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # 깨진 마크업도 지금까지 모은 블록으로 진행한다
        pass
    return parser


def _noscript_markdown(html: str) -> str:
    """`<noscript>` 안쪽을 본문 후보로 뽑는다.

    HTTP 티어는 JS 를 실행하지 않는다 — 즉 발행자가 `<noscript>` 에 넣어 둔 것이
    **우리 같은 클라이언트를 위해 준비된 바로 그 본문**이다. 이것을 잡음으로 버리는 건
    브라우저 티어의 전제를 HTTP 티어에 잘못 적용하는 것이고, 실제로 Discourse 포럼에서
    26만 자 HTML 을 받고도 추출 0자가 나오던 원인이었다(R1 실측, `docs/r1-report.md` §3).

    다만 정상 문서에서 noscript 는 대개 "JS 를 켜라" 안내나 추적 픽셀이므로 **본 문서에서
    본문을 얻지 못했을 때만** 쓴다 (`extract` 의 후보 우선순위).
    """
    inner = "\n".join(m.group(1) for m in _NOSCRIPT_BLOCK.finditer(html))
    if not inner.strip():
        return ""
    return _as_markdown(_collect(inner).blocks)


def extract(html: str) -> tuple[str, str | None]:
    """(content_markdown, title) 을 돌려준다.

    후보를 우선순위대로 늘어놓고 **기사라 부를 만한 길이를 처음 넘긴 것**을 쓴다:
    `<main>`/`<article>` 안 → 문서 전체 → `<noscript>` 안. 어느 것도 넘기지 못하면
    가장 긴 것을 그대로 돌려준다 — 판정은 분류기 몫이고, 추출기가 조용히 빈 문자열을
    내놓으면 실패 원인이 사라진다 (NG-10).

    예전에는 main 영역이 존재하기만 하면 그 안만 무조건 본문으로 삼았다. `<main>` 에
    제목 한 줄만 들어 있고 실제 본문은 밖에 있는 문서에서 17자를 본문이라 내놓았고,
    분류기는 그 빈약함을 로그인월로 오해했다.
    """
    parser = _collect(html)

    main_blocks = [b for b in parser.blocks if b[2]]
    candidates = (
        _as_markdown(main_blocks),
        _as_markdown(parser.blocks),
        _noscript_markdown(html),
    )
    markdown = next(
        (c for c in candidates if len(c) >= MIN_ARTICLE_CHARS),
        max(candidates, key=len),
    )

    title = parser.title
    if not title:
        for tag, text, _ in parser.blocks:
            if tag == "h1":
                title = text
                break
    return markdown, title


def normalized(text: str) -> str:
    """정답 대조용 정규화 — 공백 차이를 흡수한다."""
    return re.sub(r"\s+", " ", text).strip()


# ── intent 별 추출 ───────────────────────────────────────────────────────

_MEDIA_TAGS = frozenset({"img", "video", "audio", "source", "embed"})
_MEDIA_ATTRS = ("src", "poster", "data-src")


class _MediaCollector(HTMLParser):
    """미디어 리소스 URL 만 모은다 — DROP_TAGS 안쪽도 대상이다(본문 밖 이미지도 미디어다)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, str]] = []
        self._seen: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in _MEDIA_TAGS:
            return
        table = {k.lower(): (v or "") for k, v in attrs}
        for attr in _MEDIA_ATTRS:
            value = table.get(attr, "").strip()
            if value and value not in self._seen:
                self._seen.add(value)
                self.found.append((tag, value))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def extract_media(html: str, base_url: str = "") -> str:
    """미디어 목록을 마크다운 리스트로 만든다. 미디어가 없으면 빈 문자열."""
    from urllib.parse import urljoin

    collector = _MediaCollector()
    try:
        collector.feed(html)
        collector.close()
    except Exception:  # 깨진 마크업에서 파서가 죽어도 취득 전체를 실패시키지 않는다
        pass
    lines = [
        f"- {tag}: {urljoin(base_url, url) if base_url else url}"
        for tag, url in collector.found
    ]
    return "\n".join(lines)


def extract_for(intent: str, html: str, base_url: str = "") -> tuple[str, str | None]:
    """`intent` 에 맞는 (본문, 제목). 지원하지 않는 intent 는 호출 전에 걸러야 한다."""
    if intent == "raw":
        # 가공하지 않은 원본을 그대로 돌려준다 — 제목만 부가로 뽑아 준다
        return html, extract(html)[1]
    if intent == "media":
        return extract_media(html, base_url), extract(html)[1]
    return extract(html)
