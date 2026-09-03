"""패키지 __version__ 과 플러그인 매니페스트 version 이 어긋나지 않는지 지킨다.

왜 테스트까지 두는가. ``__version__`` 은 장식이 아니라 **두 건의 사실 진술**을 찍는다.

1. ``api_index.HONEST_UA`` — Phase 0 요청에서 우리가 상대 서버에 밝히는 신원.
2. ``bench`` 증적의 ``engine`` 필드 — 그 측정이 어느 버전의 것인지.

R6 이전까지 패키지는 ``1.0.0`` 인데 매니페스트는 ``1.3.0`` 이었다. 그동안의 모든 Phase 0
요청이 실제와 다른 버전으로 자기를 소개했고, 모든 벤치 증적이 ``open-reach@1.0.0`` 으로
잘못 라벨됐다. 값 하나를 고치는 것으로는 재발을 못 막으므로 (릴리스마다 한쪽만 올리기
쉽다) 두 값을 테스트로 묶는다.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from open_reach import __version__

PLUGIN_JSON = (
    pathlib.Path(__file__).resolve().parents[2] / ".claude-plugin" / "plugin.json"
)


def _manifest_version() -> str:
    return json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))["version"]


def test_package_version_matches_plugin_manifest():
    """한쪽만 올리는 릴리스를 죽인다."""
    assert __version__ == _manifest_version(), (
        f"open_reach.__version__={__version__} 이지만 "
        f"plugin.json version={_manifest_version()} 이다. "
        "릴리스 시 두 값을 함께 올린다."
    )


def test_honest_ua_carries_the_real_version():
    """UA 가 버전을 아예 안 싣거나 하드코딩된 값을 싣는 변이를 죽인다."""
    from open_reach.api_index import HONEST_UA

    assert f"open-reach/{__version__}" in HONEST_UA


@pytest.mark.parametrize("part", ["0", "."])
def test_version_is_a_plausible_semver(part):
    """빈 문자열·None 이 UA 에 실려 신원이 사라지는 변이를 죽인다."""
    assert part in __version__
    assert __version__.count(".") == 2
