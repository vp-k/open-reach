"""벤더 범위 선언(G-8)과 G-1 의 관계를 고정한다.

R1 은 실측으로 4벤더만 확보했고(docs/r1-report.md §4), SPEC 「Round 경계」는 9종 전체를
R2 로 둔다. 그래서 **기준(≥2건)은 그대로 두고 범위를 명시**하는 쪽을 택했다. 이 테스트가
지키는 것은 단 하나 — 범위를 좁히는 일이 **조용히** 일어나지 않는다는 것이다.
"""

import pathlib
import sys

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import bench  # noqa: E402
from open_reach.models import WAF_VENDORS  # noqa: E402


def _entry(entry_id: str, vendor: str, *, negative: str | None = None) -> dict:
    return {
        "id": entry_id,
        "url": f"https://example.invalid/{entry_id}",
        "tier": 1,
        "waf_expected": vendor,
        "added_reason": "테스트",
        "negative_case": negative,
        "expected": None
        if negative
        else {
            "title_contains": "x",
            "body_contains": None,
            "min_chars": None,
            "normalized_hash": None,
        },
    }


def _battery(vendors: list[str], **header) -> dict:
    entries = []
    for vendor in vendors:
        entries += [_entry(f"{vendor}-1", vendor), _entry(f"{vendor}-2", vendor)]
    entries.append(_entry("neg", vendors[0], negative="waf_challenge"))
    return {"role": "production", "entries": entries, **header}


def test_missing_scope_still_demands_all_nine():
    """키를 빠뜨리는 것이 범위를 줄이는 가장 싼 방법이 되면 안 된다."""
    battery = _battery(["cloudflare", "akamai"])
    scope, violations = bench.vendor_scope(battery)
    assert scope == tuple(WAF_VENDORS)
    assert violations == []
    with pytest.raises(bench.GovernanceError) as exc:
        bench.check_governance(battery, shipped=True)
    assert "G-1" in str(exc.value)


def test_declared_scope_narrows_g1_but_keeps_the_bar():
    battery = _battery(
        ["cloudflare", "akamai"],
        vendor_scope=["cloudflare", "akamai"],
        vendor_scope_reason="R1 실측 확보분",
    )
    bench.check_governance(battery, shipped=True)  # 통과해야 한다

    # 기준 자체는 그대로다 — 범위 안 벤더가 1건이면 여전히 fail
    thin = _battery(["cloudflare", "akamai"], vendor_scope=["cloudflare", "akamai"],
                    vendor_scope_reason="R1 실측 확보분")
    thin["entries"] = [e for e in thin["entries"] if e["id"] != "akamai-2"]
    with pytest.raises(bench.GovernanceError) as exc:
        bench.check_governance(thin, shipped=True)
    assert "akamai" in str(exc.value)


def test_scope_without_reason_is_a_violation():
    """이유가 없으면 vendor_scope 는 '그때그때 통과하도록 적는 값' 이 된다."""
    battery = _battery(
        ["cloudflare", "akamai"], vendor_scope=["cloudflare", "akamai"]
    )
    with pytest.raises(bench.GovernanceError) as exc:
        bench.check_governance(battery, shipped=True)
    assert "G-8" in str(exc.value)


def test_unknown_vendor_in_scope_is_a_violation():
    battery = _battery(
        ["cloudflare", "akamai"],
        vendor_scope=["cloudflare", "akamai", "not_a_real_waf"],
        vendor_scope_reason="오타",
    )
    with pytest.raises(bench.GovernanceError) as exc:
        bench.check_governance(battery, shipped=True)
    assert "G-8" in str(exc.value)


def test_shipped_battery_declares_scope_and_meets_it():
    """출하 배터리 파일 자체가 거버넌스를 통과하는지 — 파일과 코드가 갈라지지 않게."""
    path = pathlib.Path(__file__).resolve().parents[2] / "bench" / "battery.yaml"
    battery = bench.load_battery(path)
    bench.check_governance(battery, shipped=True)
    scope, violations = bench.vendor_scope(battery)
    assert violations == []
    assert set(scope) == {"cloudflare", "akamai", "fastly", "imperva"}
