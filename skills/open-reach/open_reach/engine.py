"""CLI 진입점 — `python -m open_reach.engine <subcommand> ...`

종료 코드: 0 성공/측정불가, 1 일반 실패, 2 경계 도달, 3 게이트 위반, 4 사용 오류.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import (
    api_index as api_index_mod,
    batch as batch_mod,
    bench as bench_mod,
    fetcher,
    observe,
    policy,
    profiles as profiles_mod,
    refresh as refresh_mod,
    search as search_mod,
    yamlio,
)
from . import models
from .models import (
    FetchRequest,
    FetchResult,
    InvariantError,
    ObservationSchemaError,
    utc_now,
)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_BOUNDARY = 2
EXIT_GATE = 3
EXIT_USAGE = 4


class _Parser(argparse.ArgumentParser):
    """argparse 의 exit 2 를 쓰지 않는다 — 사용 오류는 이 도구에서 4다."""

    def error(self, message: str):  # noqa: D102 - stdlib signature
        raise bench_mod.UsageError(message)


def _configure_streams() -> None:
    """출력은 항상 UTF-8 이다 — 콘솔 코드페이지에 따라 결과가 달라지지 않게 한다."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _emit(payload: dict) -> None:
    # ensure_ascii=True — 소비자가 어떤 인코딩으로 읽든 JSON 이 깨지지 않는다
    sys.stdout.write(json.dumps(payload, ensure_ascii=True, indent=2) + "\n")


def _fail_internal(exc: BaseException) -> int:
    """SPEC 에러 포맷의 `internal` — 스택 트레이스는 stderr 로만 나간다."""
    import traceback

    traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    _emit({"error": {"code": "internal", "message": f"{type(exc).__name__}: {exc}"}})
    return EXIT_FAILED


def _default_compare_out() -> Path:
    stamp = utc_now().replace(":", "").replace("-", "")
    return observe.state_dir() / "bench" / f"compare-{stamp}.json"


def _fail_usage(message: str) -> int:
    _emit({"error": {"code": "usage", "message": message}})
    sys.stderr.write(f"[open-reach] 사용 오류: {message}\n")
    return EXIT_USAGE


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="open-reach", description="공개 콘텐츠 취득 엔진")
    subs = parser.add_subparsers(dest="command")

    p_fetch = subs.add_parser("fetch")
    # 단건이 기본이다. `--batch` 를 쓰면 위치 인자는 비운다 (상호 배타, R6/W4).
    p_fetch.add_argument("url", nargs="?")
    p_fetch.add_argument("--batch", help="URL 목록 파일. '-' 는 표준 입력")
    p_fetch.add_argument("--concurrency", type=int, default=batch_mod.DEFAULT_CONCURRENCY)
    p_fetch.add_argument("--intent", choices=("article", "media", "raw"), default="article")
    p_fetch.add_argument("--timeout", type=float, default=20.0)
    p_fetch.add_argument("--max-attempts", type=int, default=6)
    p_fetch.add_argument("--allow-browser", action="store_true")
    # Phase 0 인덱스의 대체 경로. `bench --battery` 와 같은 구조다 — 인수 테스트가
    # 픽스처 인덱스를 지정하는 통로이며, 지정하지 않으면 출하 인덱스를 쓴다.
    p_fetch.add_argument("--api-index")
    # robots.txt 모드 (R6). 기본은 off — 조회하지 않는다.
    # `--respect-robots` 는 `--robots enforce` 의 별칭이며, 둘 다 주면 사용 오류다.
    p_fetch.add_argument("--robots", choices=models.ROBOTS_MODES, default=None)
    p_fetch.add_argument("--respect-robots", action="store_true")

    # `search` (R6/W5) — 질의 → 후보 URL → 병렬 취득. fetch 와 옵션을 공유하는 것은
    # 후보 취득이 결국 `fetch --batch` 와 같은 경로이기 때문이다.
    p_search = subs.add_parser("search")
    p_search.add_argument("query")
    p_search.add_argument("--sources", help="쉼표로 구분한 소스 이름. 기본은 선언된 전부")
    p_search.add_argument("--max-results", type=int, default=search_mod.DEFAULT_MAX_RESULTS)
    # 후보 URL 만 내고 **한 건도 취득하지 않는다**. 무엇이 걸렸는지 먼저 보고 싶을 때.
    p_search.add_argument("--urls-only", action="store_true")
    p_search.add_argument("--concurrency", type=int, default=batch_mod.DEFAULT_CONCURRENCY)
    p_search.add_argument("--intent", choices=("article", "media", "raw"), default="article")
    p_search.add_argument("--timeout", type=float, default=20.0)
    p_search.add_argument("--max-attempts", type=int, default=6)
    p_search.add_argument("--allow-browser", action="store_true")
    p_search.add_argument("--api-index")
    p_search.add_argument("--robots", choices=models.ROBOTS_MODES, default=None)
    p_search.add_argument("--respect-robots", action="store_true")

    p_bench = subs.add_parser("bench")
    p_bench.add_argument("--tier", type=int, default=1, choices=(1, 2))
    p_bench.add_argument("--runs", type=int, default=3)
    p_bench.add_argument("--battery")
    p_bench.add_argument("--no-browser", action="store_true")
    p_bench.add_argument("--shuffle", action="store_true")
    p_bench.add_argument("--holdout", action="store_true")
    p_bench.add_argument("--timeout", type=float, default=20.0)

    p_compare = subs.add_parser("compare")
    p_compare.add_argument("--tier", type=int, default=1, choices=(1, 2))
    p_compare.add_argument("--battery")
    p_compare.add_argument("--original-cmd")
    p_compare.add_argument("--out")
    p_compare.add_argument("--runs", type=int, default=1)
    p_compare.add_argument("--timeout", type=float, default=20.0)

    p_baseline = subs.add_parser("baseline")
    p_baseline.add_argument("sample")
    p_baseline.add_argument("--timeout", type=float, default=20.0)

    p_refresh = subs.add_parser("refresh")
    p_refresh.add_argument("--dry-run", action="store_true")

    p_explain = subs.add_parser("explain")
    p_explain.add_argument("url")
    p_explain.add_argument("--max-attempts", type=int, default=6)

    return parser


def _check_common(args: argparse.Namespace) -> None:
    timeout = getattr(args, "timeout", None)
    if timeout is not None and not (0 < timeout <= 60):
        raise bench_mod.UsageError("--timeout 은 0 초과 60 이하여야 한다")
    attempts = getattr(args, "max_attempts", None)
    if attempts is not None and not (1 <= attempts <= 12):
        raise bench_mod.UsageError("--max-attempts 는 1..12 여야 한다")
    runs = getattr(args, "runs", None)
    if runs is not None and not (1 <= runs <= 9):
        raise bench_mod.UsageError("--runs 는 1..9 여야 한다")
    url = getattr(args, "url", None)
    if url is not None and len(url) > policy.MAX_URL_LENGTH:
        raise bench_mod.UsageError(f"URL 이 {policy.MAX_URL_LENGTH} 자를 초과했다")
    _check_batch(args)
    _check_search(args)
    _resolve_robots_mode(args)


def _check_batch(args: argparse.Namespace) -> None:
    """단건과 배치는 정확히 하나여야 한다 (R6/W4).

    둘 다 주면 어느 쪽을 실행할지 우리가 정하게 되는데, 그 선택을 조용히 하면 사용자는
    두드리지 않으려던 목록을 두드리게 된다. 둘 다 없으면 실행할 대상이 없다.
    """
    if not hasattr(args, "batch"):
        return
    has_url = bool(getattr(args, "url", None))
    has_batch = bool(getattr(args, "batch", None))
    if has_url and has_batch:
        raise bench_mod.UsageError("url 위치 인자와 --batch 는 함께 쓸 수 없다")
    if not has_url and not has_batch:
        raise bench_mod.UsageError("url 또는 --batch 중 하나가 필요하다")
    if has_batch:
        try:
            batch_mod.check_concurrency(args.concurrency)
        except batch_mod.BatchError as exc:
            raise bench_mod.UsageError(str(exc)) from exc


def _check_search(args: argparse.Namespace) -> None:
    """검색 입력도 **요청을 시작하기 전에** 확정한다 (R6/W5)."""
    if getattr(args, "command", None) != "search":
        return
    try:
        args.query = search_mod.check_query(args.query)
        search_mod.check_max_results(args.max_results)
    except search_mod.SearchError as exc:
        raise bench_mod.UsageError(str(exc)) from exc
    try:
        batch_mod.check_concurrency(args.concurrency)
    except batch_mod.BatchError as exc:
        raise bench_mod.UsageError(str(exc)) from exc


def _resolve_robots_mode(args: argparse.Namespace) -> None:
    """`--robots` 와 `--respect-robots` 를 하나의 모드로 합친다 (R6).

    둘을 동시에 주면 **사용 오류**다. `--robots off --respect-robots` 를 조용히 한쪽으로
    해석하면 사용자는 robots 를 켠 줄 알고 끈 채로 돌게 된다 — 모드는 요청이 나가기
    전에 확정되어야 하고, 모호한 입력은 요청 없이 거절하는 편이 옳다.
    """
    if not hasattr(args, "robots"):
        return
    explicit = getattr(args, "robots", None)
    respect = getattr(args, "respect_robots", False)
    if explicit is not None and respect and explicit != "enforce":
        raise bench_mod.UsageError(
            "--robots 와 --respect-robots 가 서로 다른 모드를 가리킨다 "
            "(--respect-robots 는 --robots enforce 의 별칭이다)"
        )
    args.robots = explicit or ("enforce" if respect else policy.DEFAULT_ROBOTS_MODE)


def _shipped_paths() -> tuple[Path, Path]:
    """SPEC:329 가 '출하 배터리' 라고 부르는 두 파일.

    티어는 항목의 `tier` 필드로 갈리지 파일로 갈리지 않는다 — 파일명에 티어를 넣으면
    SPEC 이 지정한 `bench/battery.yaml` 이 영영 존재하지 않는 경로가 되어, 기본 실행이
    항상 "출하 배터리가 아직 없다" 로 죽고 사용자는 `--battery` 로 우회하게 된다.

    **둘 다 `repo_root()` 기준이다.** holdout 을 `state_dir()` 기준으로 잡으면
    `OPENREACH_STATE_DIR` 한 줄로 출하 holdout 의 신원이 바뀐다 — 그 상태에서 진짜
    출하 파일을 `--battery` 로 가리키면 `shipped=False` 가 되어 `role: production`
    검사가 꺼지고, 방금 막은 우회로(SPEC:329)가 환경변수로 다시 열린다.
    SPEC:454 가 `OPENREACH_STATE_DIR` 로 옮기라고 한 것은 **상태 파일**(관측 로그·이력)
    이지 저장소에 체크인되는 출하 배터리가 아니다.
    """
    bench_dir = observe.repo_root() / "bench"
    return (bench_dir / "battery.yaml", bench_dir / "holdout.yaml")


def _battery_path(args: argparse.Namespace) -> tuple[Path, bool]:
    """(경로, 출하 배터리 여부).

    `shipped` 는 **경로로** 판정한다. 플래그로 판정하면 `--battery bench/battery.yaml`
    처럼 출하 배터리를 직접 가리키는 순간 "출하 배터리는 role: production 이어야 한다"
    검사가 조용히 꺼진다 — SPEC:329 가 막으라고 적어 둔 바로 그 우회로(출하 배터리를
    fixture 로 강등해 G-1 을 피하는 길)가 다시 열린다.
    """
    shipped_battery, holdout = _shipped_paths()

    if getattr(args, "holdout", False):
        if getattr(args, "battery", None):
            raise bench_mod.UsageError("--holdout 과 --battery 는 함께 쓸 수 없다")
        return holdout, True

    if args.battery:
        path = Path(args.battery)
        return path, _same_file(path, shipped_battery) or _same_file(path, holdout)

    if not shipped_battery.exists():
        raise bench_mod.UsageError(
            f"출하 배터리가 아직 없다 ({shipped_battery}). --battery 로 경로를 지정하라"
        )
    return shipped_battery, True


def _same_file(a: Path, b: Path) -> bool:
    """같은 파일을 가리키는가. 존재하지 않는 경로도 이름 기준으로 비교한다."""
    try:
        if a.exists() and b.exists():
            return a.samefile(b)
    except OSError:
        pass
    return a.resolve() == b.resolve()


def cmd_fetch(args: argparse.Namespace) -> int:
    # 인덱스는 **요청을 시작하기 전에** 검증한다 (AC-B-010-8·10·12·15). 실행 중에
    # 발견하면 이미 나간 요청을 되돌릴 수 없고, "네트워크 요청 0건"이라는 계약이
    # 지켜졌는지 출력만으로는 확인할 수 없게 된다.
    api_index_mod.load_cached(args.api_index)

    # 배치 목록은 **요청을 시작하기 전에** 읽고 검증한다 — 인덱스 선검증과 같은 이유다.
    # 20번째 줄이 상한 위반인 것을 19건 두드린 뒤에 알면 되돌릴 수 없다.
    urls = _batch_urls(args) if args.batch else [args.url]

    template = FetchRequest(
        url=urls[0],
        intent=args.intent,
        timeout_s=args.timeout,
        allow_browser=args.allow_browser,
        max_attempts=args.max_attempts,
        api_index=args.api_index,
        robots_mode=args.robots,
    )

    if not args.batch:
        result = fetcher.fetch(template)
        _emit(result.to_dict())
        return result.exit_code()

    results: list[FetchResult] = []
    for result in batch_mod.run(urls, template, concurrency=args.concurrency):
        results.append(result)
        # NDJSON — 한 줄에 하나. 줄 단위로 흘려보내야 긴 배치에서 소비자가 기다리지
        # 않는다. 단건의 indent 출력과 형식이 다른 것은 의도다.
        sys.stdout.write(json.dumps(result.to_dict(), ensure_ascii=True) + "\n")
        sys.stdout.flush()
    return batch_mod.exit_code(results)


def _batch_urls(args: argparse.Namespace) -> list[str]:
    if args.batch == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(args.batch).read_text(encoding="utf-8")
        except OSError as exc:
            raise bench_mod.UsageError(f"배치 목록을 읽을 수 없다: {exc}") from exc
    try:
        urls = batch_mod.parse_urls(text)
    except batch_mod.BatchError as exc:
        raise bench_mod.UsageError(str(exc)) from exc
    too_long = [u for u in urls if len(u) > policy.MAX_URL_LENGTH]
    if too_long:
        raise bench_mod.UsageError(
            f"배치 목록에 {policy.MAX_URL_LENGTH} 자를 초과한 URL 이 있다"
        )
    return urls


def cmd_search(args: argparse.Namespace) -> int:
    """질의 → 후보 → (기본) 병렬 취득 (R6/W5).

    출력은 NDJSON 이다. **첫 줄은 검색 요약**(소스별 성패·후보 목록)이고, 이어서
    URL 당 FetchResult 한 줄이 온다. 요약을 stderr 로 빼지 않는 이유: "어느 소스가
    무엇을 냈는가"는 결과를 해석하는 데 필요한 증적이지 로그가 아니다.

    후보는 여기서 `batch` 로 넘어가고 **돌아오지 않는다**. 취득한 본문에서 링크를
    뽑아 다시 검색에 넣는 경로는 없다 — NG-5 개정판의 유일한 방벽이다.
    """
    index = api_index_mod.load_cached(args.api_index)
    try:
        sources = search_mod.select_sources(index, args.sources)
        candidates, outcomes = search_mod.run(
            args.query,
            sources,
            timeout=args.timeout,
            max_results=args.max_results,
            robots_mode=args.robots,
        )
    except search_mod.SearchError as exc:
        raise bench_mod.UsageError(str(exc)) from exc

    summary = {
        "search": {
            "query": args.query,
            "sources": [outcome.to_dict() for outcome in outcomes],
            "candidates": [candidate.to_dict() for candidate in candidates],
        }
    }
    sys.stdout.write(json.dumps(summary, ensure_ascii=True) + "\n")
    sys.stdout.flush()

    if not candidates:
        # 후보가 없으면 실패다. 소스가 전부 200 이었어도 마찬가지 — 빈 결과를
        # 성공으로 내면 "찾았는데 아무것도 없었다"와 "찾지 못했다"가 같아진다.
        sys.stderr.write("[open-reach] search: 후보 URL 이 없다\n")
        return EXIT_FAILED
    if args.urls_only:
        return EXIT_OK

    template = FetchRequest(
        url=candidates[0].url,
        intent=args.intent,
        timeout_s=args.timeout,
        allow_browser=args.allow_browser,
        max_attempts=args.max_attempts,
        api_index=args.api_index,
        robots_mode=args.robots,
    )
    results: list[FetchResult] = []
    for result in batch_mod.run(
        [candidate.url for candidate in candidates],
        template,
        concurrency=args.concurrency,
    ):
        results.append(result)
        sys.stdout.write(json.dumps(result.to_dict(), ensure_ascii=True) + "\n")
        sys.stdout.flush()
    return batch_mod.exit_code(results)


def cmd_bench(args: argparse.Namespace) -> int:
    if args.no_browser:
        # 플래그를 받아만 두고 아무 의미도 없는 것보다, 왜 무의미한지 말하는 편이 낫다
        sys.stderr.write(
            "[open-reach] --no-browser: R1 에는 브라우저 티어가 없다 — 이미 기본 동작이다\n"
        )
    path, shipped = _battery_path(args)
    battery = bench_mod.load_battery(path)
    bench_mod.check_governance(battery, shipped=shipped)
    # bench 도 Phase 0 을 탄다 — 인덱스가 깨져 있으면 배터리를 절반쯤 돈 뒤에야
    # 알게 되고, 그때는 이미 나간 요청을 되돌릴 수 없다. fetch 와 같은 자리에서
    # 같은 이유로 선검증한다 (AC-B-010-8·10·12·15, SPEC Response 3).
    api_index_mod.load_cached(None)

    report = bench_mod.run_battery(
        battery,
        tier=args.tier,
        runs=args.runs,
        shuffle=args.shuffle,
        timeout=args.timeout,
        max_attempts=bench_mod.DEFAULT_MAX_ATTEMPTS,
    )
    # bench 는 두 성격을 모두 막는다 — 틀리게 잰 것도, 아예 못 잰 것도 통과가 아니다.
    for violation in report["negative_violations"]:
        sys.stderr.write(f"[open-reach] G-3: 음성 케이스 오분류 — {violation}\n")
    for violation in report["measurement_violations"]:
        sys.stderr.write(f"[open-reach] G-3: 측정 불가 — {violation}\n")
    # SC-8 은 하드 게이트다 — 오탐 0건, 미탐 <=10%, 그리고 **잴 수 있었어야 한다**.
    sc8 = bench_mod.sc8_violations(
        report.get("vendor_sc8", {}), attempted=report.get("total", 0) > 0
    )
    for violation in sc8:
        sys.stderr.write("[open-reach] " + violation + "\n")

    # 기록은 **항상** 남긴다 — 게이트로 막히는 실행일수록 다음 회귀 감사가 그 측정을
    # 봐야 한다 (AC-B-004-4: 각 실행 BenchRun 1건 append). 신뢰 불가 실행은 gated 로
    # 표시해 다음 실행의 회귀 **기준**에서만 제외한다. 여기엔 음성 오분류·측정 불가뿐
    # 아니라 **SC-8 위반**(벤더 오탐/미탐)도 포함된다 — SC-8 이 깨진 실행의 돌파율은
    # 벤더를 잘못 귀속한 값이라 그대로 baseline 이 되면 다음 회귀 감사를 오염시킨다.
    baseline_unsafe = bool(
        report["negative_violations"] or report["measurement_violations"] or sc8
    )
    bench_mod.record_run(report, battery_path=path, gated=baseline_unsafe)
    # 측정 자체가 깨진 경우(음성 오분류·측정 불가)는 렌더 없이 즉시 정지한다.
    # SC-8 위반은 렌더로 증적을 남긴 뒤 정지한다 (아래).
    if report["negative_violations"] or report["measurement_violations"]:
        return EXIT_GATE
    sys.stdout.write(bench_mod.render(report) + "\n")
    return EXIT_GATE if sc8 else EXIT_OK


def cmd_compare(args: argparse.Namespace) -> int:
    path, _ = _battery_path(args)
    out_path = Path(args.out) if args.out else _default_compare_out()
    payload, violations = bench_mod.compare(
        battery_path=path,
        out_path=out_path,
        original_cmd=args.original_cmd,
        tier=args.tier,
        runs=args.runs,
        timeout=args.timeout,
        # bench 와 같은 시도 예산을 쓴다 — 합격선을 정하는 명령이 스스로 불리한
        # 조건으로 측정하면 그 숫자는 비교가 아니라 자해다
        max_attempts=bench_mod.DEFAULT_MAX_ATTEMPTS,
    )
    _emit(payload)
    # compare 는 **게이트가 아니라 증적 명령**이다. SPEC 의 서브커맨드 계약이 bench 에만
    # `Response 3`(거버넌스 위반 또는 음성 케이스 오분류)을 두고 compare 에는 Response
    # 0 과 4 만 두었으며, AC-B-005-2 는 원본을 못 재면 exit 0 을 요구한다 — 예외는 없다.
    # 음성 오분류를 여기서 exit 3 으로 만들면 그 계약을 깬다.
    #
    # 그렇다고 오분류가 사라지지는 않는다. bench(AC-B-004-3)가 여전히 exit 3 으로 막고,
    # compare 쪽에서는 payload 의 status="unmeasurable" 과 reason 이 "이 숫자는 쓸 수
    # 없다" 를 증적 파일에 남긴다 — 종료 코드가 아니라 기록으로 막는 자리다.
    for violation in violations:
        sys.stderr.write(f"[open-reach] G-3: 음성 케이스 오분류 — {violation}\n")
    return EXIT_OK


def cmd_baseline(args: argparse.Namespace) -> int:
    _emit(bench_mod.baseline(Path(args.sample), timeout=args.timeout))
    return EXIT_OK


def cmd_refresh(args: argparse.Namespace) -> int:
    code, output = refresh_mod.run(dry_run=args.dry_run)
    sys.stdout.write(output + "\n")
    return code


def cmd_explain(args: argparse.Namespace) -> int:
    try:
        verdict = policy.check_url(args.url)
        policy_view = asdict(verdict)
    except policy.UnresolvableHost as exc:
        policy_view = {"allowed": False, "rule": None, "detail": str(exc)}

    steps, vendor = fetcher.plan_for(args.url, max_attempts=args.max_attempts)
    _emit({"policy": policy_view, "plan": steps, "waf_hint": vendor})
    # SPEC Response 2 — 차단 URL 은 계획을 보여주더라도 성공으로 끝나지 않는다
    return EXIT_OK if policy_view.get("allowed") else EXIT_BOUNDARY


_COMMANDS = {
    "fetch": cmd_fetch,
    "search": cmd_search,
    "bench": cmd_bench,
    "compare": cmd_compare,
    "baseline": cmd_baseline,
    "refresh": cmd_refresh,
    "explain": cmd_explain,
}


def main(argv: list[str] | None = None) -> int:
    _configure_streams()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if not args.command:
            raise bench_mod.UsageError("서브커맨드를 지정하라 (fetch/search/bench/compare/baseline/refresh/explain)")
        _check_common(args)
        return _COMMANDS[args.command](args)
    except api_index_mod.IndexLoadError as exc:
        # 인덱스를 신뢰할 수 없으면 한 건도 요청하지 않는다 (SPEC Response 3).
        # yamlio.YamlError 도 ValueError 라 이 except 가 먼저 와야 한다.
        sys.stderr.write(f"[open-reach] api_index: {exc}\n")
        _emit({"error": {"code": "usage", "message": f"API 인덱스 로드 실패: {exc}"}})
        return EXIT_GATE
    except bench_mod.UsageError as exc:
        return _fail_usage(str(exc))
    except bench_mod.GovernanceError as exc:
        for violation in exc.violations:
            sys.stderr.write(f"[open-reach] 거버넌스 위반 — {violation}\n")
        _emit({"error": {"code": "usage", "message": "거버넌스 위반", "violations": exc.violations}})
        return EXIT_GATE
    except (profiles_mod.ProfilesError, yamlio.YamlError) as exc:
        # 지문표가 깨졌다 — 입력 문제이므로 사용 오류로 돌려준다
        return _fail_usage(str(exc))
    except (InvariantError, ObservationSchemaError) as exc:
        return _fail_internal(exc)
    except OSError as exc:
        return _fail_internal(exc)
    except KeyboardInterrupt:
        sys.stderr.write("[open-reach] 중단됨\n")
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
