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
import sys
from urllib.parse import urlsplit

from .models import ROBOTS_MODES, PolicyVerdict

MAX_URL_LENGTH = 2048
ALLOWED_SCHEMES = ("http", "https")

# ── robots.txt 모드 (R6) ─────────────────────────────────────────────────
#
# R1~R5 는 robots 를 fail-closed 차단으로 강제했다. R1 의 실측(docs/r1-report.md)은
# 원본 대비 격차 4 건 중 2 건이 **robots 자발 포기**였다고 기록했고, R5 는 어댑터
# 후보 3 건이 전부 `User-agent: * / Disallow: /` 로 막혀 미등재됐다.
# 즉 남은 격차는 돌파력이 아니라 정책이었다. R6 에서 사용자 승인 아래 기본값을
# 뒤집는다 (docs/policy-boundaries.md §6 — 경계 완화는 승인 없이 하지 않는다).
#
#   off      기본값. robots.txt 를 **조회하지 않는다** (요청 0 건).
#   advisory 조회하되 차단하지 않는다. 판정은 남긴다.
#   enforce  R5 까지의 동작. `--respect-robots` 가 켠다.
#
# robots 를 보지 않는 것과 **신원을 속이는 것**은 다른 일이다. 허용 UA 사칭
# (US-B-013 철회 근거)·프록시 로테이션(NG-6)·인증 우회(NG-1/2/4)는 모드와 무관하게
# 그대로 금지다.
# 값의 닫힌 집합은 models.ROBOTS_MODES 가 갖는다 (재수출).
DEFAULT_ROBOTS_MODE = "off"

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


class _InvalidURL(Exception):
    """URL 구성요소가 문법적으로 유효 범위를 벗어났다 (예: 포트 0-65535 초과)."""


def _port_of(parts) -> int:
    """명시 포트 또는 스킴 기본 포트.

    범위를 벗어난 포트는 `urlsplit` 이 아니라 `.port` 접근 순간 `ValueError` 를 던진다
    (지연 파싱). 이 예외가 정책 함수를 뚫고 나가면 CLI 가 구조화된 결과 없이 죽고
    (일반 fetch), Phase 0 격리 계약도 깨진다. 한곳에서 잡아 `_InvalidURL` 로 바꿔
    각 호출자가 자기 계약(verdict/PolicyBlocked)에 맞게 거부하도록 한다.
    """
    try:
        explicit = parts.port
    except ValueError as exc:
        raise _InvalidURL(f"포트 범위 초과 (0-65535): {exc}") from exc
    # `explicit is None` 만 "포트 미명시"다. `:0` 은 명시된 포트 0 이며 기본 포트가
    # 아니다 — `or` 로 뭉개면 `http://h:0/` 가 `:80` 오리진으로 정규화되어, 정확한
    # 픽스처 오리진 매칭(유일한 SSRF 예외)의 경계가 흐려진다. 명시 포트는 그대로 둔다.
    return explicit if explicit is not None else _default_port(parts.scheme)


def origin_of(url: str) -> str | None:
    """`scheme://host:port` 로 정규화한다. 기본 포트는 명시 포트와 같은 것으로 본다."""
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES or not parts.hostname:
        return None
    try:
        port = _port_of(parts)
    except _InvalidURL:
        return None
    return f"{parts.scheme}://{parts.hostname.lower()}:{port}"


def _is_loopback_literal(address: str) -> bool:
    """주소가 **IP 리터럴이며 루프백**인가. 이름은 이름일 뿐 주소가 아니다."""
    try:
        return ipaddress.ip_address(address.strip("[]")).is_loopback
    except ValueError:
        return False


_warned_fixture_rejected = False


def fixture_origin() -> str | None:
    """인수 테스트 전용 예외 오리진. 변수가 없으면 예외는 존재하지 않는다.

    호스트가 **루프백 IP 리터럴**일 때만 예외를 인정한다. SPEC 이 이 예외의 용도를
    "로컬 픽스처 서버(`127.0.0.1:<임의 포트>`)"로 못박고 있는데 DNS 이름을 허용하면,
    그 이름이 사설 주소로 재바인딩되는 순간 예외 자체가 SSRF 통로가 된다 — 이름은
    해석 시점마다 달라질 수 있지만 리터럴은 달라지지 않는다.
    """
    global _warned_fixture_rejected

    raw = os.environ.get("OPENREACH_FIXTURE_BASE", "").strip()
    if not raw:
        return None
    origin = origin_of(raw)
    if origin is None:
        return None
    if not _is_loopback_literal(urlsplit(raw).hostname or ""):
        if not _warned_fixture_rejected:
            _warned_fixture_rejected = True
            sys.stderr.write(
                f"[open-reach] OPENREACH_FIXTURE_BASE 를 무시한다 ({raw}) — "
                "픽스처 예외는 루프백 IP 리터럴 오리진에만 적용된다\n"
            )
        return None
    return origin


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


# RFC 6052 §2.2 — 접두 길이에 따라 IPv4 32비트가 놓이는 자리가 다르고,
# 비트 64..71(u 옥텟)은 어느 배치에서도 건너뛴다.
_NAT64_WELL_KNOWN = ipaddress.ip_network("64:ff9b::/96")  # RFC 6052
_NAT64_LOCAL_USE = ipaddress.ip_network("64:ff9b:1::/48")  # RFC 8215
# /48 접두 안에서 쓰일 수 있는 배치들. 어느 것으로 읽었을 때든 사설·메타데이터가
# 나오면 막는다 — 어떤 배치인지 확정할 수 없으니 과잉 차단 쪽으로 기운다.
# 순서는 실제 배포 빈도순(/96 이 압도적으로 흔하다)이다. 차단 사유 문장은 처음
# 걸린 배치를 인용하므로, 순서가 뒤집히면 `64:ff9b:1::7f00:1` 을 막고도 사유에는
# 127.0.0.1 대신 다른 배치의 부산물인 `0.0.0.0` 이 찍혀 진단이 사람을 헷갈리게 한다.
_NAT64_LOCAL_LAYOUTS = (96, 64, 56, 48)


def _rfc6052_extract(value: int, prefix_len: int) -> ipaddress.IPv4Address:
    """128비트 값에서 RFC 6052 배치대로 IPv4 32비트를 꺼낸다 (u 옥텟은 건너뛴다)."""
    out = 0
    pos = prefix_len
    read = 0
    while read < 32:
        if 64 <= pos < 72:  # u 옥텟은 주소가 아니다
            pos = 72
            continue
        out = (out << 1) | ((value >> (127 - pos)) & 1)
        pos += 1
        read += 1
    return ipaddress.IPv4Address(out)


def _nat64_embedded(ip: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    """NAT64 접두 안에 든 IPv4 목적지를 꺼낸다.

    `64:ff9b::a9fe:a9fe` 는 v6 대역표에도, IPv4-mapped/6to4/Teredo 어디에도 걸리지
    않지만 NAT64 게이트웨이를 지나면 169.254.169.254(클라우드 메타데이터)에 닿는다.
    표기만 바꿔 SSRF 가드를 우회하는 통로이므로 여기서 함께 푼다.
    """
    value = int(ip)
    if ip in _NAT64_WELL_KNOWN:
        return [_rfc6052_extract(value, 96)]
    if ip in _NAT64_LOCAL_USE:
        return [_rfc6052_extract(value, pl) for pl in _NAT64_LOCAL_LAYOUTS]
    return []


def _embedded_v4(ip: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    """IPv6 표기 안에 들어 있는 실제 IPv4 목적지를 모두 꺼낸다.

    `::ffff:127.0.0.1`(IPv4-mapped)·`2002::/16`(6to4)·Teredo·NAT64 는 `ip.version == 6`
    이므로 v6 대역표만 보면 하나도 걸리지 않는다. 그러나 패킷이 실제로 향하는 곳은
    안에 든 IPv4 다 — 풀지 않으면 루프백·사설 대역이 SSRF 가드를 그대로 지나간다.
    Teredo 는 (서버, 클라이언트) 두 주소를 담으므로 둘 다 본다: 판정 불가한 쪽을
    통과시키는 것보다 과잉 차단이 낫다 (가드는 fail-closed 다).
    """
    found: list[ipaddress.IPv4Address] = []
    mapped = ip.ipv4_mapped
    if mapped is not None:
        found.append(mapped)
    sixtofour = ip.sixtofour
    if sixtofour is not None:
        found.append(sixtofour)
    teredo = ip.teredo
    if teredo is not None:
        found.extend(teredo)
    found.extend(_nat64_embedded(ip))
    return found


def _blocked_band(address: str) -> str | None:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        # 주소를 해석할 수 없다 = 판정 불가 = 차단
        return f"주소 판정 불가: {address}"

    if ip.version == 6:
        for inner in _embedded_v4(ip):
            reason = _blocked_band(str(inner))
            if reason is not None:
                return f"{address} 안에 IPv4 {inner} 가 들어 있다 — {reason}"

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

    try:
        port = _port_of(parts)
    except _InvalidURL as exc:
        return PolicyVerdict(False, "scheme", str(exc))
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

    try:
        port = _port_of(parts)
    except _InvalidURL as exc:
        return PolicyVerdict(False, "scheme", str(exc))
    exempt = fixture_origin()
    if exempt is not None and f"{parts.scheme}://{host}:{port}" == exempt:
        # 오리진이 예외라도 **연결된 주소**가 루프백을 벗어나면 예외가 아니다.
        # `fixture_origin` 이 이미 리터럴만 통과시키지만, 예외의 경계는 두 곳에서
        # 각각 성립해야 한 곳의 실수가 통로가 되지 않는다.
        if _is_loopback_literal(address):
            return PolicyVerdict(True, None, f"테스트 픽스처 오리진 예외: {address}")
        return PolicyVerdict(
            False, "private_range", f"픽스처 오리진이 루프백 밖 주소로 연결됐다: {address}"
        )

    reason = _blocked_band(address)
    if reason is not None:
        return PolicyVerdict(False, "private_range", reason)
    return PolicyVerdict(True, None, f"연결 주소 {address} 는 공개 대역이다")


def resolved_targets(url: str) -> list[str]:
    """정책을 통과한 연결 대상 주소 목록. 차단이면 transport.PolicyBlocked 를 던진다.

    커널이 실제로 붙은 주소를 **요청을 보내기 전에** 볼 수 없는 전송(libcurl)에서는
    이 목록으로 이름 해석을 고정한다. 검사한 주소와 연결하는 주소가 같아야 TOCTOU 가
    닫히기 때문이다 — 응답을 받은 뒤에 확인하는 것은 이미 요청이 도달한 뒤다.
    판정 기준은 `check_url` 과 같다 (하나라도 차단 대역이면 전체 차단).
    """
    from . import transport  # 순환 임포트 회피 (정책 -> 전송)

    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    try:
        port = _port_of(parts)
    except _InvalidURL as exc:
        raise transport.PolicyBlocked("scheme", str(exc)) from exc
    if host in METADATA_HOSTS:
        raise transport.PolicyBlocked("private_range", f"클라우드 메타데이터 주소: {host}")

    exempt = fixture_origin()
    exempted = exempt is not None and f"{parts.scheme}://{host}:{port}" == exempt

    allowed: list[str] = []
    for address in _resolve(host, port):
        if address in METADATA_HOSTS:
            raise transport.PolicyBlocked("private_range", f"클라우드 메타데이터 주소: {address}")
        if exempted:
            if not _is_loopback_literal(address):
                raise transport.PolicyBlocked(
                    "private_range", f"픽스처 오리진이 루프백 밖 주소로 해석됐다: {address}"
                )
            allowed.append(address)
            continue
        reason = _blocked_band(address)
        if reason is not None:
            raise transport.PolicyBlocked("private_range", reason)
        allowed.append(address)

    if not allowed:
        raise transport.PolicyBlocked("private_range", f"{host} 의 연결 가능한 주소가 없다")
    return allowed


# robots 를 홉마다 조회할 때 쓰는 타임아웃. hop_check 콜백은 인자를 하나만 받으므로
# 원 요청의 타임아웃을 넘겨받을 자리가 없다 — robots 조회는 원 요청보다 짧게 잡는다.
ROBOTS_HOP_TIMEOUT = 10.0

# robots.txt 조회의 리디렉션은 **상한을 두지 않는다.** 라운드 3 에서 항목당 요청 총량
# 산식을 참으로 만들려고 1홉 상한을 넣었는데, 조회 실패는 SPEC 상 fail-open 이라
# (아래 `robots_verdict`) 상한에 걸린 조회가 "규칙 없음 = 전부 허용"으로 캐시됐다.
# `robots.txt -> /r1 -> /r2` 로 정규화하는 사이트에서 `/r2` 의 Disallow 가 통째로
# 사라지는 우회였다 — 상한을 지키려다 경계를 뚫은 것이다 (라운드 4 HIGH).
# 요청 총량 상한은 robots 를 `transport.MAX_REDIRECTS` 기준으로 세는 쪽으로 옮겼다.


def ssrf_hop_guard(next_url: str) -> None:
    """SSRF 만 보는 홉 가드.

    robots.txt **자신을** 가져오는 요청에만 쓴다. 여기서 robots 를 다시 보면
    robots 조회가 robots 조회를 부르는 재귀가 된다.
    """
    from . import transport  # 순환 임포트 회피 (정책 -> 전송)

    try:
        verdict = check_url(next_url)
    except UnresolvableHost as exc:
        raise transport.NetworkError(str(exc)) from exc
    if not verdict.allowed:
        raise transport.PolicyBlocked("redirect_hop", verdict.detail)


def hop_guard(next_url: str) -> None:
    """리디렉션 홉 재검사. 차단이면 transport.PolicyBlocked 를 던진다.

    transport.request 의 `hop_check` 로 넘기는 표준 가드다 — 리디렉션을 따라가는
    모든 경로가 같은 가드를 쓴다 (경로별 누락을 만들지 않는다).

    **SSRF 와 robots 를 함께 본다.** 리디렉션 목적지는 호스트도 경로도 원 URL 과
    다를 수 있고, 원 URL 에서 통과한 robots 판정은 목적지의 근거가 아니다
    (AC-B-010-3·13 이 조립 URL 에 대해 요구하는 것과 같은 이유다). 이전에는
    SSRF 만 봤고 docstring 만 "robots 조회를 포함해"라고 적혀 있었다 — 코드가
    아니라 주석이 계약을 지키고 있었다.
    """
    from . import transport  # 순환 임포트 회피 (정책 -> 전송)

    ssrf_hop_guard(next_url)
    robots = robots_verdict(next_url, timeout=ROBOTS_HOP_TIMEOUT)
    if not robots.allowed:
        raise transport.PolicyBlocked(robots.rule or "robots_disallow", robots.detail)


def advisory_hop_guard(next_url: str) -> None:
    """SSRF 는 강제하고 robots 는 보고만 하는 홉 가드 (mode=advisory)."""
    ssrf_hop_guard(next_url)
    robots = robots_verdict(next_url, timeout=ROBOTS_HOP_TIMEOUT)
    if not robots.allowed:
        _warn_advisory(next_url, robots.detail)


def hop_guard_for(mode: str):
    """모드에 맞는 홉 가드를 **고른다** (R6).

    가드에 모드 인자를 더하는 대신 함수를 고르는 이유: `off` 에서 홉 가드가
    robots 를 조회할 **경로 자체가 존재하지 않게** 하려는 것이다. 인자로 분기하면
    "off 인데 조회했다"가 런타임 버그로 가능하지만, 여기서는 `ssrf_hop_guard` 에
    robots 코드가 아예 없으므로 구조적으로 불가능하다.

    SSRF 는 어느 모드에서도 빠지지 않는다 (NG-11 은 개정 대상이 아니다).
    """
    if mode == "enforce":
        return hop_guard
    if mode == "advisory":
        return advisory_hop_guard
    return ssrf_hop_guard


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
                resp = transport.request(robots_url, timeout=timeout, hop_check=ssrf_hop_guard)
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


# advisory 경고는 (오리진, 규칙) 당 한 번만 낸다 — 배치·검색이 같은 호스트를 여러 번
# 두드릴 때 stderr 가 같은 줄로 뒤덮이면 정작 읽어야 할 실패가 묻힌다.
_advisory_warned: set[str] = set()


def _warn_advisory(url: str, detail: str) -> None:
    origin = origin_of(url) or url
    if origin in _advisory_warned:
        return
    _advisory_warned.add(origin)
    sys.stderr.write(f"[open-reach] robots advisory: {origin} — {detail} (차단하지 않음)\n")


def robots_gate(url: str, *, timeout: float, mode: str) -> PolicyVerdict:
    """모드를 반영한 robots 판정 (R6).

    `robots_verdict` 는 "robots.txt 가 뭐라고 하는가"라는 **사실**을 그대로 답하고,
    이 함수가 "그래서 막을 것인가"라는 **정책**을 결정한다. 둘을 섞지 않았기 때문에
    advisory 모드가 사실을 보고하면서도 차단하지 않을 수 있다.

    반환값의 `allowed=False` 는 오직 `enforce` 에서만 나온다.
    """
    if mode not in ROBOTS_MODES:
        raise ValueError(f"unknown robots mode: {mode}")

    if mode == "off":
        # 네트워크에 나가지 않는다. `robots_verdict` 를 부르고 결과를 버리는 것은
        # "조회하지 않는다"가 아니다 — 요청은 이미 나갔고 상대 서버는 그것을 봤다.
        return PolicyVerdict(True, None, "robots 미조회 (mode=off)")

    verdict = robots_verdict(url, timeout=timeout)
    if mode == "enforce" or verdict.allowed:
        return verdict

    _warn_advisory(url, verdict.detail)
    return PolicyVerdict(True, None, f"advisory: {verdict.detail} — 차단하지 않음")
