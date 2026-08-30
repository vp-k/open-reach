"""임퍼소네이션과 헤더가 서로 다른 브라우저를 말하지 않는지 고정한다.

R1 실측에서 격차 6건 중 2건(bloomberg·w3.org)이 **상대의 차단이 아니라 우리가 만든
불일치** 였다 — TLS 지문은 Safari 인데 UA 헤더는 Chrome 131 Windows 였고, UA 만 빼면
같은 요청이 200 을 받았다(`bench/evidence/header-mismatch-probe.json`).

이 테스트는 네트워크를 타지 않는다. 나가는 헤더만 잡아서 본다.
"""

import pathlib
import sys

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import transport  # noqa: E402


@pytest.fixture
def captured(monkeypatch):
    """나가는 헤더를 가로챈다. 어느 경로로 나갔는지도 함께 남긴다."""
    seen: dict = {}

    def fake_curl(url, timeout, headers, impersonate):
        seen["path"] = "curl_cffi"
        seen["headers"] = dict(headers)
        seen["impersonate"] = impersonate
        return 200, {}, b"<html><body>ok</body></html>", False

    def fake_stdlib(url, timeout, headers):
        seen["path"] = "stdlib"
        seen["headers"] = dict(headers)
        return 200, {}, b"<html><body>ok</body></html>", False

    monkeypatch.setattr(transport, "_send_curl_cffi", fake_curl)
    monkeypatch.setattr(transport, "_send_stdlib", fake_stdlib)
    return seen


def test_impersonated_request_does_not_send_our_user_agent(captured, monkeypatch):
    monkeypatch.setattr(transport, "impersonation_available", lambda: True)
    transport.request("https://example.invalid/a", timeout=1.0, impersonate="safari")

    assert captured["path"] == "curl_cffi"
    assert captured["impersonate"] == "safari"
    # UA 를 우리가 정하면 지문과 어긋난다 — curl_cffi 가 프로필에 맞는 것을 넣게 둔다
    assert "User-Agent" not in captured["headers"]
    # 나머지 헤더까지 버리면 안 된다. 실측에서 원인은 UA 하나로 특정됐다
    assert captured["headers"]["Accept-Language"] == transport.DEFAULT_HEADERS["Accept-Language"]
    assert captured["headers"]["Accept"] == transport.DEFAULT_HEADERS["Accept"]


def test_non_impersonated_request_still_sends_a_user_agent(captured, monkeypatch):
    """임퍼소네이션이 없는 경로(A0 기준선·폴백)에는 UA 를 넣어 줄 주체가 없다.

    여기서까지 UA 를 빼면 우리는 UA 없는 요청을 보내는 낯선 클라이언트가 된다.
    """
    monkeypatch.setattr(transport, "impersonation_available", lambda: False)
    transport.request("https://example.invalid/a", timeout=1.0, impersonate=None)

    assert captured["path"] == "stdlib"
    assert captured["headers"]["User-Agent"] == transport.DEFAULT_HEADERS["User-Agent"]


def test_impersonation_unavailable_falls_back_with_user_agent(captured, monkeypatch):
    """프로필을 요청했지만 curl_cffi 가 없어 stdlib 로 떨어지는 경우.

    이때 UA 를 빼면 지문 일치는커녕 UA 만 사라진 요청이 된다.
    """
    monkeypatch.setattr(transport, "impersonation_available", lambda: False)
    transport.request("https://example.invalid/a", timeout=1.0, impersonate="safari")

    assert captured["path"] == "stdlib"
    assert captured["headers"]["User-Agent"] == transport.DEFAULT_HEADERS["User-Agent"]


def test_referer_survives_the_user_agent_removal(captured, monkeypatch):
    monkeypatch.setattr(transport, "impersonation_available", lambda: True)
    transport.request(
        "https://example.invalid/a",
        timeout=1.0,
        impersonate="chrome",
        referer="https://example.invalid/",
    )

    assert captured["headers"]["Referer"] == "https://example.invalid/"
    assert "User-Agent" not in captured["headers"]
