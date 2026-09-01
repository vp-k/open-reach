"""문법적으로 잘못된 포트는 구조화된 거부로 처리한다 (코드리뷰 MEDIUM).

`urlsplit(...).port` 는 0-65535 범위를 벗어난 포트에 **접근하는 순간** ValueError 를
던진다. 이 예외가 정책 함수 밖으로 새면 fetch 가 통제되지 않은 스택트레이스로 죽어
경계(경계는 정책 판정으로 종료해야 한다)를 우회한다. `_port_of` 로 한곳에서 잡아
각 진입점이 정직한 거부(scheme)로 바꾸는지 검증한다.
"""

import pathlib
import sys

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import policy, transport  # noqa: E402

_BAD_PORT = "http://example.com:99999/x"  # 65535 초과


def test_check_url_rejects_out_of_range_port():
    verdict = policy.check_url(_BAD_PORT)
    assert verdict.allowed is False
    assert verdict.rule == "scheme"


def test_origin_of_returns_none_for_bad_port():
    assert policy.origin_of(_BAD_PORT) is None


def test_resolved_targets_blocks_bad_port_before_connect():
    with pytest.raises(transport.PolicyBlocked) as exc:
        policy.resolved_targets(_BAD_PORT)
    assert exc.value.rule == "scheme"


def test_valid_port_is_not_rejected_as_invalid():
    # 정상 포트는 이 경로로 거부되지 않는다 (과도 차단 방지 대조).
    verdict = policy.check_url("http://example.com:8080/x")
    # 포트 자체는 유효하므로 scheme 거부가 나오면 안 된다. (사설/공인 판정은 별개)
    assert not (verdict.allowed is False and verdict.rule == "scheme")
