"""환경 프록시가 실제로 차단되는지 검증한다 (코드리뷰 R10 CRITICAL).

프록시를 타면 대상 이름을 **프록시가** 해석하므로 `CURLOPT_RESOLVE` 로 고정한 주소가
적용되지 않고, `primary_ip` 는 프록시의 주소라 사후 확인마저 대상이 아닌 것을 확인한다.
SSRF 방어 두 겹이 동시에 무너지는 자리다.

설치본 curl_cffi 는 `trust_env=False` 를 속성으로 저장만 하고 프록시 적용에 쓰지
않는다 — 그래서 인자 하나만 믿으면 안 되고, 실제로 프록시가 요청을 받는지 본다.
"""

import contextlib
import os
import pathlib
import socket
import sys
import threading

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import transport  # noqa: E402

_PROXY_ENV = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy")


class _CountingListener:
    """연결 수만 세는 가짜 프록시. 받은 것은 즉시 닫는다."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.connections = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        self.sock.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            self.connections += 1
            with contextlib.suppress(OSError):
                conn.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        with contextlib.suppress(OSError):
            self.sock.close()


def _free_loopback_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.skipif(
    not transport.impersonation_available(),
    reason=f"임퍼소네이션 경로 없음: {transport.impersonation_reason()}",
)
def test_env_proxy_is_never_used(monkeypatch):
    proxy = _CountingListener()
    # 아무도 듣지 않는 루프백 포트를 대상으로 삼는다. 프록시가 살아 있다면 curl 은
    # 대상 대신 **프록시에** 붙으므로, 요청 성패와 무관하게 연결 수로 판정할 수 있다.
    dead_port = _free_loopback_port()
    target = f"http://127.0.0.1:{dead_port}/"

    try:
        for name in _PROXY_ENV:
            monkeypatch.setenv(name, f"http://127.0.0.1:{proxy.port}")
        # 루프백은 기본 차단이므로, 픽스처 오리진 예외로 이 대상 1개만 연다
        monkeypatch.setenv("OPENREACH_FIXTURE_BASE", f"http://127.0.0.1:{dead_port}")

        with contextlib.suppress(Exception):
            transport._send_curl_cffi(
                target, headers={}, timeout=5.0, impersonate="chrome"
            )
    finally:
        proxy.close()

    assert proxy.connections == 0, (
        f"환경 프록시가 요청을 {proxy.connections}건 받았다 — "
        "CURLOPT_RESOLVE 고정과 primary_ip 확인이 동시에 무력화된다"
    )


def test_connection_options_pin_and_disable_proxy():
    """능력 검사와 실제 요청이 같은 옵션 묶음을 쓴다 — 두 벌로 갈라지지 않게."""
    if not transport.impersonation_available():
        pytest.skip(transport.impersonation_reason() or "")
    from curl_cffi import CurlOpt

    options = transport._connection_options("example.com:443:93.184.216.34")
    assert options[CurlOpt.PROXY] == ""
    assert options[CurlOpt.NOPROXY] == "*"
    assert options[CurlOpt.RESOLVE] == ["example.com:443:93.184.216.34"]
