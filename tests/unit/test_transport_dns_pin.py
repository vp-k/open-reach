"""stdlib 폴백 경로도 DNS 를 우리가 고정한다 (코드리뷰 HIGH).

curl_cffi 경로는 `CURLOPT_RESOLVE` 로 정책이 검증한 IP 에 고정하지만, curl_cffi 가
없어 stdlib 로 떨어지면 `http.client` 가 호스트명을 **다시 해석**한다. 그 순간
검증 시점과 연결 시점의 IP 가 달라질 수 있어(TOCTOU) SSRF 방어에 구멍이 난다.
`_send_stdlib` 이 정책이 준 IP 로 직접 붙는지, 그리고 정책이 차단하면 연결 전에
PolicyBlocked 로 끊는지 검증한다.
"""

import pathlib
import sys

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import policy, transport  # noqa: E402


def test_stdlib_connects_to_policy_pinned_ip(monkeypatch):
    pinned_ip = "203.0.113.7"  # TEST-NET-3 — 실제로 라우팅되지 않는다
    monkeypatch.setattr(policy, "resolved_targets", lambda url: [pinned_ip])

    seen = []

    def fake_create_connection(address, timeout=None):
        seen.append(address)
        # 고정 IP 를 확인했으면 실제 통신은 하지 않는다 — 연결 대상만 검사한다.
        raise OSError("stub: 연결 대상만 확인")

    monkeypatch.setattr(transport.socket, "create_connection", fake_create_connection)

    # 호스트명이 아니라 정책이 준 IP 로 붙어야 한다. 모든 핀이 실패하면 NetworkError.
    with pytest.raises(transport.NetworkError):
        transport._send_stdlib("http://example.com/x", 5.0, {})

    assert seen == [(pinned_ip, 80)], (
        f"stdlib 가 고정 IP 가 아닌 {seen} 로 붙었다 — 호스트명 재해석 구멍"
    )


def test_stdlib_propagates_policy_block_before_connect(monkeypatch):
    def blocked(url):
        raise transport.PolicyBlocked("private_range", "정책 차단")

    monkeypatch.setattr(policy, "resolved_targets", blocked)

    def fail_connect(*a, **k):
        raise AssertionError("차단된 대상에 연결을 시도했다 — fail-closed 위반")

    monkeypatch.setattr(transport.socket, "create_connection", fail_connect)

    with pytest.raises(transport.PolicyBlocked):
        transport._send_stdlib("http://10.0.0.1/x", 5.0, {})
