"""전체 리뷰 델타 재리뷰 반영 3건 (codex R11 델타).

- [MEDIUM] engine.cmd_bench: SC-8 위반(벤더 오탐/미탐)만으로도 exit-3 인데 그 실행이
  `gated=False` 로 이력화되면, 벤더를 잘못 귀속한 신뢰 불가 돌파율이 다음 회귀 감사의
  baseline 이 된다. SC-8 위반 실행도 gated 로 표시하되, SC-8 은 증적 렌더는 남긴다.
- [MEDIUM] fetcher._attempt_step: 추종한 중간 3xx 홉의 **실제 URL** 을 attempt.endpoint 에
  남긴다. 없으면 SC-9 감사가 최종 URL 만 보고 실제 회선 경로(a→b/private→c)를 못 짠다.
- [LOW] policy._port_of: 명시 포트 `0` 을 기본 포트로 뭉개지 않는다. `http://h:0/` 가
  `:80` 오리진으로 정규화되면 정확한 픽스처 오리진 매칭(유일한 SSRF 예외)이 흐려진다.
"""

import argparse
import pathlib
import sys
from urllib.parse import urlsplit

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import engine, fetcher, models, policy, transport  # noqa: E402


# --------------------------------------------------------------------------- #
# MEDIUM 1 — SC-8 위반 실행은 baseline 에서 제외되도록 gated 로 기록된다
# --------------------------------------------------------------------------- #

def _bench_args() -> argparse.Namespace:
    return argparse.Namespace(
        no_browser=False, tier=1, runs=1, shuffle=False,
        timeout=5.0, battery=None, holdout=False,
    )


def _stub_bench_env(monkeypatch, report):
    monkeypatch.setattr(engine, "_battery_path", lambda args: (pathlib.Path("x"), False))
    monkeypatch.setattr(engine.bench_mod, "load_battery", lambda p: {})
    monkeypatch.setattr(engine.bench_mod, "check_governance", lambda b, *, shipped: None)
    monkeypatch.setattr(engine.api_index_mod, "load_cached", lambda p: None)
    monkeypatch.setattr(engine.bench_mod, "run_battery", lambda *a, **k: report)
    rendered = {"called": False}
    monkeypatch.setattr(
        engine.bench_mod, "render",
        lambda r: rendered.__setitem__("called", True) or "BENCH_RESULT: stub",
    )
    captured = {}
    monkeypatch.setattr(
        engine.bench_mod, "record_run",
        lambda report, *, battery_path, gated=False: captured.update(gated=gated),
    )
    return captured, rendered


def _report(*, fp=0, measurable=1, false_negative=0, neg=None, meas=None):
    return {
        "tier": 1, "runs": 1, "total": 3,
        "negative_violations": neg or [],
        "measurement_violations": meas or [],
        "vendor_sc8": {
            "false_positive": fp, "measurable": measurable,
            "unmeasured": 0, "miss_rate": (false_negative / measurable) if measurable else None,
            "false_negative": false_negative,
        },
    }


def test_sc8_failure_is_recorded_gated(monkeypatch):
    captured, rendered = _stub_bench_env(monkeypatch, _report(fp=1))
    rc = engine.cmd_bench(_bench_args())
    assert rc == engine.EXIT_GATE
    assert captured["gated"] is True, "SC-8 오탐 실행이 baseline 으로 새면 안 된다"
    # SC-8 은 증적을 남긴다 — 렌더는 호출되어야 한다 (측정 불가와 달리).
    assert rendered["called"] is True


def test_clean_run_is_not_gated(monkeypatch):
    captured, rendered = _stub_bench_env(monkeypatch, _report())
    rc = engine.cmd_bench(_bench_args())
    assert rc == engine.EXIT_OK
    assert captured["gated"] is False
    assert rendered["called"] is True


def test_measurement_failure_gated_without_render(monkeypatch):
    captured, rendered = _stub_bench_env(monkeypatch, _report(meas=["잴 수 없었다"]))
    rc = engine.cmd_bench(_bench_args())
    assert rc == engine.EXIT_GATE
    assert captured["gated"] is True
    # 측정 자체가 깨진 실행은 렌더 없이 즉시 정지한다.
    assert rendered["called"] is False


# --------------------------------------------------------------------------- #
# MEDIUM 2 — 추종한 리디렉션 홉의 실제 URL 이 attempt.endpoint 에 남는다
# --------------------------------------------------------------------------- #

def test_redirect_attempt_records_real_hop_url(monkeypatch):
    def fake_request(url, *, timeout, impersonate, hop_check, on_dispatch, **kw):
        # a → 302 b/private-path 를 추종한 뒤 회선 실패로 끝났다고 가정.
        on_dispatch("http://b.example/private-path", 302, 12)
        raise transport.NetworkError("stop after hop")

    monkeypatch.setattr(transport, "request", fake_request)

    attempts: list[models.Attempt] = []
    step = {"impersonate": None, "url_variant": "original"}
    req = models.FetchRequest(url="http://a.example/", timeout_s=5.0)

    result = fetcher._attempt_step(req, step, deadline=1e18, attempts=attempts, budget={"used": 0})

    assert result is None  # 네트워크 실패 → 다음 지문으로
    hop = attempts[0]
    assert hop.outcome == "redirect"
    assert hop.endpoint == "http://b.example/private-path", "실제 홉 URL 이 감사에 남아야 한다"
    # url_variant 는 닫힌 집합이라 경로를 담을 수 없다 — 그래서 endpoint 가 필요하다.
    assert hop.url_variant == "original"


# --------------------------------------------------------------------------- #
# LOW 3 — 명시 포트 0 은 기본 포트로 뭉개지 않는다 (픽스처 오리진 경계 보호)
# --------------------------------------------------------------------------- #

def test_explicit_port_zero_is_preserved():
    assert policy._port_of(urlsplit("http://127.0.0.1:0/")) == 0
    assert policy.origin_of("http://127.0.0.1:0/") == "http://127.0.0.1:0"


def test_unspecified_port_still_defaults():
    assert policy._port_of(urlsplit("http://127.0.0.1/")) == 80
    assert policy._port_of(urlsplit("https://127.0.0.1/")) == 443
    assert policy.origin_of("https://127.0.0.1/") == "https://127.0.0.1:443"


def test_port_zero_does_not_match_fixture_origin(monkeypatch):
    monkeypatch.setenv("OPENREACH_FIXTURE_BASE", "http://127.0.0.1:80")
    assert policy.fixture_origin() == "http://127.0.0.1:80"
    # `:0` 은 `:80` 픽스처 오리진과 다르다 — SSRF 예외로 새지 않는다.
    assert policy.origin_of("http://127.0.0.1:0/") != policy.fixture_origin()
