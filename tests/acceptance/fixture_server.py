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
