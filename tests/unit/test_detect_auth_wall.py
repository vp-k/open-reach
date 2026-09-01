"""401 은 본문 길이와 무관하게 인증벽이다 (코드리뷰 HIGH).

`classify` 의 success(substantial) 판정이 상태 코드 검사보다 앞서 있으면, 로그인 뒤
자원이 본문을 길게 실어 200 처럼 보이는 401 응답이 success 로 새어 돌파율을 부풀린다.
그것은 우리가 돌파한 공개 콘텐츠가 아니므로 NG-1(로그인월 미돌파·감지만)을 깬다.
success 예외보다 **먼저** 401 을 auth_wall 로 끊는지 검증한다.
"""

import pathlib
import sys

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import detect  # noqa: E402

# 길이·문단 형태로는 정상 기사와 구분되지 않는 본문 (로그인 폼·페이월 문구 없음).
_LONG_PROSE = (
    "이 문단은 인증이 필요한 자원의 본문처럼 충분히 길고 문장 형태를 갖추었다. "
    "상태 코드를 무시하고 길이만 보면 success 로 오인될 만큼 실속 있는 텍스트다. "
    "그러나 이 자원은 로그인 뒤에 있으므로 우리가 돌파한 공개 콘텐츠가 아니다. "
    "돌파율에 세면 안 되고, 감지만 하고 인증벽으로 종료해야 한다. " * 3
)


def _html(body: str) -> str:
    return f"<html><body><article>{body}</article></body></html>"


def test_401_with_long_body_is_auth_wall_not_success():
    verdict = detect.classify(401, _html(_LONG_PROSE), _LONG_PROSE)
    assert verdict.reason == "auth_wall"
    assert verdict.outcome == "wall"
    assert verdict.terminal is True
    assert "http_401" in verdict.signals


def test_same_body_at_200_is_success():
    # 동일 본문이 200 에서는 success 여야 한다 — 401 가드가 다른 상태까지
    # 과도하게 막지 않음을 대조로 확인한다.
    verdict = detect.classify(200, _html(_LONG_PROSE), _LONG_PROSE)
    assert verdict.reason is None
    assert verdict.outcome == "success"


def test_403_with_body_still_success():
    # 403 은 소프트 WAF 차단이라도 공개 본문을 그대로 주는 경우가 있어 success 예외를
    # 유지한다 (classify 의 요점). 401 가드가 이 예외를 훼손하지 않아야 한다.
    verdict = detect.classify(403, _html(_LONG_PROSE), _LONG_PROSE)
    assert verdict.reason is None
    assert verdict.outcome == "success"
