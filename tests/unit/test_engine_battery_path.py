"""출하 배터리 판정이 '경로' 로 이뤄지는지 고정한다.

SPEC:329 는 `--tier`/`--holdout` 로 지정되는 출하 배터리(`bench/battery.yaml`,
`bench/holdout.yaml`)가 `role: production` 이어야 한다고 적고, 그 이유를 "출하 배터리를
fixture 로 강등해 G-1 을 회피하는 경로를 막는다" 라고 밝혀 두었다. 판정이 플래그
기준이면 `--battery bench/battery.yaml` 한 줄로 그 검사가 꺼진다.
"""

import argparse
import pathlib
import sys

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import engine  # noqa: E402


def _args(**kw) -> argparse.Namespace:
    base = {"tier": 1, "battery": None, "holdout": False}
    base.update(kw)
    return argparse.Namespace(**base)


def test_default_path_is_the_name_spec_uses():
    """SPEC 은 `bench/battery.yaml` 이라 적었다. 코드가 다른 이름을 보면 기본 실행이 죽는다."""
    path, shipped = engine._battery_path(_args())
    assert path.name == "battery.yaml"
    assert path.parent.name == "bench"
    assert shipped is True
    assert path.exists(), "출하 배터리가 SPEC 이 지정한 경로에 있어야 한다"


def test_pointing_at_the_shipped_battery_is_still_shipped():
    """우회로 차단 — 같은 파일을 --battery 로 가리켜도 출하 배터리다."""
    shipped_battery, _ = engine._shipped_paths()
    path, shipped = engine._battery_path(_args(battery=str(shipped_battery)))
    assert shipped is True

    # 상대 경로·중복 구분자로 적어도 같은 판정이어야 한다
    messy = str(shipped_battery.parent / "." / shipped_battery.name)
    _, shipped_messy = engine._battery_path(_args(battery=messy))
    assert shipped_messy is True


def test_other_battery_files_are_not_shipped(tmp_path):
    """픽스처 배터리는 출하 배터리가 아니다 — 여기까지 막으면 개발이 불가능해진다."""
    other = tmp_path / "battery.yaml"
    other.write_text("role: fixture\nentries: []\n", encoding="utf-8")
    _, shipped = engine._battery_path(_args(battery=str(other)))
    assert shipped is False


def test_holdout_is_a_shipped_battery():
    path, shipped = engine._battery_path(_args(holdout=True))
    assert path.name == "holdout.yaml"
    assert shipped is True


def test_shipped_paths_do_not_move_with_the_state_dir(monkeypatch, tmp_path):
    """R11 리뷰 CRITICAL-1 — 환경변수 한 줄로 출하 배터리의 신원이 바뀌면 안 된다.

    holdout 을 `state_dir()` 기준으로 잡으면 `OPENREACH_STATE_DIR` 를 옮긴 상태에서
    진짜 출하 holdout 을 `--battery` 로 가리켰을 때 `shipped=False` 가 되어
    `role: production` 검사가 꺼진다 — 방금 막은 우회로가 환경변수로 다시 열린다.
    """
    before = engine._shipped_paths()
    monkeypatch.setenv("OPENREACH_STATE_DIR", str(tmp_path))
    after = engine._shipped_paths()
    assert after == before

    real_holdout = before[1]
    _, shipped = engine._battery_path(_args(battery=str(real_holdout)))
    assert shipped is True, "출하 holdout 을 직접 가리켜도 출하 배터리다"


def test_holdout_and_battery_together_is_a_usage_error():
    with pytest.raises(engine.bench_mod.UsageError):
        engine._battery_path(_args(holdout=True, battery="x.yaml"))
