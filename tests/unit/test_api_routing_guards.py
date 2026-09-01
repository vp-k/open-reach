"""Phase 0 라우팅 가드의 **변이 사멸** 테스트 (리뷰 라운드 2).

라운드 2 지적의 절반은 "구현은 있는데 그 구현을 지워도 테스트가 초록"이었다.
그래서 여기서 고정하는 것은 동작이 아니라 **가드를 제거했을 때 빨개지는가**다.
각 테스트에 죽여야 할 변이를 적어 둔다.

루프백 픽스처 서버를 테스트 안에서 띄운다 — SPEC 이 인정한 예외
(`OPENREACH_FIXTURE_BASE` + 루프백 IP 리터럴)를 그대로 쓴다.
"""

import http.server
import pathlib
import sys
import threading

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import api_index, policy, transport  # noqa: E402

ROBOTS = "User-agent: *\nDisallow: /blocked\n"
HITS: dict[str, int] = {}
# robots.txt 를 리디렉션 사슬로 만들지 여부 (라운드 3 — robots 홉 상한 검증용)
ROBOTS_REDIRECTS = {"on": False}
# 사슬 깊이는 **전송 계층이 실제로 허용하는 최대치**에 맞춘다. 라운드 4 의 회귀 테스트는
# 2홉짜리 사슬만 썼는데, 그러면 "상한 2 로 다시 도입" 같은 더 느슨한 변이가 그대로
# 통과한다 (라운드 5 HIGH-1). 상수에서 유도해 MAX_REDIRECTS 가 바뀌어도 따라간다.
ROBOTS_CHAIN_END = transport.MAX_REDIRECTS + 1  # /robots-{END}.txt 가 규칙을 서빙한다


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # 조용히
        pass

    def _body(self, status: int, text: str, ctype: str = "text/html; charset=utf-8"):
        raw = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _redirect(self, to: str):
        self.send_response(302)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self.path
        HITS[path] = HITS.get(path, 0) + 1
        if path == "/robots.txt":
            if ROBOTS_REDIRECTS["on"]:
                self._redirect("/robots-2.txt")
            else:
                self._body(200, ROBOTS, "text/plain; charset=utf-8")
        elif path.startswith("/robots-") and path.endswith(".txt"):
            index = int(path[len("/robots-"):-len(".txt")])
            if index < ROBOTS_CHAIN_END:
                self._redirect(f"/robots-{index + 1}.txt")
            else:
                self._body(200, ROBOTS, "text/plain; charset=utf-8")
        elif path == "/to-blocked":
            self._redirect("/blocked")
        elif path == "/blocked":
            # 여기에 닿았다는 것은 robots 재검사가 없었다는 뜻이다.
            self._body(200, "<html><body>should never be fetched</body></html>")
        elif path == "/hop1":
            self._redirect("/hop2")
        elif path == "/hop2":
            self._redirect("/hop3")
        elif path == "/hop3":
            self._body(200, "<html><body>landed</body></html>")
        elif path == "/ep3":
            self._body(200, "<html><body>third endpoint body</body></html>")
        elif path == "/ep4":
            # 여기에 닿았다는 것은 요청 예산이 3 을 넘었다는 뜻이다.
            self._body(200, "<html><body>should never be fetched</body></html>")
        elif path == "/step1":
            self._body(200, '{"v": "1.0.229"}', "application/json")
        elif path == "/step2/1.0.229":
            # **정확히 이 경로만** 답한다. 동결 인수 픽스처는 `/api/step2/` 아래
            # 아무 경로나 답해서 치환 여부를 구분하지 못했다 (라운드 7 MEDIUM).
            self._body(200, "<html><body>substituted onto the wire</body></html>")
        else:
            self._body(404, "<html><body>nope</body></html>")


@pytest.fixture(scope="module")
def server(request):
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(autouse=True)
def _fixture_origin(server, monkeypatch):
    monkeypatch.setenv("OPENREACH_FIXTURE_BASE", server)
    HITS.clear()
    ROBOTS_REDIRECTS["on"] = False
    policy._robots_cache.clear()
    yield
    ROBOTS_REDIRECTS["on"] = False
    policy._robots_cache.clear()


# ── C1 — 리디렉션 목적지의 robots 재검사 ────────────────────────────────────


def test_hop_guard_rechecks_robots_on_redirect(server):
    """죽여야 할 변이: `policy.hop_guard` 에서 robots 검사를 빼고 SSRF 만 남기기.

    원 URL 은 robots 가 허용하지만 302 목적지는 Disallow 다. 목적지 판정을 새로
    보지 않으면 우리는 robots 가 막은 경로를 그대로 받아 온다.
    """
    with pytest.raises(transport.PolicyBlocked) as caught:
        transport.request(
            f"{server}/to-blocked", timeout=5.0, hop_check=policy.hop_guard
        )
    assert "robots" in (caught.value.rule or "")
    assert HITS.get("/blocked", 0) == 0


# ── C1' — 오리진 이탈은 **robots 를 두드리기 전에** 막는다 ──────────────────


def test_foreign_origin_is_rejected_before_any_network_touch(monkeypatch):
    """죽여야 할 변이: `_same_origin_hop` 에서 오리진 검사를 hop_guard 뒤로 옮기기.

    hop_guard 는 목적지의 /robots.txt 를 받으러 나간다. 순서가 뒤집히면 "인덱스 밖
    호스트로는 요청하지 않는다"는 약속을 지키면서도 그 호스트를 이미 한 번 두드린
    뒤가 된다 — 그 요청은 `attempts[]` 에도 남지 않는다.
    """
    calls: list[str] = []
    monkeypatch.setattr(policy, "hop_guard", lambda url: calls.append(url))

    check = api_index._same_origin_hop(policy.origin_of("https://api.example/v1"))
    with pytest.raises(transport.PolicyBlocked) as caught:
        check("https://tracker.example/x")

    assert caught.value.rule == "redirect_hop"
    assert calls == []  # 네트워크로 나가는 가드는 한 번도 불리지 않았다

    # 같은 오리진이면 full guard 를 그대로 탄다 (검사를 건너뛰는 변이 방지).
    check("https://api.example/other")
    assert calls == ["https://api.example/other"]


# ── C2 — 경로 세그먼트 이탈 문자 ────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["a/b", "a\\b", "a%2fb", "a:b", "a?b", "a#b"])
def test_substitute_rejects_segment_escapes(bad):
    """죽여야 할 변이: `SEGMENT_FORBIDDEN` 에서 문자 하나 빼기.

    특히 `\\` — 라운드 1 에서 추가됐지만 이를 단독으로 검증하는 테스트가 없어
    지워도 초록이었다. IIS 계열은 `\\` 를 경로 구분자로 정규화한다.

    점은 **여기에 없다.** R2 SPEC 개정(사용자 승인)으로 `1.0.229` 같은 버전 문자열이
    정상 세그먼트가 됐기 때문이다. 점으로 하는 경로 탈출은 아래 세그먼트 테스트가 막는다.
    """
    with pytest.raises(api_index.Rejected):
        api_index.substitute("https://api.example/v1/{name}", {"name": bad})


@pytest.mark.parametrize("bad", [".", ".."])
def test_substitute_rejects_relative_path_segments(bad):
    """죽여야 할 변이: `SEGMENT_DOT_ONLY` 검사 삭제.

    점을 **문자로** 허용한 개정이 상대 경로 세그먼트까지 열어 주면 안 된다.
    `{version}` 에 `..` 가 바인딩되면 `/v1/crates/serde/../secret` 이 되고,
    서버는 이를 `/v1/crates/secret` 으로 정규화한다.
    """
    with pytest.raises(api_index.Rejected):
        api_index.substitute("https://api.example/v1/{name}", {"name": bad})


def test_substitute_accepts_a_dotted_version_segment():
    """개정이 실제로 통했는지 — 이게 빨개지면 개정이 되돌려진 것이다."""
    assert (
        api_index.substitute("https://api.example/v1/{v}", {"v": "1.0.229"})
        == "https://api.example/v1/1.0.229"
    )


@pytest.mark.parametrize("bad", ["..;a=b", "..;", "a;b", ".. ", "..	", "1.0.0 "])
def test_substitute_rejects_server_normalisable_segments(bad):
    """죽여야 할 변이: `;` 를 SEGMENT_FORBIDDEN 에서 빼거나 공백류 검사 삭제.

    점을 문자로 허용한 개정(R2 SPEC 개정)이 새로 연 표면이다 — 우리 눈에는 점만 든
    평범한 값인데 서버에서 `..` 가 되는 것들이다. Tomcat/Servlet 계열은 경로
    파라미터 `;a=b` 를 떼어 낸 뒤 정규화하고, IIS 계열은 세그먼트 끝의 공백을
    떼어 낸다. `/public/..;a=b/readme` -> `/public/../readme` -> `/readme`.
    """
    with pytest.raises(api_index.Rejected):
        api_index.substitute("https://api.example/v1/{name}", {"name": bad})


def test_substitute_still_accepts_a_triple_dot_segment():
    """`...` 는 막지 않는다 — 어떤 서버도 이를 `..` 로 정규화하지 않는 평범한 이름이다.

    "점이 들어 있으면 일단 막자"로 도망가면 개정이 되돌려진 것과 같아진다.
    """
    assert api_index.substitute(
        "https://api.example/v1/{n}", {"n": "..."}
    ) == "https://api.example/v1/..."


def test_segment_rules_are_pinned():
    """상수 자체를 못 박는다 — 규칙을 읽어 오는 테스트는 규칙을 지키지 못한다 (R5-H2)."""
    assert "." not in api_index.SEGMENT_FORBIDDEN
    assert ";" in api_index.SEGMENT_FORBIDDEN
    assert set(api_index.SEGMENT_DOT_ONLY) == {".", ".."}


def test_substitute_accepts_a_plain_segment():
    assert (
        api_index.substitute("https://api.example/v1/{name}", {"name": "doc"})
        == "https://api.example/v1/doc"
    )


# ── H2 — 실제 요청 총량 (리디렉션·robots 포함) ──────────────────────────────


def test_dispatch_budget_counts_redirect_hops(server):
    """죽여야 할 변이: `transport.request` 홉 루프에서 `_count_dispatch` 지우기.

    `budget[0]` 은 "우리가 부른 횟수"만 센다. 리디렉션은 그 한 번 안에서 회선에
    여러 번 나가므로, 홉을 세지 않으면 항목 하나가 3 회 예산으로 18 회를 쏠 수 있다.
    """
    with pytest.raises(transport.BudgetExceeded) as caught:
        with transport.dispatch_budget(2):
            transport.request(f"{server}/hop1", timeout=5.0)
    assert caught.value.limit == 2
    # 정책 차단과 **다른 타입**이어야 한다 — 같은 타입이면 robots 조회의 fail-open
    # except 절이 예산 초과를 "기본 허용"으로 삼킨다 (라운드 3).
    assert not isinstance(caught.value, transport.PolicyBlocked)
    assert HITS.get("/hop3", 0) == 0  # 마지막 홉까지 가지 못했다


def test_dispatch_budget_allows_what_it_promises(server):
    with transport.dispatch_budget(3):
        response = transport.request(f"{server}/hop1", timeout=5.0)
    assert response.status == 200
    assert response.final_url.endswith("/hop3")


def test_dispatch_meter_is_inert_when_unarmed():
    """일반 fetch 경로(무장 안 함)는 영향받지 않는다."""
    for i in range(50):
        transport._count_dispatch(f"https://a.example/{i}")


def test_dispatch_budget_restores_previous_state():
    with transport.dispatch_budget(5) as outer:
        with transport.dispatch_budget(1):
            pass
        transport._count_dispatch("https://a.example/x")
        assert outer["used"] == 1
    transport._count_dispatch("https://a.example/y")  # 밖에서는 다시 무장 해제


def test_entry_dispatch_budget_is_derived_from_the_contract():
    """상한이 임의 숫자로 바뀌면 여기서 걸린다 — 근거는 주석이 아니라 식이다.

    각 항은 **코드가 실제로 허용하는 최대치**여야 한다. 라운드 2 의 식(`*2+1`)은
    "오리진 하나·홉 한 번"을 가정했지만 코드는 그것을 강제하지 않아, 정상 항목이
    상한에 걸릴 수 있었다 (라운드 3).
    """
    assert api_index.DISPATCH_BUDGET == (
        api_index.REQUEST_BUDGET * (1 + api_index.PHASE0_MAX_REDIRECTS)
        + api_index.REQUEST_BUDGET * (1 + transport.MAX_REDIRECTS)
    )


# ── 라운드 3 — 산식의 전제를 코드가 강제하는가 ──────────────────────────────


def test_phase0_hop_cap_is_enforced_not_assumed(monkeypatch):
    """죽여야 할 변이: `_same_origin_hop` 에서 홉 카운터 지우기.

    지우면 전송 계층 상한(5홉)이 유효 상한이 되고, `DISPATCH_BUDGET` 산식의
    `1 + PHASE0_MAX_REDIRECTS` 항이 거짓이 된다.
    """
    monkeypatch.setattr(policy, "hop_guard", lambda url: None)
    check = api_index._same_origin_hop(policy.origin_of("https://api.example/v1"))
    for i in range(api_index.PHASE0_MAX_REDIRECTS):
        check(f"https://api.example/a{i}")           # 상한까지는 허용
    with pytest.raises(transport.PolicyBlocked) as caught:
        check("https://api.example/over")            # 한 홉 더 — 차단
    assert caught.value.rule == "redirect_hop"


def test_hop_cap_counter_is_per_request(monkeypatch):
    """카운터가 모듈 전역이면 두 번째 엔드포인트가 이유 없이 막힌다."""
    monkeypatch.setattr(policy, "hop_guard", lambda url: None)
    origin = policy.origin_of("https://api.example/v1")
    for _ in range(2):
        check = api_index._same_origin_hop(origin)
        for i in range(api_index.PHASE0_MAX_REDIRECTS):
            check(f"https://api.example/a{i}")  # 새 요청마다 카운터가 0 부터다


def test_redirecting_robots_still_yields_its_disallow(server):
    """죽여야 할 변이: robots 조회에 홉 상한을 다시 거는 것 (라운드 3 의 실수).

    `robots.txt -> /robots-2.txt -> ... -> /robots-{ROBOTS_CHAIN_END}.txt` 로 정규화하는
    사이트가 있다. 사슬 깊이는 전송 계층 상한(`transport.MAX_REDIRECTS`)까지 간다 —
    2홉짜리로 잡으면 "상한 2 로 재도입" 변이를 놓친다 (라운드 5 HIGH-1).
    조회에 상한을 걸면 `robots_verdict` 의 fail-open `except` 가 그 차단을
    "조회 실패 — 기본 허용"으로 삼켜 **빈 규칙을 캐시**한다. 그 결과 `/blocked` 의
    Disallow 가 통째로 사라진다 — 상한을 지키려다 경계를 뚫는 것이다 (라운드 4 HIGH).
    """
    ROBOTS_REDIRECTS["on"] = True
    verdict = policy.robots_verdict(f"{server}/blocked", timeout=5.0)
    assert not verdict.allowed
    assert verdict.rule == "robots"
    assert HITS.get(f"/robots-{ROBOTS_CHAIN_END}.txt", 0) == 1  # 끝까지 따라가 규칙을 읽었다


# ── 라운드 3 — 미터가 실제로 `run()` 에서 무장되는가 ────────────────────────


def _entry(server: str, path: str) -> dict:
    return {
        "host": "127.0.0.1",
        "response_kind": "html",
        "endpoints": [f"{server}{path}"],
    }


def test_run_arms_the_dispatch_meter(server, monkeypatch):
    """죽여야 할 변이: `api_index.run()` 에서 `with transport.dispatch_budget(...)` 지우기.

    기존 미터 테스트는 컨텍스트 매니저를 **테스트가 직접** 열어서, 프로덕션 배선을
    지워도 전부 초록이었다 (라운드 3). 여기서는 `run()` 만 부른다.
    """
    monkeypatch.setattr(api_index, "DISPATCH_BUDGET", 2)
    outcome = api_index.run(
        _entry(server, "/hop2"),  # robots(1) + 본 요청(2) + 홉(3) > 2
        {},
        intent="research",
        timeout=5.0,
        on_attempt=lambda *a, **k: None,
    )
    assert any(note.startswith("budget:") for note in outcome.notes), outcome.notes
    assert outcome.reason is None  # 우리 예산이지 정책 차단이 아니다
    assert HITS.get("/hop3", 0) == 0


def test_run_reports_budget_block_without_a_policy_rule(server, monkeypatch):
    """예산 초과가 `policy_blocked` 로 올라오면 `attempts[].rule` 이 도메인 밖 값을
    실어야 하고, 그러면 SPEC.md:229 의 "route=policy 면 rule non-null" 이 깨진다."""
    monkeypatch.setattr(api_index, "DISPATCH_BUDGET", 1)
    outcome = api_index.run(
        _entry(server, "/hop3"), {}, intent="research", timeout=5.0,
        on_attempt=lambda *a, **k: None,
    )
    assert outcome.reason is None
    assert outcome.policy_rule is None


def test_shipped_budget_covers_a_three_endpoint_multi_origin_entry():
    """정상 항목이 상한에 걸리지 않는다 — 라운드 3 HIGH 의 회귀 시나리오.

    서로 다른 오리진 3개, 각 요청이 자기 오리진 안에서 한 번 리디렉션:
    robots 3 + 본 요청 3 + 홉 3 = 9. 라운드 2 상한(7)이면 8번째에서 막혔다.
    """
    worst_case = (
        api_index.REQUEST_BUDGET * (1 + transport.MAX_REDIRECTS)   # 오리진별 robots + 홉
        + api_index.REQUEST_BUDGET                                 # 본 요청
        + api_index.REQUEST_BUDGET * api_index.PHASE0_MAX_REDIRECTS
    )
    assert api_index.DISPATCH_BUDGET >= worst_case


def test_exhausted_budget_is_not_reported_as_a_policy_block(server, monkeypatch):
    """죽여야 할 변이: `_run_endpoints` 에서 `_reserve` 를 `_guard` 뒤로 되돌리기.

    엔드포인트 4개 중 앞 3개가 404 로 예산(3회)을 다 쓰고, 4번째가 robots Disallow
    경로다. 예산 검사가 `_guard` 뒤에 있으면 **쏘지 않기로 한** 엔드포인트의 robots
    판정이 항목 전체의 결과로 보고되고(`policy_blocked`), 그 판정을 받으려고
    robots.txt 를 실제로 한 번 더 두드린다 — "오리진 수 <= 요청 수"가 거짓이 된다
    (라운드 4 MEDIUM).
    """
    entry = {
        "host": "127.0.0.1",
        "response_kind": "html",
        "endpoints": [
            f"{server}/miss1",
            f"{server}/miss2",
            f"{server}/miss3",
            f"{server}/blocked",
        ],
    }
    outcome = api_index.run(
        entry, {}, intent="research", timeout=5.0, on_attempt=lambda *a, **k: None
    )
    assert outcome.reason is None          # 정책 차단으로 세탁되지 않는다
    assert outcome.policy_rule is None
    assert any(note.startswith("budget:") for note in outcome.notes), outcome.notes
    assert HITS.get("/blocked", 0) == 0


def test_phase0_hop_cap_value_is_pinned():
    """죽여야 할 변이: `PHASE0_MAX_REDIRECTS` 를 1 로 되돌리기.

    위 두 홉 테스트는 상수를 반복 횟수로 쓰므로 값이 바뀌어도 초록이다 (라운드 5 HIGH-2).
    값 자체를 못 박는다 — 2 인 이유는 끝 슬래시 정규화처럼 같은 오리진에서 두 번
    리디렉션하는 API 가 실재하기 때문이고, 1 이면 그 정상 항목이 `redirect_hop`
    정책 위반으로 보고된다 (라운드 4 HIGH-2).
    """
    assert api_index.PHASE0_MAX_REDIRECTS == 2


def test_run_follows_a_legitimate_two_hop_normalisation(server, monkeypatch):
    """상수를 못 박는 것만으로는 부족하다 — `run()` 이 실제로 2홉을 통과해야 한다.

    `/hop1 -> /hop2 -> /hop3` 은 같은 오리진 2홉이다. 상한이 1 이면 두 번째 홉에서
    `PolicyBlocked("redirect_hop")` 이 나고 항목이 정책 위반으로 보고된다.
    """
    outcome = api_index.run(
        _entry(server, "/hop1"), {}, intent="research", timeout=5.0,
        on_attempt=lambda *a, **k: None,
    )
    assert outcome.reason is None, outcome.notes
    assert outcome.policy_rule is None
    assert HITS.get("/hop3", 0) == 1  # 끝까지 따라갔다


# ── 라운드 8 ─────────────────────────────────────────────────────────────


def test_template_cannot_synthesise_a_percent_sequence_at_load():
    """죽여야 할 변이: `_check_request_template` 의 `_bad_path_segment` 검사 지우기.

    값의 `%` 는 막혀 있지만 **템플릿 리터럴의 `%`** 는 막혀 있지 않았다. 1단계가
    `hex="2e"` 라는 멀쩡한 값을 주면 `%{hex}%2e` 가 `%2e%2e` 가 되고, Tomcat 은
    `%xx` 를 디코드한 뒤 정규화하므로 `/readme` 로 올라간다 — 우리가 robots 를
    물어본 경로와 서버가 여는 경로가 갈라진다 (라운드 8 HIGH).
    """
    with pytest.raises(api_index.IndexLoadError):
        api_index._check_request_template(
            "https://api.example/public/%{hex}%2e/readme", "chain[1].request"
        )


def test_substitute_rejects_a_percent_synthesised_by_the_template():
    """로드 검사가 이미 걸렀더라도 요청 시점에서 다시 막는다 — 값 검사와 같은 이유다."""
    with pytest.raises(api_index.Rejected):
        api_index.substitute("https://api.example/public/%{hex}%2e/readme", {"hex": "2e"})


def test_substitute_rejects_a_semicolon_synthesised_by_the_template():
    """같은 계열: 값에는 `;` 가 없지만 리터럴과 붙어 `1.0;a=b` 가 된다.

    값 단위 검사만으로는 잡히지 않는다 — 렌더된 세그먼트를 봐야 잡힌다.
    """
    with pytest.raises(api_index.Rejected):
        api_index.substitute("https://api.example/public/{x};a=b/readme", {"x": "1.0"})


def test_substitute_still_renders_an_ordinary_template():
    """위 세 개가 "일단 다 막자"로 도망간 것이 아님을 못 박는다."""
    assert (
        api_index.substitute("https://api.example/v1/{v}/readme", {"v": "1.0.229"})
        == "https://api.example/v1/1.0.229/readme"
    )


_INDEX_YAML = """version: 1
entries:
  - host: "h.invalid"
    url_pattern: "^/x$"
    source: "{source}"
    verified_at: "2026-09-01"
    response_kind: "html"
    endpoints:
      - "https://h.invalid/a"
"""


def test_source_must_be_https(tmp_path):
    """죽여야 할 변이: `source.startswith("https://")` 를 `("http://", "https://")` 로 되돌리기.

    SPEC:278 은 `https` URL 을 요구한다. `http://` 출처는 중간자가 바꿔 쓸 수 있어
    "검증 가능한 주장"이 되지 못하는데 검증기가 받아 주고 있었다 (라운드 8 MEDIUM).
    """
    good = tmp_path / "good.yaml"
    good.write_text(_INDEX_YAML.format(source="https://ok.invalid/docs"), encoding="utf-8")
    assert len(api_index.load(good)) == 1        # https 는 그대로 로드된다

    bad = tmp_path / "bad.yaml"
    bad.write_text(_INDEX_YAML.format(source="http://attacker.invalid/docs"), encoding="utf-8")
    with pytest.raises(api_index.IndexLoadError):
        api_index.load(bad)


def test_request_budget_value_is_pinned():
    """죽여야 할 변이: `REQUEST_BUDGET` 을 2 로 줄이기.

    아래 엔드포인트 테스트만으로는 부족하다 — 상수를 반복 횟수로 쓰는 산식은 값이
    바뀌어도 초록이기 때문이다 (라운드 5 HIGH-2 와 같은 함정, 라운드 8 MEDIUM).
    """
    assert api_index.REQUEST_BUDGET == 3


def test_endpoints_budget_reaches_exactly_the_third(server):
    """죽여야 할 변이: `REQUEST_BUDGET` 을 2 로 줄이기 / 4 로 늘리기.

    앞의 두 엔드포인트가 404 고 세 번째가 본문을 주는 정상 항목이다. 예산이 2 면
    구제를 포기하고, 4 면 쏘지 않기로 한 네 번째까지 두드린다. 기존 인수 테스트는
    `/api/ep4 == 0` 만 봤고 `/api/ep3 == 1` 은 보지 않았다 (라운드 8 MEDIUM).
    """
    entry = {
        "host": "127.0.0.1",
        "response_kind": "html",
        "endpoints": [
            f"{server}/ep1", f"{server}/ep2", f"{server}/ep3", f"{server}/ep4",
        ],
    }
    outcome = api_index.run(
        entry, {}, intent="research", timeout=5.0, on_attempt=lambda *a, **k: None
    )
    assert outcome.reason is None, outcome.notes
    assert HITS.get("/ep1", 0) == 1
    assert HITS.get("/ep2", 0) == 1
    assert HITS.get("/ep3", 0) == 1
    assert HITS.get("/ep4", 0) == 0


def test_chain_puts_the_substituted_value_on_the_wire(server):
    """죽여야 할 변이: `_run_chain` 의 `substitute(...)` 를 `str(step["request"])` 로 바꾸기.

    동결 인수 테스트(`us-b-010` 의 `ok2hop`)는 2단계 **도달**만 확인한다 — 픽스처가
    `/api/step2/` 아래 아무 경로나 답하므로 치환을 통째로 건너뛰어도 초록이다
    (라운드 7 MEDIUM, 재동결 승인 전까지 deferred). 여기 픽스처는 정확한 경로만
    답하므로, 치환값이 실제로 전선에 실렸는지가 여기서 확정된다.
    """
    entry = {
        "host": "127.0.0.1",
        "response_kind": "html",
        "chain": [
            {
                "request": f"{server}/step1",
                "response_kind": "json",
                "select": "v",
                "value_pattern": r"^[0-9]+\.[0-9]+\.[0-9]+$",
                "bind": "version",
            },
            {"request": server + "/step2/{version}"},
        ],
    }
    outcome = api_index.run(
        entry, {}, intent="research", timeout=5.0, on_attempt=lambda *a, **k: None
    )
    assert outcome.reason is None, outcome.notes
    assert HITS.get("/step2/1.0.229", 0) == 1     # 치환값이 실제로 실렸다
    assert HITS.get("/step2/{version}", 0) == 0   # 템플릿 그대로 나가지 않았다
