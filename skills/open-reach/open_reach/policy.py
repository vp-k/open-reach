"""정책 가드 — SSRF 차단(fail-closed), 스킴 allowlist, robots.txt.

판정 불가는 차단이다. 유일한 예외는 `OPENREACH_FIXTURE_BASE` 가 지정하는
테스트 픽스처 오리진 하나이며, 오리진이 완전히 일치할 때만 적용된다
(SPEC Constraints 보안 절).
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from urllib.parse import urlsplit

from .models import PolicyVerdict

MAX_URL_LENGTH = 2048
ALLOWED_SCHEMES = ("http", "https")

# 클라우드 메타데이터 — 픽스처 예외보다 항상 우선한다
METADATA_HOSTS = frozenset(
    {
        "169.254.169.254",
        "metadata.google.internal",
        "100.100.100.200",
        "fd00:ec2::254",
    }
)

_BLOCKED_V4 = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "224.0.0.0/4",
        "240.0.0.0/4",
    )
)
_BLOCKED_V6 = tuple(
    ipaddress.ip_network(cidr)
    for cidr in ("::/128", "::1/128", "fc00::/7", "fe80::/10", "ff00::/8")
)


class UnresolvableHost(Exception):
    """DNS 조회 자체가 실패했다 — 검사할 주소가 없으므로 정책 위반이 아니다."""


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def origin_of(url: str) -> str | None:
    """`scheme://host:port` 로 정규화한다. 기본 포트는 명시 포트와 같은 것으로 본다."""
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES or not parts.hostname:
        return None
    port = parts.port or _default_port(parts.scheme)
    return f"{parts.scheme}://{parts.hostname.lower()}:{port}"


def fixture_origin() -> str | None:
    """인수 테스트 전용 예외 오리진. 변수가 없으면 예외는 존재하지 않는다."""
    raw = os.environ.get("OPENREACH_FIXTURE_BASE", "").strip()
    return origin_of(raw) if raw else None


def _resolve(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnresolvableHost(f"DNS 조회 실패: {host} ({exc})") from exc
    except OSError as exc:
        raise UnresolvableHost(f"DNS 조회 실패: {host} ({exc})") from exc
    addresses = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr and isinstance(sockaddr[0], str):
            addresses.append(sockaddr[0].split("%", 1)[0])
    if not addresses:
        raise UnresolvableHost(f"DNS 가 주소를 반환하지 않았다: {host}")
    return addresses


def _blocked_band(address: str) -> str | None:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        # 주소를 해석할 수 없다 = 판정 불가 = 차단
        return f"주소 판정 불가: {address}"
    networks = _BLOCKED_V4 if ip.version == 4 else _BLOCKED_V6
    for network in networks:
        if ip in network:
            return f"{address} 는 차단 대역 {network} 에 속한다"
    if ip.is_multicast or ip.is_unspecified:
        return f"{address} 는 사용할 수 없는 주소다"
    return None


def check_url(url: str) -> PolicyVerdict:
    """URL 1건을 검사한다. 네트워크 요청은 보내지 않는다 (DNS 조회만).

    DNS 조회 자체가 실패하면 UnresolvableHost 를 던진다 — 호출자가 `network` 로 분류한다.
    """
    if len(url) > MAX_URL_LENGTH:
        return PolicyVerdict(False, "scheme", f"URL 길이가 {MAX_URL_LENGTH} 를 초과했다")

    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        return PolicyVerdict(False, "scheme", f"허용되지 않은 스킴: {parts.scheme or '(없음)'}")
    host = (parts.hostname or "").lower()
    if not host:
        return PolicyVerdict(False, "scheme", "호스트가 없는 URL")

    # 메타데이터 주소는 어떤 예외보다 우선해 차단한다
    if host in METADATA_HOSTS:
        return PolicyVerdict(False, "private_range", f"클라우드 메타데이터 주소: {host}")

    port = parts.port or _default_port(parts.scheme)
    exempt = fixture_origin()
    target_origin = f"{parts.scheme}://{host}:{port}"
    if exempt is not None and target_origin == exempt:
        return PolicyVerdict(True, None, f"테스트 픽스처 오리진 예외: {target_origin}")

    for address in _resolve(host, port):
        if address in METADATA_HOSTS:
            return PolicyVerdict(False, "private_range", f"클라우드 메타데이터 주소: {address}")
        reason = _blocked_band(address)
        if reason is not None:
            return PolicyVerdict(False, "private_range", reason)

    return PolicyVerdict(True, None, f"{target_origin} 은 공개 대역이다")


def check_peer(url: str, address: str) -> PolicyVerdict:
    """실제로 연결된 주소를 재검증한다 — DNS rebinding(TOCTOU) 차단용.

    `check_url` 의 사전 조회와 커널이 실제로 연결한 주소는 다를 수 있다.
    이 함수는 소켓이 붙은 뒤 그 소켓의 상대 주소를 그대로 받아 다시 판정한다.
    픽스처 예외는 여기에도 같은 규칙(오리진 완전 일치)으로 적용된다.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host in METADATA_HOSTS or address in METADATA_HOSTS:
        return PolicyVerdict(False, "private_range", f"클라우드 메타데이터 주소: {address}")

    port = parts.port or _default_port(parts.scheme)
    exempt = fixture_origin()
    if exempt is not None and f"{parts.scheme}://{host}:{port}" == exempt:
        return PolicyVerdict(True, None, f"테스트 픽스처 오리진 예외: {address}")

    reason = _blocked_band(address)
    if reason is not None:
        return PolicyVerdict(False, "private_range", reason)
    return PolicyVerdict(True, None, f"연결 주소 {address} 는 공개 대역이다")


def hop_guard(next_url: str) -> None:
    """리디렉션 홉 재검사. 차단이면 transport.PolicyBlocked 를 던진다.

    transport.request 의 `hop_check` 로 넘기는 표준 가드다 — robots 조회를 포함해
    리디렉션을 따라가는 모든 경로가 같은 가드를 쓴다 (경로별 누락을 만들지 않는다).
    """
    from . import transport  # 순환 임포트 회피 (정책 -> 전송)

    try:
        verdict = check_url(next_url)
    except UnresolvableHost as exc:
        raise transport.NetworkError(str(exc)) from exc
    if not verdict.allowed:
        raise transport.PolicyBlocked("redirect_hop", verdict.detail)


# ── robots.txt ───────────────────────────────────────────────────────────

_robots_cache: dict[str, tuple[list[tuple[bool, str]], str]] = {}


def _parse_robots(text: str) -> list[tuple[bool, str]]:
    """`User-agent: *` 그룹의 (allow 여부, 경로 패턴) 규칙을 순서대로 모은다.

    연속한 `User-agent:` 줄은 **하나의 그룹**을 이룬다 — 규칙 줄이 한 번 나온 뒤에
    다시 `User-agent:` 가 나오면 그때부터 새 그룹이다. Allow 를 버리지 않는다
    (Allow 를 무시하면 Disallow 하위의 허용 경로를 과잉 차단한다).
    값이 빈 `Disallow:` 는 "제약 없음"이므로 규칙으로 세지 않는다.
    """
    rules: list[tuple[bool, str]] = []
    star = False
    in_agent_header = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            if not in_agent_header:
                star = False
                in_agent_header = True
            if value == "*":
                star = True
            continue
        in_agent_header = False
        if field in ("allow", "disallow") and star and value:
            rules.append((field == "allow", value))
    return rules


def _robots_match(pattern: str, path: str) -> int | None:
    """매치되면 특이도(패턴 길이), 아니면 None. `*` 와일드카드와 종단 `$` 를 지원한다."""
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "^" + "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    if anchored:
        regex += "$"
    return len(pattern) if re.search(regex, path) else None


def robots_verdict(url: str, *, timeout: float) -> PolicyVerdict:
    """robots.txt 를 조회해 Disallow 여부를 판정한다.

    조회 자체가 실패하면 해당 호스트의 기본 정책(허용)을 따르되 사유를 남긴다
    (SPEC Constraints 보안 절 — fail-open 이며 로그로 드러낸다).
    조회 요청도 일반 취득과 동일한 정책 가드를 받는다 — robots.txt 가 사설 대역으로
    리디렉션해 SSRF 차단을 우회하는 경로를 막는다.
    """
    from . import transport  # 순환 임포트 회피 (정책 -> 전송)

    parts = urlsplit(url)
    origin = origin_of(url)
    if origin is None:
        return PolicyVerdict(True, None, "robots 검사 대상 아님")

    if origin not in _robots_cache:
        robots_url = f"{origin}/robots.txt"
        try:
            precheck = check_url(robots_url)
        except UnresolvableHost as exc:
            precheck = PolicyVerdict(False, "private_range", str(exc))
        if not precheck.allowed:
            _robots_cache[origin] = ([], f"robots.txt 조회 차단 ({precheck.detail}) — 기본 허용")
        else:
            try:
                resp = transport.request(robots_url, timeout=timeout, hop_check=hop_guard)
                if 200 <= resp.status < 300:
                    _robots_cache[origin] = (_parse_robots(resp.text()), "fetched")
                else:
                    _robots_cache[origin] = ([], f"robots.txt status={resp.status} — 기본 허용")
            except (transport.NetworkError, transport.PolicyBlocked) as exc:
                _robots_cache[origin] = ([], f"robots.txt 조회 실패 ({exc}) — 기본 허용")

    rules, note = _robots_cache[origin]
    path = parts.path or "/"

    # 최장 일치 우선, 길이가 같으면 Allow 가 이긴다 (robots.txt 관례)
    best_len = -1
    best_allow = True
    best_pattern = ""
    for allow, pattern in rules:
        score = _robots_match(pattern, path)
        if score is None:
            continue
        if score > best_len or (score == best_len and allow):
            best_len, best_allow, best_pattern = score, allow, pattern

    if best_len >= 0 and not best_allow:
        return PolicyVerdict(False, "robots", f"robots.txt 가 {best_pattern} 를 Disallow 한다")
    return PolicyVerdict(True, None, note)
