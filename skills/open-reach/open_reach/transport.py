"""HTTP 전송 계층 — 리디렉션을 직접 통제하고 매 홉마다 정책을 재검사한다.

`curl_cffi` 가 설치되어 있으면 TLS 임퍼소네이션 경로를 쓰고, 없으면 표준 라이브러리로
동작한다. 없을 때 조용히 넘어가지 않고 stderr 에 능력 저하를 명시한다 (NG-10).

세 가지를 전송 계층에서 강제한다:
1. 연결된 **실제** 주소를 재검증한다 — 사전 DNS 조회와 커널이 붙은 주소가 다를 수 있다.
2. 본문은 상한(`MAX_BODY_BYTES`)까지만 읽는다 — 무제한 응답에 메모리를 내주지 않는다.
3. 호스트별 동시성 1 + 최소 간격 1.0초를 락으로 강제한다 (NG-5/NG-6).
"""

from __future__ import annotations

import http.client
import socket
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator
from urllib.parse import urljoin, urlsplit

MAX_REDIRECTS = 5
MIN_HOST_INTERVAL_S = 1.0
MAX_BODY_BYTES = 8 * 1024 * 1024
_CHUNK_BYTES = 64 * 1024

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "close",
}

_gate_lock = threading.Lock()
_host_gates: dict[str, threading.Lock] = {}
_last_request_at: dict[str, float] = {}
_warned_no_curl_cffi = False


class NetworkError(Exception):
    """DNS·TLS·타임아웃 — 응답을 받지 못했다."""


class PolicyBlocked(Exception):
    """정책이 차단했다 (리디렉션 홉 포함)."""

    def __init__(self, rule: str, detail: str) -> None:
        super().__init__(detail)
        self.rule = rule
        self.detail = detail


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes
    final_url: str
    elapsed_ms: int
    truncated: bool = False

    def text(self) -> str:
        charset = "utf-8"
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            charset = ctype.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def impersonation_available() -> bool:
    try:
        import curl_cffi  # noqa: F401
    except ImportError:
        return False
    return True


def warn_if_degraded() -> None:
    """임퍼소네이션 능력이 없으면 한 번만 알린다 — 조용한 능력 저하를 만들지 않는다."""
    global _warned_no_curl_cffi
    if _warned_no_curl_cffi or impersonation_available():
        return
    _warned_no_curl_cffi = True
    sys.stderr.write(
        "[open-reach] curl_cffi 가 없어 TLS 임퍼소네이션 없이 동작한다. "
        "돌파율이 낮게 측정된다 (pip install curl_cffi).\n"
    )


# ── 호스트 게이트 ────────────────────────────────────────────────────────


def _gate_for(host: str) -> threading.Lock:
    with _gate_lock:
        gate = _host_gates.get(host)
        if gate is None:
            gate = threading.Lock()
            _host_gates[host] = gate
        return gate


@contextmanager
def host_gate(host: str) -> Iterator[None]:
    """호스트별 동시성 1 + 최소 간격 1.0초를 함께 강제한다.

    간격 계산과 갱신을 락 안에서 하지 않으면 두 요청이 같은 `last` 를 읽고
    동시에 나가버린다 — 계약이 관측 가능한 방식으로 깨진다.
    """
    gate = _gate_for(host)
    gate.acquire()
    try:
        last = _last_request_at.get(host)
        if last is not None:
            wait = MIN_HOST_INTERVAL_S - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        yield
    finally:
        _last_request_at[host] = time.monotonic()
        gate.release()


# ── 주소 재검증 (DNS rebinding 차단) ─────────────────────────────────────


def _peer_address(sock: object) -> str | None:
    if sock is None:
        return None
    getpeername = getattr(sock, "getpeername", None)
    if getpeername is None:
        return None
    try:
        peer = getpeername()
    except OSError:
        return None
    if isinstance(peer, tuple) and peer and isinstance(peer[0], str):
        return peer[0].split("%", 1)[0]
    return None


def _verify_peer(url: str, address: str | None) -> None:
    """실제 연결된 주소를 정책에 다시 물어본다. 판정 불가는 차단이다."""
    from . import policy  # 순환 임포트 회피 (전송 -> 정책)

    if not address:
        raise PolicyBlocked(
            "private_range", "연결된 주소를 확인할 수 없다 — 판정 불가는 차단이다"
        )
    verdict = policy.check_peer(url, address)
    if not verdict.allowed:
        raise PolicyBlocked(verdict.rule or "private_range", verdict.detail)


# ── 본문 읽기 (상한) ─────────────────────────────────────────────────────


def _read_capped(reader: Callable[[int], bytes]) -> tuple[bytes, bool]:
    """`MAX_BODY_BYTES` 까지만 읽는다. 상한을 넘으면 잘라내고 표시한다."""
    chunks: list[bytes] = []
    size = 0
    while size <= MAX_BODY_BYTES:
        chunk = reader(_CHUNK_BYTES)
        if not chunk:
            return b"".join(chunks), False
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)[:MAX_BODY_BYTES], True


def _drain_capped(stream: Iterator[bytes]) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    size = 0
    for chunk in stream:
        if not chunk:
            continue
        chunks.append(chunk)
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            return b"".join(chunks)[:MAX_BODY_BYTES], True
    return b"".join(chunks), False


# ── 전송 ─────────────────────────────────────────────────────────────────


def _merge_headers(pairs) -> dict[str, str]:
    """중복 헤더를 버리지 않고 합친다 — Set-Cookie 는 거의 항상 여러 줄이고,
    마지막 하나만 남기면 쿠키 기반 WAF 지문이 통째로 사라진다."""
    merged: dict[str, str] = {}
    for key, value in pairs:
        low = str(key).lower()
        if low in merged:
            merged[low] = f"{merged[low]}, {value}"
        else:
            merged[low] = str(value)
    return merged


def _send_stdlib(
    url: str, timeout: float, headers: dict[str, str]
) -> tuple[int, dict[str, str], bytes, bool]:
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query

    if parts.scheme == "https":
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(host, port, timeout=timeout)
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        # 요청을 보내기 **전에** 붙은 주소를 검증한다 — 재조회 결과가 바뀌었어도 여기서 걸린다
        conn.connect()
        _verify_peer(url, _peer_address(conn.sock))
        conn.request("GET", target, headers=headers)
        resp = conn.getresponse()
        body, truncated = _read_capped(resp.read)
        got = _merge_headers(resp.getheaders())
        return resp.status, got, body, truncated
    finally:
        conn.close()


def _send_curl_cffi(
    url: str, timeout: float, headers: dict[str, str], impersonate: str
) -> tuple[int, dict[str, str], bytes, bool]:
    """libcurl 경로. 이름 해석을 **정책이 검증한 주소로 고정**한 뒤 요청한다.

    libcurl 은 응답 헤더를 받은 뒤에야 `primary_ip` 를 알려준다 — 그때 확인하는 것은
    이미 요청이 상대에게 도달한 뒤다. 사설 서버에 GET 이 한 번 닿는 것 자체가 SSRF 이므로,
    검증을 요청 뒤로 미루지 않고 **연결할 주소를 우리가 고정한다**.
    고정할 수단이 없는 버전이라면 이 경로는 통제 불가이므로 쓰지 않는다 (fail-closed).
    """
    from curl_cffi import requests as cffi_requests  # 지연 임포트 — 없어도 동작해야 한다

    from . import policy  # 순환 임포트 회피 (전송 -> 정책)

    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    port = parts.port or (443 if parts.scheme == "https" else 80)
    address = policy.resolved_targets(url)[0]

    try:
        resp = cffi_requests.get(
            url,
            headers=headers,
            timeout=timeout,
            impersonate=impersonate,
            allow_redirects=False,
            stream=True,
            resolve=[f"{host}:{port}:{address}"],
        )
    except TypeError as exc:
        raise PolicyBlocked(
            "private_range",
            "설치된 curl_cffi 가 이름 해석 고정(resolve)을 지원하지 않아 "
            f"연결 주소를 통제할 수 없다 — 이 경로를 쓰지 않는다 ({exc})",
        ) from exc

    try:
        got = _merge_headers(
            getattr(resp.headers, "multi_items", resp.headers.items)()
        )
        # 고정한 주소로 실제로 붙었는지 확인한다 — 고정이 무시됐다면 여기서 걸린다
        _verify_peer(url, getattr(resp, "primary_ip", None))
        body, truncated = _drain_capped(resp.iter_content(chunk_size=_CHUNK_BYTES))
        return resp.status_code, got, body, truncated
    finally:
        close = getattr(resp, "close", None)
        if close is not None:
            close()


def request(
    url: str,
    *,
    timeout: float,
    impersonate: str | None = None,
    referer: str | None = None,
    hop_check: Callable[[str], None] | None = None,
) -> Response:
    """단건 GET. 리디렉션은 직접 따라가며 매 홉마다 `hop_check` 를 호출한다.

    `hop_check` 는 차단 시 PolicyBlocked 를 던져야 한다.
    `elapsed_ms` 에는 의도적 페이싱 대기를 넣지 않는다 — 지연 지표가 부풀려지면
    측정으로 쓸 수 없다.
    """
    headers = dict(DEFAULT_HEADERS)
    if referer:
        headers["Referer"] = referer

    net_ms = 0
    current = url
    for hop in range(MAX_REDIRECTS + 1):
        parts = urlsplit(current)
        host = (parts.hostname or "").lower()
        with host_gate(host):
            started = time.monotonic()
            try:
                if impersonate and impersonation_available():
                    status, got, body, truncated = _send_curl_cffi(
                        current, timeout, headers, impersonate
                    )
                else:
                    status, got, body, truncated = _send_stdlib(current, timeout, headers)
            except PolicyBlocked:
                raise
            except (socket.gaierror, socket.timeout, TimeoutError) as exc:
                raise NetworkError(f"{type(exc).__name__}: {exc}") from exc
            except (OSError, http.client.HTTPException) as exc:
                raise NetworkError(f"{type(exc).__name__}: {exc}") from exc
            except Exception as exc:  # curl_cffi 예외군은 클래스 계층이 다르다
                raise NetworkError(f"{type(exc).__name__}: {exc}") from exc
            net_ms += int((time.monotonic() - started) * 1000)

        if status in (301, 302, 303, 307, 308) and "location" in got:
            if hop >= MAX_REDIRECTS:
                raise PolicyBlocked("redirect_hop", f"리디렉션 홉이 {MAX_REDIRECTS} 를 초과했다")
            nxt = urljoin(current, got["location"])
            if hop_check is not None:
                hop_check(nxt)
            current = nxt
            continue

        return Response(
            status=status,
            headers=got,
            body=body,
            final_url=current,
            elapsed_ms=net_ms,
            truncated=truncated,
        )

    raise PolicyBlocked("redirect_hop", "리디렉션이 끝나지 않았다")
