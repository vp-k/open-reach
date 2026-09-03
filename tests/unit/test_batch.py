"""병렬 배치(R6/W4)의 변이 사멸 테스트.

NG-5 는 "단건만"에서 "사용자가 명시한 유한 집합"으로 개정됐다. 그 개정이 안전한 것은
**두 성질이 동시에 성립할 때뿐**이라, 테스트는 그 둘을 겨눈다.

1. **페이싱이 병렬화에 녹아 없어지지 않았다** — 같은 호스트로 몰린 URL 은 워커가 몇이든
   `transport.host_gate` 때문에 직렬이고 간격이 1.0 초 이상이다. "배치니까 빠르게" 라는
   변이(호스트 게이트 우회·자체 페이싱 재구현)는 여기서 죽는다.
2. **상한이 요청 전에 걸린다** — 51 번째 줄이 상한 위반인 것을 50 건 두드린 뒤에 알면
   되돌릴 수 없다.

시간 관측이 필요한 곳은 진짜 네트워크 대신 `transport.host_gate` 를 그대로 통과하는 가짜
fetch 를 쓴다. 픽스처 예외 오리진은 하나뿐이라 서로 다른 호스트를 실제로 세울 수 없고,
여기서 확인하려는 것은 취득이 아니라 **합성**(배치는 전역만 병렬화하고 호스트 직렬성은
게이트에 맡긴다)이기 때문이다.
"""

import json
import pathlib
import sys
import threading
import time
from urllib.parse import urlsplit

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import batch, engine, fetcher, transport  # noqa: E402
from open_reach.models import FetchRequest, FetchResult  # noqa: E402


def _ok(url: str) -> FetchResult:
    return FetchResult(
        url=url,
        ok=True,
        content_markdown="본문",
        metadata={},
        failure_reason=None,
        attempts=[],
        final_route="http",
    )


def _fail(url: str, reason: str = "waf_challenge") -> FetchResult:
    return FetchResult(
        url=url,
        ok=False,
        content_markdown=None,
        metadata=None,
        failure_reason=reason,
        attempts=[],
        final_route="http",
    )


class _Recorder:
    """호스트 게이트를 실제로 통과하는 가짜 fetch. 시작 시각과 동시 실행 수를 남긴다."""

    def __init__(self, work_s: float = 0.0):
        self.work_s = work_s
        self.starts: list[tuple[str, float]] = []
        self.max_inflight = 0
        self._inflight = 0
        self._lock = threading.Lock()

    def __call__(self, request: FetchRequest) -> FetchResult:
        host = (urlsplit(request.url).hostname or "").lower()
        with transport.host_gate(host):
            with self._lock:
                self._inflight += 1
                self.max_inflight = max(self.max_inflight, self._inflight)
                self.starts.append((request.url, time.monotonic()))
            try:
                if self.work_s:
                    time.sleep(self.work_s)
            finally:
                with self._lock:
                    self._inflight -= 1
        return _ok(request.url)


TEMPLATE = FetchRequest(url="https://placeholder.invalid/", timeout_s=5.0)


def _run(urls, **kw):
    return list(batch.run(urls, TEMPLATE, fetch=kw.pop("fetch"), **kw))


# ── ① 페이싱은 배치에 녹아 없어지지 않는다 ────────────────────────────────


def test_same_host_is_serial_with_minimum_interval():
    """죽여야 할 변이: 배치가 자기 페이싱을 따로 갖고 호스트 게이트를 건너뛰기.

    호스트명은 이 테스트 전용이라 `transport._last_request_at` 의 다른 테스트 잔재가
    간격에 섞이지 않는다 — 통과했는지가 우연이 되지 않게 한다.
    """
    rec = _Recorder()
    urls = [f"https://batch-serial.invalid/{i}" for i in range(2)]
    _run(urls, concurrency=4, fetch=rec)

    assert len(rec.starts) == 2
    gap = rec.starts[1][1] - rec.starts[0][1]
    assert gap >= transport.MIN_HOST_INTERVAL_S, f"같은 호스트 간격이 {gap:.3f}s 다"
    assert rec.max_inflight == 1, "같은 호스트는 동시에 하나만 나가야 한다"


def test_different_hosts_run_in_parallel():
    """죽여야 할 변이: 워커를 1 로 고정해 배치를 사실상 순차 루프로 만들기.

    호스트가 다르면 게이트가 서로를 막지 않으므로, 4 건 × 0.4 초가 순차라면 1.6 초가
    걸린다. 상한을 1.0 초로 두면 병렬이 아닐 때만 깨진다.
    """
    rec = _Recorder(work_s=0.4)
    urls = [f"https://batch-par{i}.invalid/x" for i in range(4)]

    started = time.monotonic()
    results = _run(urls, concurrency=4, fetch=rec)
    elapsed = time.monotonic() - started

    assert len(results) == 4
    assert elapsed < 1.0, f"병렬이 아니다 — {elapsed:.2f}s 걸렸다"
    assert rec.max_inflight > 1


def test_global_concurrency_cap_is_respected():
    """죽여야 할 변이: `--concurrency` 를 받아만 두고 무제한으로 펼치기."""
    rec = _Recorder(work_s=0.25)
    urls = [f"https://batch-cap{i}.invalid/x" for i in range(6)]

    _run(urls, concurrency=2, fetch=rec)

    assert rec.max_inflight <= 2


def test_results_follow_input_order_not_completion_order():
    """죽여야 할 변이: `as_completed` 로 바꿔서 빠른 것부터 내보내기.

    같은 입력이 실행마다 다른 순서로 나오면 진단·회귀 비교에서 diff 를 쓸 수 없다.
    첫 URL 을 가장 느리게 만들어, 완료 순서로 내는 구현이면 순서가 뒤집히게 한다.
    """
    delays = {"a": 0.35, "b": 0.05, "c": 0.05}

    def slow(request: FetchRequest) -> FetchResult:
        time.sleep(delays[urlsplit(request.url).path.lstrip("/")])
        return _ok(request.url)

    urls = [f"https://batch-order{i}.invalid/{k}" for i, k in enumerate("abc")]
    results = _run(urls, concurrency=3, fetch=slow)

    assert [r.url for r in results] == urls


# ── ② 입력 검증은 요청 전에 끝난다 ────────────────────────────────────────


def test_parse_urls_skips_blanks_and_comments():
    text = "\n".join(["", "# 주석", " https://a.example/1 ", "", "https://b.example/2"])
    assert batch.parse_urls(text) == ["https://a.example/1", "https://b.example/2"]


def test_parse_urls_dedupes_preserving_order():
    """죽여야 할 변이: `set()` 으로 중복 제거하기 — 순서가 실행마다 달라진다."""
    text = "https://a.example/1\nhttps://b.example/2\nhttps://a.example/1\n"
    assert batch.parse_urls(text) == ["https://a.example/1", "https://b.example/2"]


def test_parse_urls_rejects_empty_list():
    with pytest.raises(batch.BatchError):
        batch.parse_urls("\n# 전부 주석\n\n")


def test_parse_urls_rejects_over_cap():
    """상한은 **중복 제거 후** 판정한다 — 같은 URL 을 51 번 붙여 넣은 것은 1 건이다."""
    over = "\n".join(f"https://x{i}.example/" for i in range(batch.MAX_URLS + 1))
    with pytest.raises(batch.BatchError):
        batch.parse_urls(over)
    at_cap = "\n".join(f"https://x{i}.example/" for i in range(batch.MAX_URLS))
    assert len(batch.parse_urls(at_cap)) == batch.MAX_URLS


@pytest.mark.parametrize("value", [0, -1, batch.MAX_CONCURRENCY + 1])
def test_check_concurrency_rejects_out_of_range(value):
    with pytest.raises(batch.BatchError):
        batch.check_concurrency(value)


@pytest.mark.parametrize("value", [1, batch.MAX_CONCURRENCY])
def test_check_concurrency_accepts_bounds(value):
    assert batch.check_concurrency(value) == value


# ── ③ 실패는 조용히 사라지지 않는다 (NG-10) ───────────────────────────────


def test_one_exception_does_not_kill_the_batch_and_stays_visible():
    """죽여야 할 변이: 예외를 잡아서 결과 목록에서 **빼기**.

    빼면 줄 수가 입력 수와 달라지는데, NDJSON 소비자는 그것을 "덜 왔다" 가 아니라
    "그 URL 은 없었다" 로 읽는다. 실패는 그 자리에 실패로 남아야 한다.
    """
    def flaky(request: FetchRequest) -> FetchResult:
        if request.url.endswith("/boom"):
            raise RuntimeError("터졌다")
        return _ok(request.url)

    urls = ["https://ok.example/1", "https://ok.example/boom", "https://ok.example/2"]
    results = _run(urls, concurrency=2, fetch=flaky)

    assert [r.url for r in results] == urls
    broken = results[1]
    assert not broken.ok
    assert broken.failure_reason == "unknown"
    assert batch.exit_code(results) == 1


def test_exit_code_trichotomy():
    assert batch.exit_code([_ok("https://a/"), _ok("https://b/")]) == 0
    # 경계만 남은 배치는 2 — "고칠 수 있는 실패" 와 "넘지 않기로 한 벽" 을 가른다
    assert batch.exit_code([_ok("https://a/"), _fail("https://b/", "paywall")]) == 2
    assert batch.exit_code([_fail("https://a/", "auth_wall"), _fail("https://b/", "policy_blocked")]) == 2
    # 경계 하나라도 섞이면 1 로 내려간다 — 2 는 "전부 경계" 일 때만이다
    assert batch.exit_code([_fail("https://a/", "paywall"), _fail("https://b/", "network")]) == 1


# ── ④ CLI 배선 ────────────────────────────────────────────────────────────


def test_cli_rejects_url_and_batch_together(tmp_path, capsys):
    listing = tmp_path / "urls.txt"
    listing.write_text("https://a.example/\n", encoding="utf-8")
    code = engine.main(["fetch", "https://b.example/", "--batch", str(listing)])
    assert code == engine.EXIT_USAGE
    assert "함께 쓸 수 없다" in capsys.readouterr().err


def test_cli_rejects_neither_url_nor_batch(capsys):
    code = engine.main(["fetch"])
    assert code == engine.EXIT_USAGE
    capsys.readouterr()


def test_cli_rejects_over_cap_before_any_request(tmp_path, monkeypatch, capsys):
    """상한 위반은 **요청 0 건**으로 거절된다 — 50 건 두드린 뒤에 알면 늦다."""
    calls: list[str] = []
    monkeypatch.setattr(fetcher, "fetch", lambda req: calls.append(req.url) or _ok(req.url))

    listing = tmp_path / "urls.txt"
    listing.write_text(
        "\n".join(f"https://x{i}.example/" for i in range(batch.MAX_URLS + 1)),
        encoding="utf-8",
    )
    code = engine.main(["fetch", "--batch", str(listing)])

    assert code == engine.EXIT_USAGE
    assert calls == []
    capsys.readouterr()


def test_cli_emits_one_ndjson_line_per_url(tmp_path, monkeypatch, capsys):
    """출력 계약: URL 당 한 줄, 단건과 같은 FetchResult 스키마."""
    monkeypatch.setattr(fetcher, "fetch", lambda req: _ok(req.url))

    urls = ["https://a.example/1", "https://b.example/2", "https://c.example/3"]
    listing = tmp_path / "urls.txt"
    listing.write_text("\n".join(urls), encoding="utf-8")

    code = engine.main(["fetch", "--batch", str(listing), "--concurrency", "3"])
    out = capsys.readouterr().out.strip().splitlines()

    assert code == 0
    assert len(out) == len(urls)
    assert [json.loads(line)["url"] for line in out] == urls


def test_cli_batch_from_stdin(monkeypatch, capsys):
    monkeypatch.setattr(fetcher, "fetch", lambda req: _ok(req.url))
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("https://a.example/1\n"))

    code = engine.main(["fetch", "--batch", "-"])

    assert code == 0
    assert json.loads(capsys.readouterr().out.strip())["url"] == "https://a.example/1"


def test_cli_rejects_bad_concurrency(tmp_path, capsys):
    listing = tmp_path / "urls.txt"
    listing.write_text("https://a.example/\n", encoding="utf-8")
    code = engine.main(
        ["fetch", "--batch", str(listing), "--concurrency", str(batch.MAX_CONCURRENCY + 1)]
    )
    assert code == engine.EXIT_USAGE
    capsys.readouterr()


def test_cli_batch_exit_code_reflects_failures(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        fetcher,
        "fetch",
        lambda req: _ok(req.url) if req.url.endswith("1") else _fail(req.url, "paywall"),
    )
    listing = tmp_path / "urls.txt"
    listing.write_text("https://a.example/1\nhttps://a.example/2\n", encoding="utf-8")

    code = engine.main(["fetch", "--batch", str(listing)])

    assert code == engine.EXIT_BOUNDARY
    capsys.readouterr()


# ── ⑤ 재귀 부재 (NG-5 개정판의 유일한 방벽) ───────────────────────────────


def test_batch_module_has_no_link_extraction():
    """죽여야 할 변이: 취득 본문에서 링크를 뽑아 큐에 다시 넣기.

    개수 상한은 크롤러가 되는 것을 막지 못한다 — 막는 것은 재귀 부재뿐이다. 소스에
    추출·큐 재투입의 흔적이 없음을 고정해, 그 코드가 들어오는 순간 실패하게 한다.
    """
    source = pathlib.Path(batch.__file__).read_text(encoding="utf-8")
    # `content_markdown` 은 뺀다 — 실패 결과를 조립할 때 쓰는 필드명일 뿐이고, 여기서
    # 겨누는 것은 **본문을 읽어 다음 URL 을 만드는 행위**다.
    for forbidden in ("href", "urljoin", "extract", "findall"):
        assert forbidden not in source, f"배치에 재귀 후보 흔적이 있다: {forbidden}"
