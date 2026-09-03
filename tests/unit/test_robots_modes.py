"""robots.txt 모드(R6)의 변이 사멸 테스트.

R6 은 robots 기본값을 fail-closed 차단에서 **미조회**로 뒤집었다. 경계를 완화하는
개정이므로 "완화됐다"가 아니라 **정확히 어디까지 완화됐는가**를 고정한다:

- `off`   — robots.txt 요청이 **0 건**이다 (판정을 받아 놓고 무시하는 것이 아니다).
- `advisory` — 조회하고 보고하되 차단하지 않는다.
- `enforce`  — R5 까지의 동작을 **정확히** 복원한다.
- SSRF 는 세 모드 어디에서도 빠지지 않는다 (NG-11 은 개정 대상이 아니다).

루프백 픽스처 서버를 쓴다 — SPEC 이 인정한 예외(`OPENREACH_FIXTURE_BASE`).
"""

import http.server
import pathlib
import sys
import threading

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import api_index, fetcher, models, policy, transport  # noqa: E402

ROBOTS = "User-agent: *\nDisallow: /\n"  # 전면 Disallow — 가장 강한 차단
HITS: dict[str, int] = {}

_PAGE = (
    "<html><body><article>"
    + ("robots 모드와 무관하게 본문은 본문이다. " * 20)
    + "</article></body></html>"
)


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _body(self, status: int, text: str, ctype: str = "text/html; charset=utf-8"):
        raw = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        HITS[self.path] = HITS.get(self.path, 0) + 1
        if self.path == "/robots.txt":
            self._body(200, ROBOTS, "text/plain; charset=utf-8")
        elif self.path == "/to-private":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/x")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == "/article":
            self._body(200, _PAGE)
        else:
            self._body(404, "<html><body>nope</body></html>")


@pytest.fixture(scope="module")
def server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(autouse=True)
def _isolate(server, monkeypatch):
    monkeypatch.setenv("OPENREACH_FIXTURE_BASE", server)
    HITS.clear()
    policy._robots_cache.clear()
    policy._advisory_warned.clear()
    yield
    policy._robots_cache.clear()
    policy._advisory_warned.clear()


def _fetch(server: str, mode: str):
    return fetcher.fetch(
        models.FetchRequest(
            url=f"{server}/article",
            timeout_s=5.0,
            max_attempts=1,
            no_impersonate=True,
            robots_mode=mode,
        )
    )


# ── off — 조회 자체가 없다 ─────────────────────────────────────────────────


def test_off_mode_never_requests_robots_txt(server):
    """죽여야 할 변이: `robots_gate` 의 off 분기를 "조회하고 결과를 버린다"로 바꾸기.

    그 변이는 동작(차단하지 않음)이 같아서 결과만 보는 테스트로는 잡히지 않는다.
    하지만 요청은 이미 나갔고 **상대 서버는 그것을 봤다** — 우리가 약속한 것은
    "따르지 않는다"가 아니라 "조회하지 않는다"이므로 히트 수로 고정한다.
    """
    result = _fetch(server, "off")
    assert result.ok, result.failure_reason
    assert HITS.get("/robots.txt", 0) == 0
    assert HITS.get("/article", 0) == 1


def test_off_mode_is_the_default(server):
    """죽여야 할 변이: 기본값을 enforce 로 되돌리기 (사용자 결정의 회귀)."""
    assert models.FetchRequest(url="https://example.com").robots_mode == "off"
    assert policy.DEFAULT_ROBOTS_MODE == "off"
    # 전면 Disallow 인데도 기본 호출은 통과한다.
    assert _fetch(server, "off").ok


# ── enforce — R5 동작의 정확한 복원 ────────────────────────────────────────


def test_enforce_mode_restores_the_block(server):
    """죽여야 할 변이: enforce 를 advisory 와 같게 만들기 (플래그가 무의미해진다)."""
    result = _fetch(server, "enforce")
    assert not result.ok
    assert result.failure_reason == "policy_blocked"
    assert result.attempts[0].rule == "robots"
    assert HITS.get("/robots.txt", 0) == 1
    assert HITS.get("/article", 0) == 0  # 본문은 두드리지 않았다
    assert result.exit_code() == 2       # 경계 사유


# ── advisory — 보고하되 차단하지 않는다 ────────────────────────────────────


def test_advisory_mode_reports_without_blocking(server, capsys):
    """죽여야 할 변이: advisory 를 off 와 같게 만들기 (조회를 지우면 보고할 사실이 없다)."""
    result = _fetch(server, "advisory")
    assert result.ok, result.failure_reason
    assert HITS.get("/robots.txt", 0) == 1   # 사실은 확인했다
    assert HITS.get("/article", 0) == 1      # 그러나 막지는 않았다
    assert "advisory" in capsys.readouterr().err


def test_advisory_warns_once_per_origin(server, capsys):
    """배치·검색이 같은 호스트를 여러 번 두드릴 때 stderr 가 같은 줄로 덮이면 안 된다."""
    for _ in range(3):
        _fetch(server, "advisory")
    assert capsys.readouterr().err.count("robots advisory") == 1


# ── 모드와 무관한 것: SSRF ─────────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["off", "advisory", "enforce"])
def test_ssrf_hop_guard_survives_every_mode(server, mode):
    """죽여야 할 변이: off 에서 홉 가드를 통째로 없애기.

    `hop_guard_for("off")` 가 `ssrf_hop_guard` 를 돌려주는 것이 핵심이다 — robots 만
    빠지고 SSRF 는 남는다. None 을 돌려주는 변이는 여기서 죽는다 (NG-11).
    """
    with pytest.raises(transport.PolicyBlocked) as caught:
        transport.request(
            f"{server}/to-private",
            timeout=5.0,
            hop_check=policy.hop_guard_for(mode),
        )
    assert caught.value.rule == "redirect_hop"


def test_hop_guard_selection_is_structural():
    """off 가 돌려주는 가드에는 robots 코드 경로가 **존재하지 않는다**."""
    assert policy.hop_guard_for("off") is policy.ssrf_hop_guard
    assert policy.hop_guard_for("advisory") is policy.advisory_hop_guard
    assert policy.hop_guard_for("enforce") is policy.hop_guard


# ── 닫힌 집합 ──────────────────────────────────────────────────────────────


def test_unknown_mode_is_rejected_not_coerced():
    """죽여야 할 변이: 모르는 모드를 조용히 off 로 떨어뜨리기.

    robots 를 켠 줄 알고 끈 채로 도는 것이 가장 나쁜 실패다 (NG-10).
    """
    with pytest.raises(models.InvariantError):
        models.FetchRequest(url="https://example.com", robots_mode="respect")
    with pytest.raises(ValueError):
        policy.robots_gate("https://example.com", timeout=1.0, mode="respect")


# ── Phase 0 도 같은 모드를 따른다 ──────────────────────────────────────────


def test_phase0_guard_follows_the_mode(server):
    """죽여야 할 변이: `api_index._guard` 만 `robots_verdict` 로 되돌리기.

    Phase 0 은 조립 URL 마다 robots 를 다시 봤다(AC-B-010-13). 그 자리가 모드를
    따르지 않으면 `--robots off` 로 돌려도 인덱스 경로에서만 robots 요청이 샌다.
    """
    entry = {
        "host": "127.0.0.1",
        "response_kind": "html",
        "endpoints": [f"{server}/article"],
    }
    outcome = api_index.run(
        entry, {}, intent="article", timeout=5.0,
        on_attempt=lambda *a, **k: None, robots_mode="off",
    )
    assert HITS.get("/robots.txt", 0) == 0
    assert outcome.reason is None

    HITS.clear()
    policy._robots_cache.clear()
    outcome = api_index.run(
        entry, {}, intent="article", timeout=5.0,
        on_attempt=lambda *a, **k: None, robots_mode="enforce",
    )
    assert HITS.get("/robots.txt", 0) == 1
    assert outcome.reason == "policy_blocked"
    assert outcome.policy_rule == "robots"
