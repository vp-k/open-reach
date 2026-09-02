"""브라우저 티어(T2) 단위 검증 — A8 준수 불변식과 지연 설치 계약.

여기서 지키는 계약:
- browser_available() 는 항상 (bool, str) 이며, patchright 부재를 예외로 새지 않고
  (False, 사유) 로 강등한다 (SC-7 지연 설치 · NG-10 세탁 금지).
- _Cleanup 는 임시 프로필 삭제를 LIFO 로 보장하고, 정리 함수 하나가 던져도 나머지를
  계속 실행한다 (A8-1 신원 비지속의 기계적 근거).
- browser_fetch 는 정상 경로에서 임시 프로필을 남기지 않는다 (2회 실행 잔존 0).
"""

import pathlib
import sys

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import browser as bt  # noqa: E402


# ─── BrowserOutcome 기본값 ───

def test_outcome_defaults():
    o = bt.BrowserOutcome(ok=True, status=200, html="<p>x</p>", final_url="http://h/")
    assert o.headers == {}
    assert o.elapsed_ms == 0
    assert o.error is None


def test_outcome_frozen():
    o = bt.BrowserOutcome(ok=False, status=0, html="", final_url="u")
    with pytest.raises(Exception):
        o.ok = True  # frozen dataclass — 취득 결과는 불변


# ─── _Cleanup LIFO / discard / 예외 격리 ───

def test_cleanup_lifo_order():
    c = bt._Cleanup()
    order = []
    c.push(lambda: order.append("a"))
    c.push(lambda: order.append("b"))
    c.push(lambda: order.append("c"))
    c.run()
    assert order == ["c", "b", "a"]  # 마지막에 연 프로필부터 회수


def test_cleanup_discard():
    c = bt._Cleanup()
    order = []
    fn = lambda: order.append("removed")
    c.push(fn)
    c.push(lambda: order.append("kept"))
    c.discard(fn)
    c.run()
    assert order == ["kept"]


def test_cleanup_discard_absent_is_silent():
    c = bt._Cleanup()
    c.discard(lambda: None)  # 스택에 없어도 예외 없이 무시


def test_cleanup_swallows_and_continues():
    c = bt._Cleanup()
    order = []

    def boom():
        raise RuntimeError("정리 중 예외")

    c.push(lambda: order.append("first"))
    c.push(boom)  # 이게 던져도
    c.push(lambda: order.append("third"))
    c.run()  # 나머지가 계속 실행돼야 한다
    assert order == ["third", "first"]
    assert c._stack == []  # 예외에도 스택은 비워진다


def test_cleanup_run_empties_stack():
    c = bt._Cleanup()
    c.push(lambda: None)
    c.run()
    assert c._stack == []
    c.run()  # 두 번째 run 은 no-op


# ─── browser_available 계약 ───

def test_available_returns_bool_str():
    ok, why = bt.browser_available()
    assert isinstance(ok, bool)
    assert isinstance(why, str)
    # 설치돼 있으면 사유는 비고, 없으면 사유가 있다 (상호 배타)
    assert (ok and why == "") or (not ok and why != "")


def test_available_false_on_missing_patchright(monkeypatch):
    # patchright.sync_api import 를 실패시켜 미설치 환경을 시뮬레이션한다.
    monkeypatch.setitem(sys.modules, "patchright", None)
    monkeypatch.setitem(sys.modules, "patchright.sync_api", None)
    ok, why = bt.browser_available()
    assert ok is False
    assert "patchright" in why  # 사유에 원인 명시 (NG-10 — 다른 이유로 세탁 금지)


# ─── browser_fetch: 오프라인 렌더 + 프로필 잔존 0 (설치 시에만) ───

_HAVE_BROWSER = bt.browser_available()[0]

_DATA_URL = (
    "data:text/html,"
    "<html><head><title>Just a moment...</title></head><body>"
    "<div class=challenge-running>Checking your browser</div>"
    "<script>document.title='rendered';"
    "document.body.innerHTML="
    "'<article>' + 'OPENREACH-UNIT-MARKER '.repeat(40) + '</article>';"
    "</script></body></html>"
)


@pytest.mark.skipif(not _HAVE_BROWSER, reason="patchright 미설치 — 지연 설치 계약상 정상 스킵")
def test_fetch_renders_js_and_cleans_profile():
    import glob
    import tempfile

    before = set(glob.glob(str(pathlib.Path(tempfile.gettempdir()) / (bt._PROFILE_PREFIX + "*"))))
    out = bt.browser_fetch(_DATA_URL, timeout_s=15)
    assert out.ok is True
    assert "OPENREACH-UNIT-MARKER" in out.html  # JS 가 실제로 DOM 을 다시 썼다
    assert "challenge-running" not in out.html  # 챌린지 노드가 렌더 후 사라졌다
    after = set(glob.glob(str(pathlib.Path(tempfile.gettempdir()) / (bt._PROFILE_PREFIX + "*"))))
    assert after <= before  # 임시 프로필 잔존 0 (A8-1)


@pytest.mark.skipif(not _HAVE_BROWSER, reason="patchright 미설치 — 지연 설치 계약상 정상 스킵")
def test_fetch_never_raises_on_unexpected_error(monkeypatch):
    """폴백 격리(M1): 예기치 못한 내부 오류도 크래시로 새지 않고 강등하며 프로필도 정리한다."""
    import glob
    import tempfile

    import patchright.sync_api as pw

    def boom(*a, **k):
        raise RuntimeError("patchright 내부 붕괴 시뮬레이션")  # PWError 가 아님

    monkeypatch.setattr(pw, "sync_playwright", boom)
    pat = str(pathlib.Path(tempfile.gettempdir()) / (bt._PROFILE_PREFIX + "*"))
    before = set(glob.glob(pat))
    out = bt.browser_fetch("http://example.invalid/", timeout_s=5)
    assert out.ok is False  # 예외가 밖으로 새지 않았다
    assert out.error == "network"  # 유효한 실패 사유로 강등
    after = set(glob.glob(pat))
    assert after <= before  # 예외 경로에서도 임시 프로필 잔존 0


@pytest.mark.skipif(not _HAVE_BROWSER, reason="patchright 미설치 — 지연 설치 계약상 정상 스킵")
def test_fetch_twice_leaves_no_residue():
    import glob
    import tempfile

    pat = str(pathlib.Path(tempfile.gettempdir()) / (bt._PROFILE_PREFIX + "*"))
    before = set(glob.glob(pat))
    bt.browser_fetch(_DATA_URL, timeout_s=15)
    bt.browser_fetch(_DATA_URL, timeout_s=15)
    after = set(glob.glob(pat))
    assert after <= before  # 2회 실행에도 신원(프로필) 지속 없음


# ─── _ssrf_allow: NG-11 프리엠티브 SSRF 판정 (Critical 회귀, 브라우저 불요) ───
#   codex 리뷰 Critical: 공개→사설→공개 리디렉션의 중간 홉을 사후 final_url 검사가
#   놓친다. route 가드는 매 요청을 이 함수로 사전 판정해 사설 홉의 연결 자체를 막는다.

def test_ssrf_allow_permits_non_network_schemes():
    # data:·blob:·about: 는 호스트로의 egress 가 없다 — 인라인 렌더를 막지 않는다.
    assert bt._ssrf_allow("data:text/html,<p>x</p>") is True
    assert bt._ssrf_allow("about:blank") is True
    assert bt._ssrf_allow("blob:https://example.com/abc") is True


def test_ssrf_allow_blocks_loopback():
    # 리터럴 IP 라 DNS 없이 결정적. 픽스처 예외 포트가 아니면 루프백은 차단.
    assert bt._ssrf_allow("http://127.0.0.1:9/x") is False


def test_ssrf_allow_blocks_metadata():
    # 클라우드 메타데이터 주소는 어떤 예외보다 우선해 차단된다.
    assert bt._ssrf_allow("http://169.254.169.254/latest/meta-data/") is False


def test_ssrf_allow_permits_public(monkeypatch):
    # 공개 대역은 통과. check_url 을 스텁해 DNS 의존 없이 판정 경로만 검증.
    from open_reach import policy as pol

    monkeypatch.setattr(pol, "check_url", lambda u: pol.PolicyVerdict(True, None, "ok"))
    assert bt._ssrf_allow("http://example.com/page") is True


def test_ssrf_allow_fails_closed_on_unresolvable(monkeypatch):
    # DNS 실패는 fail-closed — 코드베이스 전역(hop_check·robots 프리체크) 관례와 일치.
    from open_reach import policy as pol

    def _boom(u):
        raise pol.UnresolvableHost("DNS 실패")

    monkeypatch.setattr(pol, "check_url", _boom)
    assert bt._ssrf_allow("http://nx.invalid/x") is False
