"""지문 노후 경고(SPEC §263) — `last_reviewed` 90일 초과 판정과 경고.

여기서 지키는 계약:
- `stale_profiles` 는 `today` 를 주입받는 순수 함수다 — 결정적이고 부작용이 없다.
- 임계(기본 90일)를 **넘긴 경우만** 노후다. 임계와 같거나 이하는 노후가 아니다(경계).
- `last_reviewed` 가 없거나 파싱 불가하면 신선도를 증명할 수 없으므로 함께 잡는다
  (`days_since=None`) — 검토되지 않은 지문을 조용히 통과시키지 않는다(NG-10 정신).
- `warn_stale` 은 노후가 있을 때만 stderr(주입 스트림)로 한 번 쓴다. 없으면 조용하다.

네트워크를 타지 않는다.
"""

import datetime as dt
import io
import pathlib
import sys

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import profiles  # noqa: E402


def _p(vendor, last_reviewed):
    return {"vendor": vendor, "last_reviewed": last_reviewed}


TODAY = dt.date(2026, 9, 2)


# ─── stale_profiles: 임계 판정 ───

def test_fresh_is_not_stale():
    # 44일 전 — 90일 임계 미만이라 노후가 아니다.
    out = profiles.stale_profiles([_p("cloudflare", "2026-07-20")], today=TODAY)
    assert out == []


def test_over_threshold_is_stale():
    # 100일 전 — 임계 초과.
    reviewed = (TODAY - dt.timedelta(days=100)).isoformat()
    out = profiles.stale_profiles([_p("akamai", reviewed)], today=TODAY)
    assert len(out) == 1
    assert out[0]["vendor"] == "akamai"
    assert out[0]["days_since"] == 100


def test_exactly_threshold_is_not_stale():
    # 정확히 90일 — "초과" 가 아니므로 노후가 아니다(경계 off-by-one 고정).
    reviewed = (TODAY - dt.timedelta(days=90)).isoformat()
    assert profiles.stale_profiles([_p("f5", reviewed)], today=TODAY) == []


def test_one_day_over_threshold_is_stale():
    reviewed = (TODAY - dt.timedelta(days=91)).isoformat()
    out = profiles.stale_profiles([_p("f5", reviewed)], today=TODAY)
    assert out and out[0]["days_since"] == 91


def test_custom_threshold():
    reviewed = (TODAY - dt.timedelta(days=45)).isoformat()
    assert profiles.stale_profiles([_p("x", reviewed)], today=TODAY) == []
    out = profiles.stale_profiles([_p("x", reviewed)], today=TODAY, threshold_days=30)
    assert out and out[0]["days_since"] == 45


# ─── 결측·파싱 불가 ───

def test_missing_date_is_flagged_with_none():
    out = profiles.stale_profiles([_p("y", None)], today=TODAY)
    assert out == [{"vendor": "y", "last_reviewed": None, "days_since": None}]


def test_unparseable_date_is_flagged_with_none():
    out = profiles.stale_profiles([_p("z", "not-a-date")], today=TODAY)
    assert len(out) == 1
    assert out[0]["days_since"] is None
    assert out[0]["last_reviewed"] == "not-a-date"


def test_mixed_set_partitions_correctly():
    ps = [
        _p("fresh", "2026-08-30"),                               # 3일 — 신선
        _p("old", (TODAY - dt.timedelta(days=120)).isoformat()),  # 120일 — 노후
        _p("nodate", None),                                      # 결측
    ]
    out = profiles.stale_profiles(ps, today=TODAY)
    vendors = {e["vendor"] for e in out}
    assert vendors == {"old", "nodate"}  # fresh 는 빠진다


# ─── warn_stale: 부작용과 once-guard ───

def test_warn_writes_when_stale():
    profiles._warned_stale = False
    buf = io.StringIO()
    reviewed = (TODAY - dt.timedelta(days=100)).isoformat()
    profiles.warn_stale([_p("akamai", reviewed)], today=TODAY, stream=buf)
    msg = buf.getvalue()
    assert "akamai" in msg and "100일" in msg
    assert "90일 초과" in msg


def test_warn_silent_when_all_fresh():
    profiles._warned_stale = False
    buf = io.StringIO()
    profiles.warn_stale([_p("cloudflare", "2026-08-30")], today=TODAY, stream=buf)
    assert buf.getvalue() == ""  # 노후가 없으면 조용하다


def test_warn_only_once_per_process():
    profiles._warned_stale = False
    reviewed = (TODAY - dt.timedelta(days=100)).isoformat()
    b1, b2 = io.StringIO(), io.StringIO()
    profiles.warn_stale([_p("akamai", reviewed)], today=TODAY, stream=b1)
    profiles.warn_stale([_p("akamai", reviewed)], today=TODAY, stream=b2)
    assert b1.getvalue() != ""
    assert b2.getvalue() == ""  # 두 번째는 조용하다(중복 경고 방지)


def test_warn_returns_stale_list():
    profiles._warned_stale = False
    reviewed = (TODAY - dt.timedelta(days=100)).isoformat()
    out = profiles.warn_stale([_p("akamai", reviewed)], today=TODAY, stream=io.StringIO())
    assert out and out[0]["vendor"] == "akamai"
