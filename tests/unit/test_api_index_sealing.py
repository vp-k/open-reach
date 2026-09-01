"""Phase 0 는 어떤 예외도 밖으로 던지지 않는다 (코드리뷰 MEDIUM).

계약: `run()` 은 전 단계 격리 지점이다 — 예상 밖 예외(비정상 깊이 JSON 의
RecursionError, 조립 URL 의 포트 범위 초과 등)가 밖으로 새면 Phase 0 실패가 뒤
단계·CLI 를 오염시킨다. 분류에 안 걸린 예외도 outcome 에 종류를 남기고 정상 종료하는지
검증한다 (NG-10 — 다른 이유로 세탁하지 않는다).
"""

import pathlib
import sys

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import api_index  # noqa: E402


def _run(monkeypatch, exc):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(api_index, "_run_endpoints", boom)
    # "chain" 이 없으면 run() 은 _run_endpoints 로 분기한다.
    return api_index.run(
        {"endpoints": ["http://example.com/x"], "response_kind": "html"},
        {},
        intent="article",
        timeout=5.0,
        on_attempt=lambda *a: None,
    )


def test_recursion_error_is_sealed(monkeypatch):
    outcome = _run(monkeypatch, RecursionError("too deep"))
    # 밖으로 새지 않고 outcome 을 돌려준다.
    assert outcome is not None
    assert any("internal" in n and "RecursionError" in n for n in outcome.notes)
    # 성공 세탁 금지: markdown 없음.
    assert outcome.markdown is None


def test_unexpected_exception_is_sealed(monkeypatch):
    outcome = _run(monkeypatch, ValueError("assembled url weirdness"))
    assert any("internal" in n and "ValueError" in n for n in outcome.notes)
