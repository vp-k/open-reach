#!/usr/bin/env python3
"""로컬 픽스처 HTTP 서버 — 인수 테스트가 직접 기동/종료한다.

실제 WAF 사이트를 인수 테스트에 넣지 않기 위한 결정론적 대역이다.
각 응답은 실제 사이트의 복사본이 아니라 판정 신호의 최소 재현 형태다 (NG-12).

포트는 0번 바인딩으로 OS가 할당하고, 실제 포트를 --port-file 경로에 기록한다.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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

# 403이지만 정상 본문인 케이스 — 상태 코드 단독 판정 금지의 반례
FORBIDDEN_BUT_REAL = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>정상 본문 (403)</title></head>
<body><article><p>{BODY_MARKER}</p><p>{_LOREM}</p></article></body></html>"""

ROBOTS = "User-agent: *\nDisallow: /norobots/\n"


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

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        path = self.path.split("?", 1)[0]

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
