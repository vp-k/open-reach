"""벤치 이력은 append 전용이고, 게이트로 막힌 실행은 회귀 기준에서 제외한다 (코드리뷰 MEDIUM).

- `observe.append_jsonl(..., rotate=False)` 는 상한을 넘겨도 회전하지 않는다.
  회전은 `.1` 로 오래된 줄을 버리므로 이력에 쓰면 AC-B-004-4(기존 줄 미수정·미삭제)를 깬다.
- `bench.prior_rate` 는 `gated=True` 실행을 기준(baseline)에서 건너뛴다. 게이트로 막힌
  실행의 돌파율은 음성 오분류로 부풀거나 표본이 달라 신뢰할 수 없다.
- `record_run(..., gated=True)` 는 이력엔 남기되 그 줄에 gated 표식을 남긴다.
"""

import pathlib
import sys

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import bench, observe  # noqa: E402


def test_rotate_false_never_drops_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(observe, "OBSERVATIONS_MAX_BYTES", 10)  # 아주 작게
    target = tmp_path / "history.jsonl"

    observe.append_jsonl(target, {"n": 1}, rotate=False)
    observe.append_jsonl(target, {"n": 2}, rotate=False)  # 이미 10바이트 초과 상태

    rotated = target.with_name("history.1.jsonl")
    assert not rotated.exists(), "이력이 회전되어 오래된 줄을 버렸다 (append-only 위반)"
    assert len(observe.read_jsonl(target)) == 2


def test_rotate_true_drops_old_lines(tmp_path, monkeypatch):
    # 대조: 학습 로그(rotate=True)는 상한 도달 시 회전한다.
    monkeypatch.setattr(observe, "OBSERVATIONS_MAX_BYTES", 10)
    target = tmp_path / "observations.jsonl"

    observe.append_jsonl(target, {"n": 1}, rotate=True)
    observe.append_jsonl(target, {"n": 2}, rotate=True)

    rotated = target.with_name("observations.1.jsonl")
    assert rotated.exists()


def test_prior_rate_skips_gated_run(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENREACH_STATE_DIR", str(tmp_path))
    hist = observe.bench_history_path()

    # 오래된 완주 baseline (0.5) → 이후 최근 gated 실행 (0.9).
    observe.append_jsonl(hist, rotate=False, record={
        "battery_hash": "H", "tier": 1, "rate_median": 0.5, "truncated": False, "gated": False,
    })
    observe.append_jsonl(hist, rotate=False, record={
        "battery_hash": "H", "tier": 1, "rate_median": 0.9, "truncated": False, "gated": True,
    })

    # 최근 줄이 gated 이므로 건너뛰고 baseline 0.5 를 돌려줘야 한다.
    assert bench.prior_rate("H", 1) == 0.5


def test_prior_rate_none_when_only_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENREACH_STATE_DIR", str(tmp_path))
    hist = observe.bench_history_path()
    observe.append_jsonl(hist, rotate=False, record={
        "battery_hash": "H", "tier": 1, "rate_median": 0.9, "truncated": False, "gated": True,
    })
    assert bench.prior_rate("H", 1) is None


def test_record_run_marks_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENREACH_STATE_DIR", str(tmp_path))
    battery = tmp_path / "battery.yaml"
    battery.write_text("role: test\nentries: []\n", encoding="utf-8")

    report = {
        "tier": 1, "runs": 1, "total": 0, "passed": 0, "failed": 0,
        "rate_median": 0.0, "rate_http_only": 0.0, "rescued_by_phase0": 0,
        "vendor_accuracy": 0.0, "vendor_sc8": {}, "truncated": False,
        "by_vendor": {}, "by_route": {}, "by_reason": {},
    }
    bench.record_run(report, battery_path=battery, gated=True)

    lines = observe.read_jsonl(observe.bench_history_path())
    assert lines and lines[-1]["gated"] is True
