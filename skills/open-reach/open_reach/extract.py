"""본문 추출 — HTML 에서 잡음을 버리고 마크다운 근사치를 만든다.

취득 본문은 호출자에게 반환만 하고 어디에도 저장하지 않는다 (NG-12).
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

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


def extract(html: str) -> tuple[str, str | None]:
    """(content_markdown, title) 을 돌려준다.

    `<article>`/`<main>` 이 있으면 그 안만 본문으로 취급하고, 없으면 문서 전체에서
    잡음 태그를 뺀 나머지를 쓴다.
    """
    parser = _Extractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # 깨진 마크업도 지금까지 모은 블록으로 진행한다
        pass

    main_blocks = [b for b in parser.blocks if b[2]]
    blocks = main_blocks if main_blocks else parser.blocks
    markdown = _as_markdown(blocks)

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
