"""자기선언 열린문 티어 — 페이지가 **스스로 밝힌** 다른 표현을 따라간다 (R6/W3).

HTTP 티어가 바이트는 받았는데 본문이 못 쓸 때(SPA 셸·네비게이션 껍데기), 많은 사이트는
같은 문서의 다른 표현을 HTML 안에 **명시적으로 적어 둔다** — JSON-LD ``articleBody``,
RSS/Atom 대체 링크, ``amphtml``, oEmbed, 다른 오리진의 ``canonical``. 그것을 읽는 것은
추측이 아니라 상대가 붙여 둔 안내를 따르는 일이다.

**선언된 것만 따라간다.** R2 에서 `m.` · `amp.` 접두를 맹목적으로 붙여 보는 변형을
12건 중 0건 성공으로 폐기했다(NG-10 — 없는 문을 지어내는 짓이다). 그 경로는 부활시키지
않는다. 여기서 요청이 나가는 URL 은 전부 HTML 안에 문자로 적혀 있던 것이다.

지켜지는 경계:

* **NG-11** — 후보 URL 은 예외 없이 `policy.check_url` 을 새로 통과해야 한다. 원본이
  공개였다는 사실은 그 원본이 가리키는 주소의 안전을 보증하지 않는다.
* **NG-5** — 예산 ``BUDGET`` 건. 취득한 본문에서 링크를 다시 뽑지 않는다(재귀 없음).
* **NG-10** — 가져온 대체 표현도 `detect.classify` 를 그대로 통과해야 성공이다.
  피드를 받았는데 **요청한 문서가 그 안에 없으면** 성공이 아니다 — 같은 호스트의 다른
  글을 돌려주고 성공이라 부르는 것이 이 티어의 가장 그럴듯한 거짓말이다.
* **NG-12** — 본문은 반환만 하고 저장하지 않는다.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from . import detect, extract, policy, transport
from .models import BOUNDARY_REASONS

# 요청 예산. 셸 하나를 구제하려고 회선을 많이 쓰는 티어가 아니다.
BUDGET = 2

# 따라갈 선언의 종류와 우선순위. 앞의 것일수록 싸거나 본문일 확률이 높다.
KIND_JSONLD = "jsonld"
KIND_FEED = "feed"
KIND_AMP = "amphtml"
KIND_OEMBED = "oembed"
KIND_CANONICAL = "canonical"

_FEED_TYPES = frozenset({"application/rss+xml", "application/atom+xml", "text/xml"})
_OEMBED_TYPES = frozenset({"application/json+oembed", "text/json+oembed"})

# 이 티어가 손대는 실패 신호 — 셋 다 "바이트는 받았는데 쓸 본문이 없다"다.
# `empty_body` 를 빼면 안 된다: 그것은 **추출한 글자가 적다**는 뜻이지 HTML 이
# 없다는 뜻이 아니며, 선언(`<link rel=alternate>`·JSON-LD)만 잔뜩 실린 JS 렌더
# 페이지가 정확히 그 형태로 떨어진다. 바이트를 아예 못 받은 경우는 호출부의
# `last_html` 유무 검사가 따로 막는다.
ENTRY_SIGNALS = frozenset({"nav_shell", "js_shell", "empty_body"})


@dataclass(frozen=True)
class Alternate:
    """페이지가 선언한 대체 표현 하나."""

    kind: str
    url: str | None = None
    #: JSON-LD 처럼 요청 없이 본문을 이미 손에 쥔 경우
    inline: str | None = None
    title: str | None = None


@dataclass
class AlternateOutcome:
    ok: bool
    markdown: str | None = None
    title: str | None = None
    final_url: str | None = None
    content_type: str = ""
    reason: str | None = None
    policy_rule: str | None = None
    notes: list[str] = field(default_factory=list)


# ── 선언 수집 ────────────────────────────────────────────────────────────


class _DeclarationCollector(HTMLParser):
    """`<link>` 선언과 JSON-LD 블록만 모은다. 본문 추출은 `extract` 의 일이다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self.jsonld: list[str] = []
        self._in_ld = False
        self._ld_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        got = {k.lower(): (v or "") for k, v in attrs}
        if tag == "link":
            self.links.append(got)
        elif tag == "script" and got.get("type", "").strip().lower() == "application/ld+json":
            self._in_ld = True
            self._ld_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_ld:
            self._in_ld = False
            self.jsonld.append("".join(self._ld_buffer))
            self._ld_buffer = []

    def handle_data(self, data: str) -> None:
        if self._in_ld:
            self._ld_buffer.append(data)


def _walk_jsonld(node: object) -> list[dict]:
    """`@graph` · 배열 중첩을 펴서 객체만 돌려준다."""
    out: list[dict] = []
    if isinstance(node, list):
        for item in node:
            out.extend(_walk_jsonld(item))
    elif isinstance(node, dict):
        out.append(node)
        graph = node.get("@graph")
        if graph is not None:
            out.extend(_walk_jsonld(graph))
    return out


def _jsonld_body(blocks: list[str]) -> tuple[str, str | None] | None:
    """JSON-LD 에 실린 ``articleBody`` 를 꺼낸다 — 요청 0건으로 얻는 본문이다."""
    for raw in blocks:
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            # 깨진 JSON-LD 는 흔하다. 한 블록이 깨졌다고 나머지를 버리지 않는다.
            continue
        for obj in _walk_jsonld(parsed):
            body = obj.get("articleBody")
            if isinstance(body, str) and body.strip():
                headline = obj.get("headline")
                title = headline.strip() if isinstance(headline, str) and headline.strip() else None
                return extract.normalized(body), title
    return None


def _same_document(a: str, b: str) -> bool:
    """프래그먼트·후행 슬래시·호스트 대소문자 차이는 같은 문서로 본다."""
    pa, pb = urlsplit(a), urlsplit(b)
    return (
        pa.scheme == pb.scheme
        and pa.netloc.lower() == pb.netloc.lower()
        and pa.path.rstrip("/") == pb.path.rstrip("/")
        and pa.query == pb.query
    )


def discover(html: str, base_url: str) -> list[Alternate]:
    """HTML 이 스스로 선언한 대체 표현을 우선순위대로 돌려준다.

    선언이 없으면 빈 목록이다 — 이 티어가 요청을 0건 내는 것이 정상 동작이며,
    그 사실이 "맹목 변형이 부활하지 않았다"의 증거다.
    """
    collector = _DeclarationCollector()
    try:
        collector.feed(html)
        collector.close()
    except Exception:  # noqa: BLE001 — 깨진 HTML 로 티어 전체를 죽이지 않는다
        pass

    found: list[Alternate] = []

    body = _jsonld_body(collector.jsonld)
    if body is not None:
        found.append(Alternate(KIND_JSONLD, inline=body[0], title=body[1]))

    feeds: list[Alternate] = []
    amps: list[Alternate] = []
    oembeds: list[Alternate] = []
    canonicals: list[Alternate] = []

    for link in collector.links:
        rels = {r.strip().lower() for r in link.get("rel", "").split() if r.strip()}
        href = link.get("href", "").strip()
        if not href or not rels:
            continue
        mime = link.get("type", "").strip().lower().split(";")[0]
        target = urljoin(base_url, href)
        if urlsplit(target).scheme not in ("http", "https"):
            # data:·javascript: 는 문이 아니다
            continue

        if "alternate" in rels and mime in _FEED_TYPES:
            feeds.append(Alternate(KIND_FEED, url=target))
        elif "amphtml" in rels:
            amps.append(Alternate(KIND_AMP, url=target))
        elif "alternate" in rels and mime in _OEMBED_TYPES:
            oembeds.append(Alternate(KIND_OEMBED, url=target))
        elif "canonical" in rels and not _same_document(target, base_url):
            # 같은 문서를 가리키는 canonical 은 방금 실패한 그 페이지다 — 다시 두드리지 않는다.
            canonicals.append(Alternate(KIND_CANONICAL, url=target))

    found.extend(feeds)
    found.extend(amps)
    found.extend(oembeds)
    found.extend(canonicals)

    # 같은 URL 을 두 번 두드리지 않는다 (rel 이 겹쳐 선언되는 페이지가 흔하다)
    seen: set[str] = set()
    unique: list[Alternate] = []
    for alt in found:
        key = alt.url or f"inline:{alt.kind}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(alt)
    return unique


# ── 피드 해석 ────────────────────────────────────────────────────────────

_ITEM_RE = re.compile(r"<(item|entry)\b.*?</\1>", re.I | re.S)
_LINK_HREF_RE = re.compile(r"<link\b[^>]*\bhref\s*=\s*[\"']([^\"']+)[\"']", re.I)
_LINK_TEXT_RE = re.compile(r"<link\b[^>]*>(.*?)</link>", re.I | re.S)
_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.I | re.S)
_CONTENT_RE = re.compile(
    r"<(content:encoded|content|description|summary)\b[^>]*>(.*?)</\1>", re.I | re.S
)
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.S)


def _unwrap(raw: str) -> str:
    parts = _CDATA_RE.findall(raw)
    return "".join(parts) if parts else raw


def _item_link(item: str) -> str | None:
    match = _LINK_HREF_RE.search(item)  # Atom
    if match:
        return match.group(1).strip()
    match = _LINK_TEXT_RE.search(item)  # RSS 2.0
    if match:
        return _unwrap(match.group(1)).strip()
    return None


def feed_entry_for(feed_xml: str, wanted_url: str) -> tuple[str, str | None] | None:
    """피드에서 **요청한 문서에 해당하는 항목**의 본문을 꺼낸다.

    항목이 하나뿐이면 그것이 이 문서의 피드다(예: 게시물 자신의 ``.rss``). 여럿이면
    링크가 일치하는 항목만 쓴다. 일치가 없으면 ``None`` — 같은 호스트의 **다른 글**을
    받아 놓고 성공이라 부르는 것이 이 경로의 가장 그럴듯한 거짓말이라 막는다 (NG-10).
    """
    items = [m.group(0) for m in _ITEM_RE.finditer(feed_xml)]
    if not items:
        return None

    chosen: str | None = None
    if len(items) == 1:
        chosen = items[0]
    else:
        for item in items:
            link = _item_link(item)
            if link and _same_document(link, wanted_url):
                chosen = item
                break
    if chosen is None:
        return None

    best = ""
    for match in _CONTENT_RE.finditer(chosen):
        candidate = _unwrap(match.group(2))
        if len(candidate) > len(best):
            best = candidate
    if not best.strip():
        return None

    markdown, _ = extract.extract(best)
    if not markdown.strip():
        markdown = extract.normalized(best)

    title_match = _TITLE_RE.search(chosen)
    title = extract.normalized(_unwrap(title_match.group(1))) if title_match else None
    return markdown, (title or None)


def _oembed_html(payload: str) -> str | None:
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    html = data.get("html")
    return html if isinstance(html, str) and html.strip() else None


# ── 티어 실행 ────────────────────────────────────────────────────────────


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def worthy(reason: str | None, signals: tuple[str, ...]) -> bool:
    """이 티어가 오를 자리인가.

    바이트는 받았는데 본문이 못 쓸 때만이다. 403·네트워크 실패에는 따라갈 선언이
    실린 HTML 이 없고, 경계(auth_wall·paywall)는 선언을 따라간다고 뒤집히지
    않는다 — 그 시도가 곧 NG-1/NG-2 위반이다.
    """
    return reason == "validation_failed" and bool(ENTRY_SIGNALS & set(signals))


def _wall_of(payload: str) -> detect.ContentVerdict | None:
    """파싱에 실패한 응답이 **경계**인지 본다.

    `detect_wall` 의 로그인월 휴리스틱에는 "읽을 본문이 실제로 없을 때만 쓴다"는
    안전장치가 붙어 있고(공개 기사 상단에 로그인 폼이 있다는 이유로 읽히는 본문을
    버리지 않기 위해서다), 그 조건은 `extracted` 인자로 전달된다. 여기서 `""` 를
    넘기면 그 장치가 통째로 꺼져, 로그인 문구와 `<input type=password>` 가
    **내용으로** 실린 정상 피드가 auth_wall 로 오판된다 — 요청한 문서가 없을 뿐인
    피드가 exit 2 경계 보고로 둔갑하고 남은 선언까지 중단된다.

    그래서 payload 에서 실제로 읽히는 글자를 한 번 뽑아 함께 넘긴다. 벽이면 뽑을
    것이 없고, 읽을 것이 있으면 벽이 아니다.
    """
    text, _ = extract.extract(payload)
    return detect.detect_wall(payload, text)


def try_alternates(
    request,
    html: str,
    base_url: str,
    *,
    on_attempt=None,
) -> AlternateOutcome | None:
    """선언된 대체 표현을 예산 안에서 따라간다. 선언이 없으면 ``None``."""
    candidates = discover(html, base_url)
    if not candidates:
        return None

    notes: list[str] = []
    spent = 0

    for alt in candidates:
        if alt.inline is not None:
            verdict = detect.classify(200, "", alt.inline)
            # 요청이 0건이라도 **어떤 선언을 따랐는지는 남는다** (AC-B-015-6).
            # 이력이 비면 final_route="alternate" 만 보이고 근거가 사라져,
            # 관측만 보고는 취득 경로를 재구성할 수 없다 (NG-10).
            if on_attempt is not None:
                on_attempt(base_url, alt.kind, None, verdict.outcome, 0)
            if verdict.reason is None:
                return AlternateOutcome(
                    True,
                    markdown=alt.inline,
                    title=alt.title,
                    final_url=base_url,
                    content_type="application/ld+json",
                    notes=notes,
                )
            notes.append("jsonld: articleBody 가 본문 판정을 통과하지 못했다")
            continue

        if spent >= BUDGET:
            notes.append(f"예산 {BUDGET}건 소진 — 남은 선언은 두드리지 않는다")
            break

        assert alt.url is not None
        # NG-11 — 선언되어 있다는 사실은 안전을 보증하지 않는다. 새로 검사한다.
        try:
            verdict = policy.check_url(alt.url)
        except policy.UnresolvableHost as exc:
            notes.append(f"{alt.kind}: 주소를 확인할 수 없다 — {exc}")
            continue
        if not verdict.allowed:
            return AlternateOutcome(
                False, reason="policy_blocked", policy_rule=verdict.rule, notes=notes
            )

        spent += 1
        started = time.monotonic()
        try:
            response = transport.request(
                alt.url,
                timeout=request.timeout_s,
                hop_check=policy.hop_guard_for(request.robots_mode),
            )
        except transport.PolicyBlocked as exc:
            # 요청은 실제로 나갔고 리디렉트 홉에서 막혔다. 이력에 남기지 않으면
            # 관측만 보고는 **어느 선언을 두드리다** 막혔는지 재구성할 수 없다 —
            # 결과에는 endpoint 없는 정책 차단만 남는다 (NG-10).
            if on_attempt is not None:
                on_attempt(alt.url, alt.kind, None, "blocked", _ms(started))
            return AlternateOutcome(
                False, reason="policy_blocked", policy_rule=exc.rule, notes=notes
            )
        except transport.NetworkError as exc:
            notes.append(f"{alt.kind}: 네트워크 실패 — {exc}")
            if on_attempt is not None:
                on_attempt(alt.url, alt.kind, None, "error", _ms(started))
            continue

        payload = response.text()
        if alt.kind == KIND_FEED:
            entry = feed_entry_for(payload, base_url)
            if entry is None:
                # 피드 자리에 피드가 아닌 것이 왔을 수 있다. 그것이 로그인월이면
                # "요청한 문서가 피드에 없다(mismatch)"가 아니라 **경계**다. mismatch 로
                # 적고 넘어가면 남은 선언으로 같은 벽을 다른 문으로 두드리게 되고,
                # 그 시도 자체가 NG-1/NG-2 위반이다. 파싱 실패는 판정을 면제하지 않는다.
                wall = _wall_of(payload)
                if wall is not None:
                    notes.append(f"feed: {wall.reason} — 경계는 선언을 따라가도 뒤집히지 않는다")
                    if on_attempt is not None:
                        on_attempt(
                            alt.url, alt.kind, response.status, wall.outcome, response.elapsed_ms
                        )
                    return AlternateOutcome(False, reason=wall.reason, notes=notes)
                notes.append("feed: 요청한 문서가 피드에 없다 — 다른 글을 성공이라 부르지 않는다")
                if on_attempt is not None:
                    on_attempt(alt.url, alt.kind, response.status, "mismatch", response.elapsed_ms)
                continue
            markdown, title = entry
        elif alt.kind == KIND_OEMBED:
            embed = _oembed_html(payload)
            if embed is None:
                # 피드와 같은 이유 — oembed 자리에 온 로그인월을 파싱 실패로 적지 않는다.
                wall = _wall_of(payload)
                if wall is not None:
                    notes.append(f"oembed: {wall.reason} — 경계는 선언을 따라가도 뒤집히지 않는다")
                    if on_attempt is not None:
                        on_attempt(
                            alt.url, alt.kind, response.status, wall.outcome, response.elapsed_ms
                        )
                    return AlternateOutcome(False, reason=wall.reason, notes=notes)
                notes.append("oembed: html 필드가 없다")
                if on_attempt is not None:
                    on_attempt(alt.url, alt.kind, response.status, "error", response.elapsed_ms)
                continue
            markdown, title = extract.extract(embed)
        else:
            markdown, title = extract.extract_for(
                request.intent, payload, response.final_url or alt.url
            )

        # 대체 표현이라고 판정을 느슨하게 하지 않는다. 명시적 검색 면제도 주지 않는다 —
        # 이 URL 은 사용자가 적은 것이 아니라 페이지가 적어 준 것이다 (AC-B-014 정신).
        content_verdict = detect.classify(response.status, payload, markdown)
        if on_attempt is not None:
            on_attempt(
                alt.url, alt.kind, response.status, content_verdict.outcome, response.elapsed_ms
            )
        if content_verdict.reason is None:
            return AlternateOutcome(
                True,
                markdown=markdown,
                title=title,
                final_url=response.final_url or alt.url,
                content_type=response.headers.get("content-type", ""),
                notes=notes,
            )
        if content_verdict.terminal or content_verdict.reason in BOUNDARY_REASONS:
            # 경계·CAPTCHA 는 표현을 바꾼다고 열리지 않는다. 남은 선언을 두드리는 것도,
            # 이 사유를 버리고 상위 티어로 흘려보내는 것도 같은 벽을 다시 미는 짓이다
            # (NG-1/NG-2/NG-3). 사유를 그대로 들고 즉시 멈춘다.
            notes.append(f"{alt.kind}: {content_verdict.reason} — 남은 선언은 두드리지 않는다")
            return AlternateOutcome(False, reason=content_verdict.reason, notes=notes)
        notes.append(f"{alt.kind}: {content_verdict.reason}")

    return AlternateOutcome(False, reason=None, notes=notes)
