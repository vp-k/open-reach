"""브라우저 티어 (T2) — JS 챌린지 전용, A8 준수.

curl_cffi(T1)가 JS 를 실행하지 못해 통과하지 못하는 챌린지(예: aws_waf·kasada·f5 의
클라이언트 사이드 챌린지)에서만 오른다. HTML 을 실제로 렌더해 챌린지 스크립트가
스스로 풀리기를 기다린 뒤 공개 본문을 취득한다.

A8 준수 설계 (ADR-006 · policy-boundaries §4 — 이 넷 중 하나라도 하면 '회피 도구'다):
- A8-1 신원 비지속: 매 호출 tempfile.mkdtemp 임시 프로필을 쓰고 LIFO 정리로 정상·예외·
  시그널 모두에서 삭제한다. 쿠키·스토리지·프로필을 실행 간 재사용하지 않는다.
- A8-2 행동 시뮬 없음: page.goto 후 챌린지 JS 가 실행될 시간을 '대기'할 뿐,
  마우스 이동·타이핑·스크롤로 사람을 흉내내지 않는다.
- A8-3 자격증명·쿠키 미취급: 쿠키/세션 파일 옵션이 없다. 임시 프로필의 쿠키는
  프로필과 함께 소멸한다.
- A8-4 탐지 회피 지표 없음: 성공은 '공개 본문 취득'으로만 판정한다. 탐지 회피도를
  성공 지표로 두지 않는다(bench 출력에도 그런 필드가 없다).

patchright 는 navigator.webdriver 등 자동화 아티팩트를 '제거'할 뿐 지문을 '위조'하지
않는다 — ADR-006 이 명시적으로 허용한 범위다.

지연 설치(SC-7): patchright 는 T1 경로에서 import 되지 않는다. import 는 함수 안에서만
일어난다. 미설치 시 browser_available() 가 (False, 사유)를 돌려주고 fetcher 는 이를
browser_disabled 정책 사유로 강등한다 — 없는 돌파를 지어내지 않는다(NG-10).
"""

from __future__ import annotations

import atexit
import os
import shutil
import signal
import sys
import tempfile
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# 챌린지 스크립트가 스스로 풀릴 여유 (사람 행동 흉내가 아니라 순수 대기다).
_CHALLENGE_SETTLE_MS = 4000
_PROFILE_PREFIX = "open-reach-bt-"


@dataclass(frozen=True)
class BrowserOutcome:
    """브라우저 티어의 취득 결과. 내용 판정(성공/차단)은 호출부(fetcher)가 한다."""

    ok: bool  # 브라우저가 응답 본문을 받아냈는가 (네트워크·기동 성공 여부)
    status: int
    html: str
    final_url: str
    headers: dict = field(default_factory=dict)
    elapsed_ms: int = 0
    error: str | None = None  # 실패 시 SPEC 실패 사유 문자열, 성공 시 None


class _Cleanup:
    """임시 프로필 삭제를 정상 종료·예외·시그널 전부에서 보장하는 LIFO 정리 스택.

    정상 경로는 finally 에서 즉시 정리하고 스택에서 뺀다 — 스택에 남는 항목은
    '실행 중 크래시/시그널로 중단된' 프로필뿐이며, atexit·SIGTERM 훅이 그것을 회수한다.
    SIGINT(Ctrl-C)은 기본적으로 KeyboardInterrupt 로 finally 를 태우므로 별도 처리가
    필요 없다.
    """

    def __init__(self) -> None:
        self._stack: list = []
        self._installed = False

    def push(self, fn) -> None:
        self._stack.append(fn)

    def discard(self, fn) -> None:
        try:
            self._stack.remove(fn)
        except ValueError:
            pass

    def run(self) -> None:
        while self._stack:
            fn = self._stack.pop()
            try:
                fn()
            except Exception:
                pass

    def install(self) -> None:
        if self._installed:
            return
        self._installed = True
        atexit.register(self.run)
        # SIGTERM 은 기본적으로 finally 없이 종료하므로 훅을 걸어 프로필을 회수한다.
        # 메인 스레드가 아니면 signal.signal 이 실패한다 — atexit 백스톱으로 충분하다.
        try:
            prev = signal.getsignal(signal.SIGTERM)

            def _handler(signum, frame, _prev=prev):
                self.run()
                # 정리만 하고 반환하면 우리가 기본 동작(SIG_DFL=종료)을 덮어썼으므로
                # 프로세스가 SIGTERM 을 삼키고 계속 산다 — 챌린지가 좀비로 남는다.
                # 정리 후에는 원래 하기로 돼 있던 일을 반드시 수행한다.
                if _prev == signal.SIG_IGN:
                    return  # 원래 무시하기로 한 신호 — 그 뜻을 존중
                if callable(_prev) and _prev not in (signal.SIG_DFL, signal.SIG_IGN):
                    _prev(signum, frame)
                    return
                # 기본 동작은 종료였다 — 기본 핸들러를 복구하고 신호를 재전달해 실제로 죽는다.
                signal.signal(signum, signal.SIG_DFL)
                try:
                    os.kill(os.getpid(), signum)
                except (OSError, ValueError, AttributeError):
                    raise SystemExit(128 + signum)

            signal.signal(signal.SIGTERM, _handler)
        except (ValueError, OSError):
            pass


_CLEANUP = _Cleanup()


def browser_available() -> tuple[bool, str]:
    """(설치됨, 사유). T1 경로 비용을 늘리지 않도록 import 는 여기서만 한다."""
    try:
        from patchright.sync_api import sync_playwright  # noqa: F401
    except Exception as exc:  # ImportError 외에 부분 설치 손상도 강등 대상
        return False, f"patchright import 실패 ({exc.__class__.__name__})"
    return True, ""


def _ssrf_allow(url: str) -> bool:
    """이 요청 URL 을 브라우저 egress 로 허용할지 (NG-11 프리엠티브 판정).

    http/https 가 아니면(data:·blob:·about:) 호스트로의 네트워크 egress 가 없어
    무조건 허용한다. 그 외에는 정책의 사설 대역·메타데이터 검사를 그대로 쓴다.
    DNS 실패는 fail-closed(코드베이스 전역 관례), 가드 자체 오류만 통과시킨다
    (사후 final_url 재검사가 2차 방어로 남는다).
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return True
    from . import policy as _policy  # 지연 임포트 — T1 경로 비용/순환을 피한다

    try:
        return _policy.check_url(url).allowed
    except _policy.UnresolvableHost:
        return False
    except Exception:
        return True


def browser_fetch(url: str, *, timeout_s: float) -> BrowserOutcome:
    """임시 프로필로 headless Chromium 을 띄워 url 을 렌더하고 본문을 돌려준다.

    성공/차단 판정은 하지 않는다 — status·html·final_url 을 그대로 넘겨 fetcher 가
    HTTP 티어와 동일한 detect.classify 로 판정하게 한다(판정 일관성).
    """
    from patchright.sync_api import Error as PWError, sync_playwright

    _CLEANUP.install()
    nav_ms = int(max(1.0, timeout_s) * 1000)
    started = time.monotonic()

    # NG-11 프리엠티브 SSRF 가드: 브라우저가 리디렉션·서브리소스로 사설 대역에
    # '연결하기 전에' 각 요청을 정책으로 검사해 사설이면 차단한다. 사후 final_url
    # 재검사는 최종 도착지만 보므로 공개→사설→공개 리디렉션의 중간 홉을 놓친다
    # (codex 리뷰 Critical). route 가드는 그 홉의 연결 자체를 막는다. 이는 탐지
    # 회피가 아니라 경계 강제이므로 A8 를 침해하지 않는다.
    _ssrf_cache: dict = {}

    def _ssrf_guard(route) -> None:
        try:
            parts = urlsplit(route.request.url)
            # 캐시 키는 오리진(scheme+host+port)이다. host 만으로 캐시하면 같은 host 의
            # 다른 포트(127.0.0.1:80 허용 → :6379 redis)가 캐시 히트로 뚫린다.
            origin = f"{parts.scheme}://{parts.hostname}:{parts.port or ''}"
            ok = _ssrf_cache.get(origin)
            if ok is None:
                ok = _ssrf_allow(route.request.url)
                _ssrf_cache[origin] = ok
            (route.continue_ if ok else route.abort)()
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass
    profile = None
    _remove = None
    try:
        profile = tempfile.mkdtemp(prefix=_PROFILE_PREFIX)

        def _remove() -> None:
            shutil.rmtree(profile, ignore_errors=True)

        _CLEANUP.push(_remove)
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                profile,
                headless=True,
                # A8-2/A8-3: 지문·프록시·행동·저장상태 옵션을 일절 주지 않는다.
            )
            try:
                # 호출자 deadline 을 context 전역에 걸어 goto 이후 content()·close() 등
                # 모든 작업이 무기한 블로킹되지 않게 한다(codex 리뷰 High).
                context.set_default_timeout(nav_ms)
                context.set_default_navigation_timeout(nav_ms)
                context.route("**/*", _ssrf_guard)  # NG-11 프리엠티브 SSRF 차단
                page = context.pages[0] if context.pages else context.new_page()
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=nav_ms)
                except PWError:
                    return BrowserOutcome(
                        ok=False, status=0, html="", final_url=url,
                        elapsed_ms=int((time.monotonic() - started) * 1000),
                        error="network",
                    )
                status = response.status if response is not None else 0
                headers = dict(response.headers) if response is not None else {}
                # 챌린지 JS 가 스스로 풀리도록 네트워크 정착을 기다린다(대기이지 상호작용이 아니다).
                # 대기 상한은 남은 예산으로 스케일한다 — timeout_s 가 작으면 고정 4초를
                # 통째로 더하지 않는다(codex 리뷰 High). 최소 500ms 는 챌린지 여유로 남긴다.
                remaining = nav_ms - int((time.monotonic() - started) * 1000)
                settle = max(500, min(_CHALLENGE_SETTLE_MS, remaining))
                try:
                    page.wait_for_load_state("networkidle", timeout=settle)
                except PWError:
                    pass
                html = page.content()
                final_url = page.url or url
                return BrowserOutcome(
                    ok=True, status=status, html=html, final_url=final_url,
                    headers=headers,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                    error=None,
                )
            finally:
                context.close()
    except (KeyboardInterrupt, SystemExit):
        raise
    except PWError:
        return BrowserOutcome(
            ok=False, status=0, html="", final_url=url,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error="network",
        )
    except Exception as exc:
        # 브라우저 티어는 폴백이다 — 어떤 예기치 못한 오류(context.close 실패·
        # mkdtemp OSError·patchright 내부 오류)도 크래시로 새지 않고 강등한다.
        # Phase 0 run() 과 동일한 격리 원칙. 원 사유는 fetcher 가 last_reason 으로 유지한다.
        sys.stderr.write(
            f"[open-reach] browser_tier: 예기치 못한 오류 무시 ({exc.__class__.__name__})\n"
        )
        return BrowserOutcome(
            ok=False, status=0, html="", final_url=url,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error="network",
        )
    finally:
        if _remove is not None:
            _remove()
            _CLEANUP.discard(_remove)
