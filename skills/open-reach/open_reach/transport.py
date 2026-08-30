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


_REQUIRED_CURL_OPTS = ("RESOLVE", "PROXY", "NOPROXY")


def _connection_options(entry: str | None) -> dict:
    """연결 경로를 우리가 정하는 핸들 옵션 묶음 — 능력 검사와 실제 요청이 같은 것을 쓴다.

    두 벌로 두면 검사에 통과한 조합과 요청이 실제로 거는 조합이 갈라진다. 실제로
    `trust_env=False` 만 보고 통과시켰다가, 그 인자가 설치본에서 **저장만 되고
    프록시 적용에 쓰이지 않아** 환경 프록시가 그대로 살아 있던 적이 있다.

    프록시를 반드시 핸들에서 끄는 이유: 프록시를 타면 대상 이름을 **프록시가**
    해석하므로 `CURLOPT_RESOLVE` 로 고정한 주소가 적용되지 않고, `primary_ip` 는
    프록시의 주소라 사후 확인마저 대상이 아닌 것을 확인한다 — SSRF 방어 두 겹이
    동시에 무너진다. libcurl 은 `CURLOPT_PROXY` 가 없으면 스스로 `http_proxy`/
    `ALL_PROXY` 환경변수를 읽으므로, 빈 문자열을 **명시적으로** 넣어 그 기본 동작을
    덮는다(`NOPROXY: "*"` 는 프록시가 다른 경로로 설정된 경우까지 덮는 이중 안전장치).
    """
    from curl_cffi import CurlOpt

    options = {CurlOpt.PROXY: "", CurlOpt.NOPROXY: "*"}
    if entry is not None:
        options[CurlOpt.RESOLVE] = [entry]
    return options


def _probe_impersonation() -> str | None:
    """임퍼소네이션 경로를 **실제로 쓸 수 있는지** 본다. None = 가능, 문자열 = 불가 사유.

    설치 여부만 보면 안 된다. 이 경로는 `CURLOPT_RESOLVE` 로 이름 해석을 고정하고
    환경 프록시를 끊는 것을 전제로 성립하는데(`_send_curl_cffi` 참조), 그 수단이 없는
    curl_cffi 를 만나면 매 요청이 fail-closed 로 떨어진다. 그때 호출자가 보는 것은
    `policy_blocked` 뿐이라 "상대가 막았다"와 구분되지 않는다 — 능력 부족이 정책
    판정으로 위장되고, 임퍼소네이션 돌파율은 조용히 0 이 된다.
    그러므로 **쓸 수 없으면 애초에 켜지 않는다**: 저하 모드로 내려가 표준 클라이언트로
    동작하고 stderr 에 이유를 남긴다. curl_cffi 가 아예 없을 때와 같은 상태다.
    """
    try:
        from curl_cffi import CurlOpt
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return "curl_cffi 가 설치되어 있지 않다 (pip install curl_cffi)"

    missing = [name for name in _REQUIRED_CURL_OPTS if not hasattr(CurlOpt, name)]
    if missing:
        return (
            f"설치된 curl_cffi 에 {', '.join('CURLOPT_' + m for m in missing)} 가 없어 "
            "연결 경로(이름 해석·프록시)를 고정할 수 없다"
        )

    # 옵션들을 **함께** 받는지 실제로 만들어 본다 — 시그니처는 **kwargs 로 열려 있어
    # 이름만 보고는 알 수 없다. 네트워크는 타지 않는다.
    try:
        probe = cffi_requests.Session(curl_options=_connection_options(None))
    except TypeError as exc:
        return (
            f"설치된 curl_cffi 가 연결 경로 통제(curl_options)를 지원하지 않는다 ({exc})"
        )
    probe.close()
    return None


_UNPROBED = object()
_impersonation_block: str | None | object = _UNPROBED
# 판정과 경고는 프로세스당 한 번이다. `fetch` 를 스레드로 나눠 돌리면 두 스레드가
# 동시에 미판정 상태를 보고 각자 프로브를 돌리거나 경고를 두 번 낼 수 있다 —
# 프로브는 부작용이 없어 치명적이진 않지만, "한 번만"이라는 계약은 지켜야 한다.
_probe_lock = threading.Lock()


def impersonation_reason() -> str | None:
    """저하 사유(없으면 None). 프로세스당 한 번만 판정한다."""
    global _impersonation_block
    if _impersonation_block is not _UNPROBED:
        return _impersonation_block  # type: ignore[return-value]
    with _probe_lock:
        if _impersonation_block is _UNPROBED:
            _impersonation_block = _probe_impersonation()
        return _impersonation_block  # type: ignore[return-value]


def impersonation_available() -> bool:
    return impersonation_reason() is None


def warn_if_degraded() -> None:
    """임퍼소네이션 능력이 없으면 한 번만 알린다 — 조용한 능력 저하를 만들지 않는다."""
    global _warned_no_curl_cffi
    reason = impersonation_reason()
    if reason is None:
        return
    with _probe_lock:
        if _warned_no_curl_cffi:
            return
        _warned_no_curl_cffi = True
    sys.stderr.write(
        f"[open-reach] TLS 임퍼소네이션 없이 동작한다 — {reason}. 돌파율이 낮게 측정된다.\n"
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


def resolve_entry(host: str, port: int, addresses: list[str]) -> str:
    """libcurl `CURLOPT_RESOLVE` 한 줄 — `host:port:addr1,addr2`.

    IPv6 주소는 대괄호로 감싼다. 쉼표로 여러 주소를 이어야 하는 형식이라
    감싸지 않으면 주소 안의 콜론이 구분자와 섞여 항목 자체가 무효가 된다.
    검증한 주소를 **전부** 넘긴다 — 하나만 고정하면 dual-stack 호스트에서 첫 주소가
    불통일 때 폴백이 사라져, 보안을 위해 도입한 고정이 가용성을 깎는다.
    """
    literals = []
    for address in addresses:
        literals.append(f"[{address}]" if ":" in address else address)
    return f"{host}:{port}:{','.join(literals)}"


def _send_curl_cffi(
    url: str, timeout: float, headers: dict[str, str], impersonate: str
) -> tuple[int, dict[str, str], bytes, bool]:
    """libcurl 경로. 이름 해석을 **정책이 검증한 주소로 고정**한 뒤 요청한다.

    libcurl 은 응답 헤더를 받은 뒤에야 `primary_ip` 를 알려준다 — 그때 확인하는 것은
    이미 요청이 상대에게 도달한 뒤다. 사설 서버에 GET 이 한 번 닿는 것 자체가 SSRF 이므로,
    검증을 요청 뒤로 미루지 않고 **연결할 주소를 우리가 고정한다**.
    고정할 수단이 없는 버전이라면 이 경로는 통제 불가이므로 쓰지 않는다 (fail-closed).

    환경 프록시(`http_proxy` 등)도 같은 이유로 신뢰하지 않는다. 프록시를 타면 대상
    이름을 **프록시가** 해석하므로 우리가 고정한 주소는 적용되지 않고, `primary_ip` 는
    프록시의 주소라서 사후 확인마저 대상이 아닌 것을 확인하게 된다 — 검증 두 겹이
    동시에 무력화된다. stdlib 경로는 `http.client` 를 직접 써서 애초에 프록시를 타지
    않으므로, 이 경로만 명시적으로 막으면 두 경로의 동작이 같아진다.
    """
    from curl_cffi import requests as cffi_requests  # 지연 임포트 — 없어도 동작해야 한다

    from . import policy  # 순환 임포트 회피 (전송 -> 정책)

    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    port = parts.port or (443 if parts.scheme == "https" else 80)
    entry = resolve_entry(host, port, policy.resolved_targets(url))

    try:
        # 고정과 프록시 차단은 요청 인자가 아니라 **핸들 옵션**이다. 세션을 요청마다
        # 새로 만들기 때문에 이 항목은 이 URL 하나에만 적용되고, 세션이 닫히면 사라진다.
        session = cffi_requests.Session(curl_options=_connection_options(entry))
    except TypeError as exc:
        # `impersonation_available()` 가 앞서 걸러내므로 여기까지 오면 설치 상태가
        # 도중에 바뀐 것이다. 통제할 수 없는 연결은 만들지 않는다 (fail-closed).
        raise PolicyBlocked(
            "private_range",
            "설치된 curl_cffi 로 연결 경로(이름 해석 고정·환경 프록시 차단)를 "
            f"통제할 수 없다 — 이 경로를 쓰지 않는다 ({exc})",
        ) from exc

    resp = None
    try:
        resp = session.get(
            url,
            headers=headers,
            timeout=timeout,
            impersonate=impersonate,
            allow_redirects=False,
            stream=True,
        )

        got = _merge_headers(
            getattr(resp.headers, "multi_items", resp.headers.items)()
        )
        # 고정한 주소로 실제로 붙었는지 확인한다 — 고정이 무시됐다면 여기서 걸린다
        _verify_peer(url, getattr(resp, "primary_ip", None))
        body, truncated = _drain_capped(resp.iter_content(chunk_size=_CHUNK_BYTES))
        return resp.status_code, got, body, truncated
    finally:
        for closable in (resp, session):
            close = getattr(closable, "close", None)
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
    if impersonate and impersonation_available():
        # 임퍼소네이션은 TLS/HTTP2 지문을 **그 브라우저의 것**으로 맞추는 일이다. 그런데
        # 여기서 우리 UA(Chrome 131 Windows)를 덮어쓰면 지문은 Safari 인데 UA 는 Chrome
        # 이라고 말하는 응답이 나간다 — 그 **불일치 자체가 봇 신호**다.
        #
        # 실측(bench/evidence/header-mismatch-probe.json): 같은 URL·같은 임퍼소네이션에서
        # 헤더 조합만 바꿨을 때
        #   bloomberg.com/technology : UA 없음 → 200 (2,279,185B) / UA 만 추가 → 403
        #   w3.org/TR/WCAG21/        : UA 없음 → 200 (476,496B)   / UA 만 추가 → 403
        # 나머지 세 헤더(Accept·Accept-Language·Connection)를 그대로 둔 채 UA 만 빼도
        # 200 이 나왔으므로 원인은 UA 하나로 특정된다. stackoverflow 는 어느 조합에서도
        # 403 이라 이 수정과 무관하다 — 즉 "무조건 좋아지는 조작"이 아니라 우리가 만든
        # 불일치를 없애는 것이다.
        del headers["User-Agent"]
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
