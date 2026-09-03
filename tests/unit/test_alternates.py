"""자기선언 열린문 티어(R6/W3)의 변이 사멸 테스트.

이 티어의 위험은 두 가지고, 테스트는 그 둘을 정면으로 겨눈다.

1. **맹목 변형의 부활** — R2 에서 `m.`·`amp.` 접두 부착을 12건 중 0건으로 폐기했다.
   선언이 없는 HTML 에 대해 요청이 **0 건**임을 히트 수로 고정한다. "선언을 못 찾으면
   그냥 붙여 보자"는 변이는 히트가 1 이상이 되어 죽는다.
2. **그럴듯한 거짓 성공** — 피드를 받았는데 그 안에 요청한 문서가 없을 때 아무 항목이나
   본문으로 내주는 것. 같은 호스트의 다른 글이라 길이·문장 구조가 진짜 본문과 같아서
   `detect.classify` 로는 절대 못 잡는다 (NG-10).

루프백 픽스처 서버를 쓴다 — SPEC 이 인정한 예외(`OPENREACH_FIXTURE_BASE`).
"""

import http.server
import json
import pathlib
import sys
import threading

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import alternates, fetcher, models, policy  # noqa: E402

HITS: dict[str, int] = {}

# 본문이라 부를 만한 산문 한 덩어리. MIN_ARTICLE_CHARS·MIN_PROSE_BLOCK_CHARS 를 넘긴다.
PROSE = (
    "이 문단은 자기선언 열린문 티어가 실제로 본문을 회수했는지 확인하기 위한 산문이다. "
    "길이 하한과 문단 길이 하한을 모두 넘겨야 detect.classify 가 성공으로 판정한다. "
) * 4

# HTTP 티어가 nav_shell 로 실패하는 껍데기. 문단이 없고 총량도 적다.
SHELL_BODY = "<ul><li>홈</li><li>소개</li><li>목록</li><li>연락</li></ul>"


def _shell(head: str = "") -> str:
    return f"<html><head>{head}</head><body>{SHELL_BODY}</body></html>"


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _body(self, status: int, text: str, ctype: str = "text/html; charset=utf-8"):
        raw = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: C901 — 픽스처 라우팅
        HITS[self.path] = HITS.get(self.path, 0) + 1
        base = f"http://127.0.0.1:{self.server.server_address[1]}"

        if self.path == "/bare":
            # 선언이 전혀 없는 껍데기 — 이 티어는 요청을 내면 안 된다
            self._body(200, _shell())
        elif self.path == "/bare.rss" or self.path == "/bare/amp":
            # 맹목 변형이 부활하면 여기가 두들겨진다. 존재하되 성공하지 않는다.
            self._body(200, f"<html><body><article>{PROSE}</article></body></html>")
        elif self.path == "/jsonld":
            payload = json.dumps(
                {"@context": "https://schema.org", "@graph": [
                    {"@type": "WebSite"},
                    {"@type": "Article", "headline": "선언된 제목", "articleBody": PROSE},
                ]},
                ensure_ascii=False,
            )
            self._body(
                200,
                _shell(f'<script type="application/ld+json">{payload}</script>'),
            )
        elif self.path == "/feed-doc":
            head = (
                '<link rel="alternate" type="application/rss+xml" href="/feed-doc.rss">'
            )
            self._body(200, _shell(head))
        elif self.path == "/feed-doc.rss":
            self._body(
                200,
                "<rss><channel><item>"
                "<title>선언된 피드 제목</title>"
                f"<link>{base}/feed-doc</link>"
                f"<description><![CDATA[<p>{PROSE}</p>]]></description>"
                "</item></channel></rss>",
                "application/rss+xml",
            )
        elif self.path == "/other-doc":
            head = (
                '<link rel="alternate" type="application/rss+xml" href="/other-doc.rss">'
            )
            self._body(200, _shell(head))
        elif self.path == "/other-doc.rss":
            # 항목이 둘이고 **둘 다 다른 글**이다 — 성공으로 내주면 거짓말이다
            self._body(
                200,
                "<rss><channel>"
                f"<item><title>남의 글 1</title><link>{base}/somewhere-else</link>"
                f"<description><![CDATA[<p>{PROSE}</p>]]></description></item>"
                f"<item><title>남의 글 2</title><link>{base}/another</link>"
                f"<description><![CDATA[<p>{PROSE}</p>]]></description></item>"
                "</channel></rss>",
                "application/rss+xml",
            )
        elif self.path == "/private-alt":
            # 선언이 사설 대역을 가리킨다 — 선언되어 있다고 안전한 것이 아니다 (NG-11)
            head = (
                '<link rel="alternate" type="application/rss+xml" '
                'href="http://127.0.0.1:1/secret.rss">'
            )
            self._body(200, _shell(head))
        elif self.path == "/amp-doc":
            self._body(200, _shell('<link rel="amphtml" href="/amp-doc/amp">'))
        elif self.path == "/amp-doc/amp":
            self._body(200, f"<html><body><article>{PROSE}</article></body></html>")
        elif self.path == "/wall-behind":
            # 껍데기다(티어가 뜬다). 선언은 둘 — 피드가 먼저고, **뒤에 성공하는 amp** 가
            # 있다. 피드 자리에서 만난 벽을 mismatch 로 적고 넘어가는 변이가 살아 있으면
            # amp 로 취득에 성공해 버린다.
            head = (
                '<link rel="alternate" type="application/rss+xml" href="/wall-feed">'
                '<link rel="amphtml" href="/amp-doc/amp">'
            )
            self._body(200, _shell(head))
        elif self.path == "/wall-feed":
            # 피드를 달라 했는데 로그인월이 왔다
            self._body(
                200,
                "<html><body>"
                "<div>이 기사를 보려면 로그인하세요. Sign in to continue reading.</div>"
                '<form><input type="password" name="pw"></form>'
                "</body></html>",
            )
        elif self.path == "/login-copy":
            # 벽이 아니다. 첫 선언은 **정상 피드**인데 요청한 글이 없을 뿐이고,
            # 다음 선언(amp)에서 취득에 성공해야 한다.
            head = (
                '<link rel="alternate" type="application/rss+xml" href="/login-copy.rss">'
                '<link rel="amphtml" href="/amp-doc/amp">'
            )
            self._body(200, _shell(head))
        elif self.path == "/login-copy.rss":
            # 항목이 둘이고 둘 다 남의 글이라 entry 는 None 이다 — 파싱 실패 자리로 간다.
            # 그 자리에서 보이는 것은 로그인 문구와 password 입력이지만, 그것은 **읽히는
            # 본문의 내용**이지 벽이 아니다. 공개 피드가 로그인 방법을 설명할 자유가 있다.
            self._body(
                200,
                "<rss><channel>"
                "<item><title>로그인 안내</title>"
                f"<link>{base}/somewhere-else</link>"
                f"<description>{PROSE} 이 기사를 보려면 로그인하세요. "
                'Sign in to continue reading. <input type="password" name="pw">'
                "</description></item>"
                "<item><title>남의 글</title>"
                f"<link>{base}/another</link>"
                f"<description>{PROSE}</description></item>"
                "</channel></rss>",
                "application/rss+xml",
            )
        elif self.path == "/pay-doc":
            self._body(200, _shell('<link rel="amphtml" href="/pay-doc/amp">'))
        elif self.path == "/pay-doc/amp":
            # 선언을 따라간 자리에 발행자 스스로 붙인 페이월 선언이 있다
            self._body(
                200,
                "<html><head>"
                '<script type="application/ld+json">'
                '{"@type":"Article","isAccessibleForFree":false}</script>'
                f"</head><body><article>{PROSE}</article></body></html>",
            )
        elif self.path == "/redir-alt":
            head = (
                '<link rel="alternate" type="application/rss+xml" href="/redir-feed">'
            )
            self._body(200, _shell(head))
        elif self.path == "/redir-feed":
            # 공개 주소로 시작해 사설 대역으로 넘긴다 — 홉 가드가 잡을 자리다
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/secret.rss")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == "/wall-doc":
            # 로그인월 + 선언. 경계는 선언을 따라간다고 뒤집히지 않는다 (NG-1)
            head = '<link rel="amphtml" href="/amp-doc/amp">'
            self._body(
                200,
                f"<html><head>{head}</head><body>"
                "<div>이 기사를 보려면 로그인하세요. Sign in to continue reading.</div>"
                '<form><input type="password" name="pw"></form>'
                "</body></html>",
            )
        else:
            self._body(404, "<html><body>nope</body></html>")


@pytest.fixture(scope="module")
def server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(autouse=True)
def _isolate(server, monkeypatch):
    monkeypatch.setenv("OPENREACH_FIXTURE_BASE", server)
    HITS.clear()
    policy._robots_cache.clear()
    yield
    policy._robots_cache.clear()


def _fetch(server: str, path: str):
    return fetcher.fetch(
        models.FetchRequest(
            url=f"{server}{path}",
            timeout_s=5.0,
            max_attempts=1,
            no_impersonate=True,
        )
    )


# ── ① 맹목 변형이 부활하지 않았다 ─────────────────────────────────────────


def test_no_declaration_means_no_request(server):
    """죽여야 할 변이: 선언이 없을 때 `.rss`·`/amp` 를 붙여서 두드려 보기.

    R2 가 0/12 로 폐기한 경로다. 픽스처는 그 두 주소에 **실제로 본문을 놓아 두었으므로**,
    변이가 살아 있으면 취득에 성공해 버린다 — 결과만 보는 테스트는 그것을 개선으로
    착각한다. 그래서 성공/실패가 아니라 **히트 수 0** 으로 고정한다.
    """
    result = _fetch(server, "/bare")
    assert not result.ok
    assert HITS.get("/bare.rss", 0) == 0
    assert HITS.get("/bare/amp", 0) == 0
    assert HITS.get("/bare", 0) == 1
    assert not any(a.route == "alternate" for a in result.attempts)


def test_discover_returns_nothing_for_undeclared_html():
    """순수 함수 층에서도 같은 계약 — 선언이 없으면 후보가 없다."""
    assert alternates.discover(_shell(), "https://example.com/x") == []


# ── ② 거짓 성공을 만들지 않는다 ───────────────────────────────────────────


def test_feed_without_our_document_is_not_success(server):
    """죽여야 할 변이: 피드 첫 항목을 그냥 본문으로 쓰기.

    이 변이는 `detect.classify` 를 통과한다 — 받아 온 것이 **진짜 산문**이기 때문이다.
    다만 우리가 요청한 글이 아니다. 판정기로는 절대 못 잡으므로 여기서 고정한다.
    """
    result = _fetch(server, "/other-doc")
    assert not result.ok
    assert HITS.get("/other-doc.rss", 0) == 1, "피드는 실제로 두드렸어야 한다"
    mismatch = [a for a in result.attempts if a.outcome == "mismatch"]
    assert mismatch, "요청한 문서가 없었다는 사실이 attempts 에 남아야 한다 (NG-10)"
    assert mismatch[0].route == "alternate"


def test_feed_entry_for_picks_the_requested_document():
    """여러 항목 중 링크가 일치하는 것만 쓴다."""
    feed = (
        "<rss><channel>"
        "<item><link>https://e.com/a</link><description>AAAA</description></item>"
        "<item><link>https://e.com/b</link><description>BBBB</description></item>"
        "</channel></rss>"
    )
    got = alternates.feed_entry_for(feed, "https://e.com/b/")
    assert got is not None and "BBBB" in got[0]
    assert alternates.feed_entry_for(feed, "https://e.com/zzz") is None


# ── ③ 선언을 따라가 실제로 구제한다 ───────────────────────────────────────


def test_jsonld_body_rescues_without_any_request(server):
    """가장 싼 승리 — 요청 0건. 죽여야 할 변이: JSON-LD 후보를 뒤로 미루기."""
    result = _fetch(server, "/jsonld")
    assert result.ok, result.failure_reason
    assert result.final_route == "alternate"
    assert result.metadata["title"] == "선언된 제목"
    # 추가 회선을 쓰지 않았다 — 이 경로의 요점이다
    assert sum(HITS.values()) == 1


def test_declared_feed_rescues_the_shell(server):
    result = _fetch(server, "/feed-doc")
    assert result.ok, result.failure_reason
    assert result.final_route == "alternate"
    assert "자기선언" in result.content_markdown
    assert HITS.get("/feed-doc.rss", 0) == 1


def test_declared_amphtml_rescues_the_shell(server):
    result = _fetch(server, "/amp-doc")
    assert result.ok, result.failure_reason
    assert result.final_route == "alternate"
    assert [a.url_variant for a in result.attempts if a.route == "alternate"] == ["amp"]


# ── ④ 경계는 그대로다 ─────────────────────────────────────────────────────


def test_declared_alternate_is_ssrf_rechecked(server):
    """죽여야 할 변이: "원본이 공개였으니 그 선언도 안전하다"는 생략 (NG-11)."""
    result = _fetch(server, "/private-alt")
    assert not result.ok
    assert result.failure_reason == "policy_blocked"
    assert HITS.get("/secret.rss", 0) == 0


def test_auth_wall_does_not_reach_the_tier(server):
    """죽여야 할 변이: 경계 판정 뒤에도 선언을 따라가 보기 (NG-1).

    로그인월은 선언을 따라간다고 뒤집히지 않는다 — 그 시도 자체가 우회다.
    픽스처는 벽 페이지에 **동작하는 amphtml 선언**을 달아 두었으므로, 티어가
    부주의하게 뜨면 취득에 성공해 버린다.
    """
    result = _fetch(server, "/wall-doc")
    assert not result.ok
    assert result.failure_reason == "auth_wall"
    assert HITS.get("/amp-doc/amp", 0) == 0


def test_wall_behind_a_declaration_stops_the_whole_tier(server):
    """죽여야 할 변이: 선언 자리에 온 로그인월을 "파싱 실패(mismatch)"로 적고 넘어가기.

    진입 시점의 경계 판정(`worthy`)은 **원본 HTML** 만 본다. 벽이 선언 뒤에 있으면
    그 판정은 통과하고, 벽은 피드를 파싱하려는 자리에서 처음 드러난다. 거기서
    mismatch 로 적으면 남은 선언으로 같은 벽을 다른 문으로 두드린다 — 픽스처는
    그 다음 선언에 **성공하는 amp** 를 놓아 두었으므로 변이는 취득에 성공한다.
    """
    result = _fetch(server, "/wall-behind")
    assert not result.ok
    assert result.failure_reason == "auth_wall", "벽을 벽이라 부르지 않았다"
    assert HITS.get("/amp-doc/amp", 0) == 0, "경계를 만난 뒤 남은 선언을 두드렸다 (NG-1)"
    walls = [a for a in result.attempts if a.route == "alternate" and a.outcome == "wall"]
    assert walls, "어느 선언에서 벽을 만났는지가 attempts 에 남아야 한다 (NG-10)"


def test_login_words_in_a_working_feed_are_not_a_wall(server):
    """죽여야 할 변이: 파싱 실패 자리의 벽 판정을 `extracted=""` 로 부르기.

    `detect_wall` 의 로그인월 휴리스틱에는 "읽을 본문이 없을 때만"이라는 조건이
    붙어 있고 그 조건은 `extracted` 로 전달된다. 빈 문자열을 주면 장치가 꺼져,
    로그인 문구와 password 입력이 **내용으로** 실린 정상 피드가 auth_wall 로
    뒤집히고 — 요청한 글이 없을 뿐인 응답이 exit 2 경계 보고가 되며 뒤에 있는
    성공하는 선언까지 중단된다. 위양성의 대가가 위음성보다 크다.
    """
    result = _fetch(server, "/login-copy")
    assert result.ok, f"정상 피드를 벽으로 오판했다 — {result.failure_reason}"
    assert HITS.get("/amp-doc/amp", 0) >= 1, "다음 선언을 두드리지 않았다"
    mismatches = [
        a for a in result.attempts if a.route == "alternate" and a.outcome == "mismatch"
    ]
    assert mismatches, "요청한 글이 없는 것은 mismatch 로 남아야 한다"


def test_paywall_in_declared_content_is_not_laundered(server):
    """죽여야 할 변이: 대체 표현의 경계 사유를 버리고 상위 티어로 흘려보내기.

    사유를 버리면 exit 는 2(경계)가 아니라 1이 되고, 상위 티어가 같은 벽을 다시 민다.
    """
    result = _fetch(server, "/pay-doc")
    assert not result.ok
    assert result.failure_reason == "paywall"
    assert result.exit_code() == 2, "경계는 exit 2 다 — 사유가 세탁되면 1 이 된다"


def test_hop_blocked_alternate_is_recorded(server):
    """죽여야 할 변이: 홉에서 막힌 시도를 이력 없이 반환하기.

    요청은 실제로 나갔다. 이력이 비면 결과에는 endpoint 없는 정책 차단만 남아,
    관측만 보고는 **어느 선언을 두드리다** 막혔는지 재구성할 수 없다 (NG-10).
    """
    result = _fetch(server, "/redir-alt")
    assert not result.ok
    assert result.failure_reason == "policy_blocked"
    blocked = [
        a for a in result.attempts if a.route == "alternate" and a.outcome == "blocked"
    ]
    assert blocked, "막힌 대체 시도가 attempts 에 남아야 한다"
    assert blocked[0].endpoint.endswith("/redir-feed")
    assert HITS.get("/secret.rss", 0) == 0


@pytest.mark.parametrize(
    "reason,signals,expected",
    [
        ("validation_failed", ("nav_shell",), True),
        ("validation_failed", ("js_shell",), True),
        # 추출 글자가 적을 뿐 HTML 은 있다 — 선언만 실린 JS 렌더 페이지가 이 형태다
        ("validation_failed", ("empty_body",), True),
        # 경계·차단·부재는 선언으로 뒤집히지 않는다
        ("auth_wall", ("nav_shell",), False),
        ("paywall", ("nav_shell",), False),
        ("waf_challenge", (), False),
        ("rate_limited", (), False),
        (None, (), False),
    ],
)
def test_worthy_is_a_closed_decision(reason, signals, expected):
    """진입 조건을 순수 함수로 고정한다 — 조건이 넓어지는 변이를 죽인다."""
    assert alternates.worthy(reason, signals) is expected


def test_budget_caps_the_requests():
    """죽여야 할 변이: 예산 상한 제거 (NG-5 — 상한 있는 수집기여야 한다)."""
    assert alternates.BUDGET == 2


def test_same_origin_canonical_is_not_a_candidate():
    """방금 실패한 그 페이지를 다시 두드리는 변이를 죽인다."""
    html = _shell('<link rel="canonical" href="https://e.com/doc/">')
    assert alternates.discover(html, "https://e.com/doc") == []
    cross = _shell('<link rel="canonical" href="https://other.example/doc">')
    got = alternates.discover(cross, "https://e.com/doc")
    assert [a.kind for a in got] == [alternates.KIND_CANONICAL]
