"""벤더 감지 정확도 판정(AC-B-009-4 · SC-8)과 강한-판정 선택 규칙을 고정한다.

SC-8 의 두 기준은 성격이 다르다 — 오탐은 **0건 hard fail**, 미탐은 **≤10%** 다.
그래서 둘의 경계가 흐려지면 관문의 강도가 조용히 달라진다. 여기서 고정하는 것은
"무엇을 오탐으로, 무엇을 미탐으로, 무엇을 아예 세지 않기로 하는가" 하나다.
"""

import pathlib
import sys

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import bench, fetcher  # noqa: E402
from open_reach.models import WafVerdict  # noqa: E402


@pytest.mark.parametrize(
    "expected,detected,want",
    [
        ("cloudflare", "cloudflare", "correct"),
        ("none", "none", "correct"),
        # 다른 벤더로 **단정**했다 — SC-8 이 0건을 요구하는 쪽.
        ("cloudflare", "akamai", "false_positive"),
        # 방어가 없는 곳에 벤더를 붙인 것도 같은 단정이다.
        ("none", "cloudflare", "false_positive"),
        # 있는 벤더를 흘렸다 — SC-8 이 10% 를 허용하는 쪽.
        ("cloudflare", "none", "false_negative"),
        ("cloudflare", "unknown_challenge", "false_negative"),
        # 막히긴 했는데 기대 라벨이 none — 두 기준 어디에도 안 들어간다.
        ("none", "unknown_challenge", "unresolved"),
        # 응답 자체가 없었다. 감지기의 실패가 아니라 측정의 부재다.
        ("cloudflare", None, "unmeasured"),
        ("none", None, "unmeasured"),
    ],
)
def test_classify_vendor(expected, detected, want):
    assert bench.classify_vendor(expected, detected) == want


def test_every_verdict_is_declared():
    """집계 키가 선언 집합 밖으로 새면 render 가 조용히 항목을 빠뜨린다."""
    for expected in ("cloudflare", "none"):
        for detected in ("cloudflare", "akamai", "none", "unknown_challenge", None):
            assert bench.classify_vendor(expected, detected) in bench.VENDOR_VERDICTS


def test_unmeasured_is_not_counted_as_a_miss():
    """네트워크 장애가 감지기 실력으로 둔갑하면 SC-8 은 회선 상태를 재게 된다."""
    counts = {k: 0 for k in bench.VENDOR_VERDICTS}
    misses: list[str] = []
    bench._tally_vendor({"id": "x", "waf_expected": "cloudflare"}, None, counts, misses)
    assert counts["unmeasured"] == 1
    assert counts["false_negative"] == 0
    assert misses == []


def test_miss_records_which_entry():
    counts = {k: 0 for k in bench.VENDOR_VERDICTS}
    misses: list[str] = []
    bench._tally_vendor(
        {"id": "cf-001", "waf_expected": "cloudflare"}, "akamai", counts, misses
    )
    assert counts["false_positive"] == 1
    assert misses and "cf-001" in misses[0] and "akamai" in misses[0]


def test_stronger_verdict_wins_over_a_later_clean_response():
    """차단을 본 뒤 평범한 응답을 받아도 차단 사실이 지워지면 안 된다.

    `none` 의 confidence 는 1.0 이고 `unknown_challenge` 는 0.4 다. 확신도만으로
    고르면 리다이렉트 끝의 200 하나가 벤더 판정을 통째로 덮는다.
    """
    site = "https://a.example/x"
    trace: dict = {}
    fetcher._note_vendor(trace, WafVerdict("unknown_challenge", 0.4, ["blocked"], []), site)
    fetcher._note_vendor(trace, WafVerdict("none", 1.0, [], []), site)
    assert trace["waf_vendor"] == "unknown_challenge"

    # 반대로 실제 벤더가 잡히면 그것이 이긴다.
    fetcher._note_vendor(trace, WafVerdict("cloudflare", 1.0, ["cf-ray"], []), site)
    assert trace["waf_vendor"] == "cloudflare"
    # 판정을 만든 응답의 출처가 함께 남는다 — bench 가 귀속을 확인할 수 있어야 한다.
    assert trace["waf_origin"] == site


def test_note_vendor_without_trace_is_a_noop():
    """trace 를 안 넘기는 호출부(일반 fetch)가 예외로 죽지 않는다."""
    fetcher._note_vendor(None, WafVerdict("cloudflare", 1.0, [], []), "https://a.example/")


# ── 교차 오리진 귀속 (H4) ───────────────────────────────────────────────


def test_same_site_requires_exact_host():
    # 스킴과 대소문자만 정규화한다.
    assert bench.same_site("http://a.example/x", "https://A.example/y")
    # `www` 교차는 **다른 호스트**다 — apex 는 WAF 없이, www 만 Cloudflare 뒤에
    # 두는 배치가 실재한다. www 를 벗기면 그 판정이 apex 의 실력으로 계상된다.
    assert not bench.same_site("https://www.a.example/x", "https://a.example/y")
    # 서브도메인도 다른 사이트다 — WAF 는 호스트 단위로 붙는다.
    assert not bench.same_site("https://cdn.a.example/x", "https://a.example/y")
    assert not bench.same_site("https://b.example/x", "https://a.example/y")
    assert not bench.same_site(None, "https://a.example/y")


def test_cross_origin_verdict_is_not_scored():
    """다른 사이트에서 온 판정은 맞음으로도 틀림으로도 세지 않는다.

    리디렉션이 사이트 B 로 넘어가 거기서 cloudflare 를 만나면, 그 판정을 항목 A 의
    정답 라벨과 대조하는 순간 SC-8 은 겨냥하지 않은 사이트의 감지 결과를 채점한다.
    """
    assert bench.classify_vendor("cloudflare", "cloudflare", attributed=False) == "unresolved"
    assert bench.classify_vendor("none", "cloudflare", attributed=False) == "unresolved"
    # 귀속되면 원래대로 채점된다.
    assert bench.classify_vendor("cloudflare", "cloudflare", attributed=True) == "correct"
    # 판정 자체가 없으면 귀속과 무관하게 측정 불가다.
    assert bench.classify_vendor("cloudflare", None, attributed=False) == "unmeasured"


# ── 정답 라벨 표기 (M1) ─────────────────────────────────────────────────


def test_expected_vendor_reads_both_spellings():
    assert bench.expected_vendor({"expected": {"waf_vendor": "akamai"}}) == "akamai"
    assert bench.expected_vendor({"waf_expected": "akamai"}) == "akamai"
    assert bench.expected_vendor({}) == "none"


def test_conflicting_labels_are_a_governance_violation():
    """두 자리에 다른 정답을 적어 두고 유리한 쪽이 채점되게 할 수 없다."""
    entry = {"id": "x-1", "waf_expected": "akamai", "expected": {"waf_vendor": "cloudflare"}}
    assert bench._label_conflict(entry) is not None
    entry["expected"]["waf_vendor"] = "akamai"
    assert bench._label_conflict(entry) is None


# ── SC-8 게이트 (H3) ────────────────────────────────────────────────────


def test_sc8_summary_denominator_excludes_unmeasured():
    summary = bench.sc8_summary(
        {"correct": 8, "false_positive": 0, "false_negative": 1, "unresolved": 1, "unmeasured": 5}
    )
    assert summary["measurable"] == 10
    assert summary["miss_rate"] == 0.1


def test_sc8_gate_blocks_false_positive_and_high_miss_rate():
    fp = bench.sc8_summary({"correct": 9, "false_positive": 1, "false_negative": 0,
                            "unresolved": 0, "unmeasured": 0})
    assert bench.sc8_violations(fp, attempted=True)

    miss = bench.sc8_summary({"correct": 8, "false_positive": 0, "false_negative": 2,
                              "unresolved": 0, "unmeasured": 0})
    assert bench.sc8_violations(miss, attempted=True)

    ok = bench.sc8_summary({"correct": 9, "false_positive": 0, "false_negative": 1,
                            "unresolved": 0, "unmeasured": 0})
    assert bench.sc8_violations(ok, attempted=True) == []


def test_sc8_gate_blocks_when_nothing_was_measurable():
    """"한 건도 재지 못했다"는 통과가 아니다.

    이 단언이 없으면 감지 경로를 통째로 망가뜨려 전 항목을 `unmeasured` 로 만드는
    변형이 오탐 0건·미탐 0건으로 SC-8 을 통과한다.
    """
    dead = bench.sc8_summary({"correct": 0, "false_positive": 0, "false_negative": 0,
                              "unresolved": 0, "unmeasured": 12})
    assert bench.sc8_violations(dead, attempted=True)
    # 애초에 돌린 항목이 없으면 잴 것도 없다 — 그것까지 실패로 만들지는 않는다.
    assert bench.sc8_violations(dead, attempted=False) == []
