"""추종한 중간 리디렉션 홉을 감사에 남긴다 (코드리뷰 MEDIUM).

리디렉션을 따라가면서 나간 요청이 attempts 에 하나도 안 남으면, SC-9 감사가 보는
것은 우리의 의도(최종 URL)이지 실제로 회선에 나간 요청들이 아니다. 특히 리디렉션이
차단으로 끝나는 경우, 302 를 받은 그 요청 자체가 기록에서 사라진다. `on_dispatch`
훅이 최종 응답이 아닌 **중간 3xx 홉만** (차단으로 끝나는 홉 포함) 통지하는지 검증한다.
"""

import pathlib
import sys

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import models, transport  # noqa: E402

_LONG = "<html><body><article>" + ("문단 본문 텍스트. " * 40) + "</article></body></html>"


def test_redirect_outcome_is_a_valid_model_value():
    # attempts 에 남길 중간 홉 outcome. 모델 어휘에 없으면 Attempt 생성이 거부된다.
    assert "redirect" in models.OUTCOMES


def test_on_dispatch_fires_for_intermediate_hop_only(monkeypatch):
    responses = iter([
        (302, {"location": "http://other.example/final"}, b"", False),
        (200, {}, _LONG.encode("utf-8"), False),
    ])
    monkeypatch.setattr(transport, "_send_stdlib", lambda url, timeout, headers: next(responses))

    dispatched = []
    resp = transport.request(
        "http://start.example/",
        timeout=5.0,
        impersonate=None,
        hop_check=lambda nxt: None,
        on_dispatch=lambda url, status, ms: dispatched.append((url, status, ms)),
    )

    # 최종 응답에는 on_dispatch 를 부르지 않는다 — 호출자의 최종 기록과 이중 계상 방지.
    assert len(dispatched) == 1
    assert dispatched[0][0] == "http://start.example/"
    assert dispatched[0][1] == 302
    assert isinstance(dispatched[0][2], int)
    assert resp.status == 200
    assert resp.final_url == "http://other.example/final"


def test_on_dispatch_fires_before_hop_block(monkeypatch):
    responses = iter([
        (302, {"location": "http://blocked.example/x"}, b"", False),
    ])
    monkeypatch.setattr(transport, "_send_stdlib", lambda url, timeout, headers: next(responses))

    dispatched = []

    def blocking_hop(nxt):
        raise transport.PolicyBlocked("redirect_hop", "공개 → 사설 리디렉션 차단")

    with pytest.raises(transport.PolicyBlocked):
        transport.request(
            "http://start.example/",
            timeout=5.0,
            impersonate=None,
            hop_check=blocking_hop,
            on_dispatch=lambda url, status, ms: dispatched.append((url, status, ms)),
        )

    # 차단 직전에 나간 302 요청이 기록되어야 한다 — 나간 요청은 남긴다.
    assert len(dispatched) == 1
    assert dispatched[0][1] == 302
