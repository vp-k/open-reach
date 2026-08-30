"""NAT64 표기를 통한 SSRF 우회 회귀 테스트 (코드리뷰 R10 MAJOR).

`64:ff9b::a9fe:a9fe` 는 v6 차단 대역표에도, IPv4-mapped/6to4/Teredo 어느 변환에도
걸리지 않는다. 그러나 NAT64 게이트웨이를 지나면 실제 목적지는 169.254.169.254 —
클라우드 메타데이터다. 표기만 바꿔 가드를 지나가는 통로였다.
"""

import pathlib
import sys

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import policy  # noqa: E402


@pytest.mark.parametrize(
    "address, inner",
    [
        # RFC 6052 well-known prefix (64:ff9b::/96)
        ("64:ff9b::a9fe:a9fe", "169.254.169.254"),  # 메타데이터
        ("64:ff9b::7f00:1", "127.0.0.1"),  # 루프백
        ("64:ff9b::a00:1", "10.0.0.1"),  # 사설
        # RFC 8215 local-use prefix (64:ff9b:1::/48)
        ("64:ff9b:1::7f00:1", "127.0.0.1"),
        ("64:ff9b:1::a9fe:a9fe", "169.254.169.254"),
    ],
)
def test_nat64_embedded_private_is_blocked(address, inner):
    reason = policy._blocked_band(address)
    assert reason is not None, f"{address} 가 통과했다 — {inner} 로 나가는 경로다"
    assert inner in reason, f"차단은 됐지만 사유에 실제 목적지가 없다: {reason}"


def test_nat64_public_target_is_not_blocked():
    """과잉 차단이 기본이지만, 공인 IPv4 를 담은 NAT64 주소까지 막지는 않는다."""
    assert policy._blocked_band("64:ff9b::808:808") is None  # 8.8.8.8


def test_rfc6052_layout_skips_u_octet():
    """/64 배치는 비트 64..71(u 옥텟)을 건너뛰고 읽는다 — RFC 6052 §2.2."""
    import ipaddress

    # 64:ff9b:1:0:00:7f00:0001:xxxx — u 옥텟(0x00)을 건너뛰면 127.0.0.1
    value = int(ipaddress.IPv6Address("64:ff9b:1::7f:0:100:0"))
    assert policy._rfc6052_extract(value, 64) == ipaddress.IPv4Address("127.0.0.1")
