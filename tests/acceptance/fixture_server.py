#!/usr/bin/env python3
"""로컬 픽스처 HTTP 서버 — 인수 테스트가 직접 기동/종료한다.

실제 WAF 사이트를 인수 테스트에 넣지 않기 위한 결정론적 대역이다.
각 응답은 실제 사이트의 복사본이 아니라 판정 신호의 최소 재현 형태다 (NG-12).

포트는 0번 바인딩으로 OS가 할당하고, 실제 포트를 --port-file 경로에 기록한다.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ── 요청 카운터 ────────────────────────────────────────────────────────────
# "요청하지 않았다"는 US-B-010 음성 케이스의 핵심 단언인데, 출력만 봐서는
# 요청이 없었는지 있었다가 실패했는지 구분되지 않는다. 서버가 직접 센다.
_HITS: dict[str, int] = {}
_HITS_LOCK = threading.Lock()


def _record_hit(path: str) -> None:
    with _HITS_LOCK:
        _HITS[path] = _HITS.get(path, 0) + 1

# 본문 추출 검증용 마커 — 각각 "남아야 하는 것"과 "사라져야 하는 것"
BODY_MARKER = "OPENREACH-BODY-MARKER"
SCRIPT_MARKER = "OPENREACH-SCRIPT-MARKER"
NAV_MARKER = "OPENREACH-NAV-MARKER"
FOOTER_MARKER = "OPENREACH-FOOTER-MARKER"

_LOREM = (
    "공개 문서의 본문 문단이다. 본문 추출기는 이 문단을 살리고 주변 잡음을 버려야 한다. "
) * 12

PUBLIC_ARTICLE = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>공개 기술 문서 — open-reach fixture</title>
<script>var trap = "{SCRIPT_MARKER}";</script>
<style>body {{ color: #111; }}</style>
</head><body>
<nav>{NAV_MARKER} 홈 · 문서 · 블로그</nav>
<article><h1>공개 기술 문서</h1><p>{BODY_MARKER}</p><p>{_LOREM}</p></article>
<footer>{FOOTER_MARKER} (c) fixture</footer>
</body></html>"""

LOGIN_WALL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Sign in</title></head>
<body><h1>Sign in to continue</h1>
<form method="post" action="/login">
<input type="email" name="email"><input type="password" name="password">
<button type="submit">Log in</button></form>
<p>You must sign in to continue reading this page.</p>
</body></html>"""

PAYWALL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Members only</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"NewsArticle","isAccessibleForFree":false}
</script></head>
<body><article><p>The opening paragraph is visible to everyone.</p>
<p class="truncated">[...]</p>
<div class="paywall">Subscribe to continue reading.</div></article></body></html>"""

CHALLENGE_200 = """<!doctype html>
<html><head><meta charset="utf-8"><title>Just a moment...</title></head>
<body><div id="challenge-running">Checking your browser before accessing the site.
Please enable JavaScript and cookies to continue.</div>
<noscript>Please turn JavaScript on.</noscript></body></html>"""

CAPTCHA_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Verify you are human</title></head>
<body><h1>Verify you are human</h1>
<div class="captcha-widget" data-sitekey="fixture-sitekey"></div>
<p>Complete the challenge below to continue.</p></body></html>"""

CHALLENGE_403 = """<!doctype html>
<html><head><meta charset="utf-8"><title>Access denied</title></head>
<body><h1>Access denied</h1><p>Your request has been blocked.</p></body></html>"""

# 브라우저 티어(T2) 대역 — JS 를 실행해야만 본문이 드러나는 챌린지.
# 비-JS 클라이언트(curl_cffi=HTTP 티어)에게는 challenge 신호만 보여 waf_challenge 로
# 막히고, 실제 브라우저가 스크립트를 실행하면 title·body 가 공개 기사로 교체되어
# 어떤 challenge 신호도 남지 않는다 → detect.classify 가 success 로 판정한다.
# 실제 챌린지의 복사본이 아니라 "JS 실행 시에만 본문이 나타난다"는 판정 신호의 최소
# 재현이다 (NG-12). 스크립트·기사 문면에 challenge/ captcha 키워드를 넣지 않는다.
JS_CHALLENGE = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Just a moment...</title></head>
<body>
<div id="challenge-running">Checking your browser before accessing the site.
Please enable JavaScript and cookies to continue.</div>
<script>
document.title = "공개 기술 문서";
document.body.innerHTML =
  "<article><h1>공개 기술 문서</h1>" +
  "<p>{BODY_MARKER}</p>" +
  "<p>{_LOREM}</p></article>";
</script>
</body></html>"""

# 403이지만 정상 본문인 케이스 — 상태 코드 단독 판정 금지의 반례
FORBIDDEN_BUT_REAL = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>정상 본문 (403)</title></head>
<body><article><p>{BODY_MARKER}</p><p>{_LOREM}</p></article></body></html>"""

ROBOTS = "User-agent: *\nDisallow: /norobots/\n"

# ── US-B-010 (Phase 0 공개 API 라우팅) 대역 ────────────────────────────────
# 원문 경로는 403으로 막아 HTTP 경로를 실패시킨다 (AC-B-010-1: API는 그 뒤에만).
API_README = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>README — open-reach fixture</title></head>
<body><article><p>{BODY_MARKER}</p><p>{_LOREM}</p></article></body></html>"""

# step 1 응답 변종 — 각각 하나의 조립 규칙을 겨눈다
API_STEP1 = {
    # 정상: 앵커 패턴에 맞는 스칼라 버전
    "ok": {"crate": {"max_stable_version": "1.0.229"}},
    # AC-B-010-9: select 자리에 배열 — 스칼라가 아니면 중단
    "array": {"crate": {"max_stable_version": ["1.0.229", "1.0.228"]}},
    # AC-B-010-10: value_pattern 불일치 — 요청하지 않고 중단
    "mismatch": {"crate": {"max_stable_version": "latest-and-greatest"}},
    # AC-B-010-11: 경로 세그먼트를 벗어나는 값 — 패턴과 별개로 이중 거부
    "slashy": {"crate": {"max_stable_version": "1.0.229/../../norobots/doc"}},
    # AC-B-010-11: 상대 경로 세그먼트 자체 — 점을 문자로 허용해도 이것은 막아야 한다
    "dotdot": {"crate": {"max_stable_version": ".."}},
    # AC-B-010-13: 조립 결과가 robots Disallow 경로가 되는 값
    "norobots": {"crate": {"max_stable_version": "doc"}},
}

# AC-B-010-12: 응답이 다른 목적지를 "지시"해도 따라가지 않는다.
# 모든 step 1 응답에 같은 유혹을 심어 둔다 — /api/evil 은 끝까지 0회여야 한다.
for _v in API_STEP1.values():
    _v["next_url"] = "/api/evil"
    _v["host"] = "evil.invalid"


# ── US-B-012 / US-B-014 (R5) 대역 ──────────────────────────────────────────
# 검색 결과 페이지의 최소 재현(NG-12): 짧은 블록(<80자) 다수, 합계 200~999자.
# 명시 선언 없이 닿으면 nav_shell 로 validation_failed 가 되고, 선언된 검색
# URL 로 닿으면 nav_shell 판정만 면제되어 성공해야 한다 (AC-B-014-1).
# 문구는 wall(_로그인_·sign in·continue reading)·challenge·captcha 신호어를 피한다.
_SEARCH_ITEMS = "".join(
    f"<p>항목 {i} — rust 주제를 다루는 공개 문서의 한 줄 요약이 여기에 놓인다.</p>"
    for i in range(1, 11)
)
SEARCH_RESULTS = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>검색 — open-reach fixture</title></head>
<body><main><h1>검색</h1>{_SEARCH_ITEMS}</main></body></html>"""

# 결과 0건 — 선언된 검색 URL 이라도 길이 하한(200자)은 유지되어야 한다 (AC-B-014-1).
SEARCH_EMPTY = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>검색 — open-reach fixture</title></head>
<body><main><h1>검색</h1><p>결과 0건.</p></main></body></html>"""


# ── R6 (US-B-015~018) 대역 ────────────────────────────────────────────────
# 메뉴 껍데기 — 짧은 블록만 있고 합계가 1,000자 미만이라 nav_shell 로 떨어진다.
# 자기선언 티어(US-B-018)의 진입 조건("바이트는 받았는데 본문이 못 쓸 때")을 만드는
# 최소 형태다. head 에 무엇을 선언하느냐만 바꿔 가며 이 셸을 재사용한다.
_SHELL_ITEMS = "".join(
    f"<p>항목 {i} — 목록 껍데기의 한 줄이다. 본문이 아니다.</p>" for i in range(1, 11)
)


def _shell(head_extra: str = "") -> str:
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>목록 셸</title>
{head_extra}</head>
<body><main><h1>목록</h1>{_SHELL_ITEMS}</main></body></html>"""


# JSON-LD articleBody — **요청 0건**으로 얻는 본문. 길이 하한과 nav_shell 을 모두
# 넘도록 충분히 길게 둔다 (이 티어는 판정을 느슨하게 하지 않는다).
_JSONLD_BODY = (
    f"{BODY_MARKER} 이 문단은 페이지가 JSON-LD 로 스스로 실어 둔 본문이다. "
    "발행자가 적어 둔 것을 읽는 일이라 추측이 아니며, 회선에 요청이 한 건도 나가지 않는다. "
) * 12

JSONLD_SHELL = _shell(
    '<script type="application/ld+json">'
    + json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "headline": "자기선언 본문",
            "articleBody": _JSONLD_BODY,
        },
        ensure_ascii=False,
    )
    + "</script>"
    # 미끼: JSON-LD 가 이겼다면 이 피드는 끝까지 0회여야 한다 (우선순위 + 예산).
    + '<link rel="alternate" type="application/rss+xml" href="/altdecoy/feed.xml">'
)

FEED_SHELL = _shell(
    '<link rel="alternate" type="application/rss+xml" href="/alt/feed.xml">'
)
MISMATCH_SHELL = _shell(
    '<link rel="alternate" type="application/rss+xml" href="/alt/others.xml">'
)
# 선언되어 있다는 사실은 안전을 보증하지 않는다 — 후보도 SSRF 가드를 새로 통과해야
# 한다 (NG-11). 포트가 달라 픽스처 예외 오리진에 해당하지 않는다.
SSRF_SHELL = _shell('<link rel="amphtml" href="http://127.0.0.1:1/x">')
# 선언이 하나도 없는 셸 — 이 티어가 요청을 0건 내는 것이 정상이며, 그 사실이
# "맹목 변형(m./amp. 접두 부착)이 부활하지 않았다"의 증거다.
BARE_SHELL = _shell()


# US-B-018 — 부피만 크고 수확이 없는 문서. 안내문 한 문단은 문장 형태라 문단 검사와
# 길이 하한을 통과하지만, 받은 바이트 대비 건진 양이 바닥이라 성공이 아니다.
_STARVE_NOTICE = "AI가 생성한 결과는 정확하지 않거나 최신 정보가 아닐 수 있습니다. " * 6
STARVE_PAGE = (
    "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
    "<title>부피만 큰 문서</title></head><body>"
    + "<!--" + ("x" * 200_000) + "-->"
    + f"<div><p>{_STARVE_NOTICE}</p></div></body></html>"
)

# US-B-018 — main/article 선언이 없는 문서. 밀도 폴백이 본문 컨테이너를 골라야 하고,
# 메뉴는 본문에 섞이면 안 된다.
_DENSE_LINKS = "".join(f'<a href="/x/{i}">{NAV_MARKER}{i}</a> ' for i in range(20))
DENSE_PAGE = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>선언 없는 문서</title></head>
<body><div id="menu">{_DENSE_LINKS}</div>
<div id="content"><p>{BODY_MARKER}</p><p>{_LOREM}</p></div></body></html>"""


def _feed_item(link: str, title: str) -> str:
    return (
        f"<item><title>{title}</title><link>{link}</link>"
        f"<description><![CDATA[<p>{BODY_MARKER}</p><p>{_LOREM}</p>]]></description></item>"
    )


def _feed(items: list[str]) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<rss version=\"2.0\"><channel><title>fixture feed</title>"
        + "".join(items)
        + "</channel></rss>"
    )


# 검색 후보로 회수되는 실제 문서. 본문 안에 링크를 심어 둔다 — 검색 계층이 취득
# 본문에서 링크를 뽑아 다시 큐에 넣지 않는다는 것(무재귀, NG-5 개정판의 방벽)은
# /trap/ 히트 0 으로만 증명된다.
SEARCH_DOC_COUNT = 12


def _doc_article(slug: str) -> str:
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>문서 {slug}</title></head>
<body><nav>{NAV_MARKER}</nav>
<article><h1>문서 {slug}</h1><p>{BODY_MARKER}</p><p>{_LOREM}</p>
<p><a href="/trap/{slug}">이어지는 문서</a></p></article>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "open-reach-fixture/1"

    def log_message(self, fmt, *args):  # noqa: A002 - stdlib signature
        sys.stderr.write("[fixture] " + (fmt % args) + "\n")

    def _send(self, code: int, body: str, ctype: str = "text/html; charset=utf-8",
              extra: dict[str, str] | None = None) -> None:
        payload = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, code: int, obj: object) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False),
                   ctype="application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        path = self.path.split("?", 1)[0]
        # 히트 카운터는 쿼리를 떼고 세므로, "치환된 쿼리 값이 실제 요청에 실렸는가"는
        # 응답 본문에 쿼리를 되비추는 라우트(RAWQ 마커)로만 구분한다 (US-B-012).
        query = self.path.split("?", 1)[1] if "?" in self.path else ""
        _record_hit(path)

        # ── US-B-010 대역 ──────────────────────────────────────────────
        if path == "/_hits":
            with _HITS_LOCK:
                self._send_json(200, dict(_HITS))
            return
        if path == "/_hits/reset":
            with _HITS_LOCK:
                _HITS.clear()
            self._send_json(200, {"reset": True})
            return
        if path.startswith("/api/origin/"):
            # 원문 경로 — HTTP 경로를 실패시켜 Phase 0 로 넘어가게 한다
            self._send(403, CHALLENGE_403)
            return
        if path.startswith("/api/step1/"):
            variant = path.rsplit("/", 1)[-1]
            if variant in API_STEP1:
                self._send_json(200, API_STEP1[variant])
            else:
                self._send(404, "<html><body>unknown step1 variant</body></html>")
            return
        if path.startswith("/api/step2/"):
            self._send(200, API_README)
            return
        if path.startswith("/api/ep"):
            # 예산 테스트용 엔드포인트 — 본문이 없어 구제에 실패한다
            self._send_json(200, {"note": "no article body here"})
            return
        if path == "/api/evil":
            # 응답이 지시한 목적지. 요청되면 그 자체로 계약 위반이다.
            self._send(200, API_README)
            return

        # ── US-B-012 / US-B-014 (R5) 대역 ─────────────────────────────
        if path == "/q/item":
            # 쿼리 캡처 원문 경로 — HTTP 티어를 실패시켜 Phase 0 로 넘긴다
            self._send(403, CHALLENGE_403)
            return
        if path == "/api/qitem":
            # 수신한 쿼리를 본문에 그대로 되비춘다 — 치환값 실림 단언용
            self._send_json(200, {"item": {"text": f"{BODY_MARKER} RAWQ[{query}] {_LOREM}"}})
            return
        if path == "/api/auth401":
            # 인증을 요구하는 어댑터 엔드포인트 — 돌파 없이 auth_wall 보고 (AC-B-012-3)
            self._send(401, LOGIN_WALL)
            return
        if path == "/search/results":
            if query == "q=none":
                self._send(200, SEARCH_EMPTY)
            else:
                self._send(200, SEARCH_RESULTS)
            return
        if path == "/search/challenge":
            # 선언된 검색 URL 이라도 챌린지 판정은 유지되어야 한다 (AC-B-014-3)
            self._send(200, CHALLENGE_200)
            return
        if path == "/redir/tosearch":
            # 리디렉트로 검색 페이지에 "도착"한 경우 — 명시 판정은 입력 URL 로만 (AC-B-014-2)
            self.send_response(302)
            self.send_header("Location", "/search/results?q=rust")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        # ── R6 (US-B-015~018) 대역 ────────────────────────────────────
        host = self.headers.get("Host") or "127.0.0.1"
        if path.startswith("/doc/a"):
            self._send(200, _doc_article(path.rsplit("/", 1)[-1]))
            return
        if path == "/srch/json":
            self._send_json(200, {"hits": [
                {"link": f"http://{host}/doc/a{i}", "name": f"결과 {i}"}
                for i in range(1, SEARCH_DOC_COUNT + 1)
            ]})
            return
        if path == "/srch/json2":
            # 앞 소스와 겹치는 후보 — dedupe 단언용
            self._send_json(200, {"hits": [
                {"link": f"http://{host}/doc/a{i}", "name": f"중복 {i}"}
                for i in (1, 2, 3)
            ]})
            return
        if path == "/srch/html":
            links = "".join(
                f'<a class="r" href="http://{host}/doc/a{i}">결과 {i}</a>'
                for i in range(1, 6)
            )
            self._send(200,
                       f"<!doctype html><html><body><ol>{links}</ol></body></html>")
            return
        if path == "/srch/empty":
            self._send_json(200, {"hits": []})
            return
        if path == "/alt/none":
            self._send(200, BARE_SHELL)
            return
        if path == "/alt/jsonld":
            self._send(200, JSONLD_SHELL)
            return
        if path == "/alt/feed":
            self._send(200, FEED_SHELL)
            return
        if path == "/alt/feed.xml":
            self._send(200, _feed([_feed_item(f"http://{host}/alt/feed", "단일 항목")]),
                       ctype="application/rss+xml; charset=utf-8")
            return
        if path == "/alt/mismatch":
            self._send(200, MISMATCH_SHELL)
            return
        if path == "/alt/others.xml":
            # 두 항목 어느 쪽도 요청한 문서가 아니다 — 다른 글을 성공이라 부르지 않는다
            self._send(200, _feed([
                _feed_item(f"http://{host}/alt/other-1", "다른 글 1"),
                _feed_item(f"http://{host}/alt/other-2", "다른 글 2"),
            ]), ctype="application/rss+xml; charset=utf-8")
            return
        if path == "/starve/page":
            self._send(200, STARVE_PAGE)
            return
        if path == "/dense/article":
            self._send(200, DENSE_PAGE)
            return
        if path == "/alt/ssrf":
            self._send(200, SSRF_SHELL)
            return

        if path == "/public/article":
            self._send(200, PUBLIC_ARTICLE)
        elif path == "/wall/login":
            self._send(200, LOGIN_WALL)
        elif path == "/wall/paywall":
            self._send(200, PAYWALL)
        elif path == "/waf/challenge":
            self._send(200, CHALLENGE_200,
                       extra={"Set-Cookie": "fixture_clearance=abc123; Path=/"})
        elif path == "/waf/challenge-403":
            self._send(403, CHALLENGE_403)
        elif path == "/waf/js-challenge":
            # 200 + challenge 신호 → HTTP 티어는 waf_challenge. JS 실행 시에만 본문 등장.
            self._send(200, JS_CHALLENGE)
        elif path == "/waf/captcha":
            self._send(403, CAPTCHA_PAGE)
        elif path == "/waf/forbidden-but-real":
            self._send(403, FORBIDDEN_BUT_REAL)
        elif path == "/err/404":
            self._send(404, "<html><body>not found</body></html>")
        elif path == "/err/500":
            self._send(500, "<html><body>server error</body></html>")
        elif path == "/err/429":
            self._send(429, "<html><body>too many requests</body></html>",
                       extra={"Retry-After": "1"})
        elif path == "/redir/private":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/x")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/redir/public":
            self.send_response(302)
            self.send_header("Location", "/public/article")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/robots.txt":
            self._send(200, ROBOTS, ctype="text/plain; charset=utf-8")
        elif path == "/norobots/doc":
            # robots.txt 가 Disallow 한 경로 — 내용 자체는 정상 공개 문서다
            self._send(200, PUBLIC_ARTICLE)
        elif path == "/health":
            self._send(200, "ok", ctype="text/plain; charset=utf-8")
        else:
            self._send(404, "<html><body>unknown fixture route</body></html>")

    do_HEAD = do_GET


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port-file", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    httpd = ThreadingHTTPServer((args.host, 0), Handler)
    port = httpd.socket.getsockname()[1]

    with open(args.port_file, "w", encoding="utf-8") as handle:
        handle.write(str(port))

    sys.stderr.write(f"[fixture] listening on {args.host}:{port}\n")
    sys.stderr.flush()

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    socket.setdefaulttimeout(30)
    raise SystemExit(main())
