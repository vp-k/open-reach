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
    bench as bench_mod,
    fetcher,
    observe,
    policy,
    profiles as profiles_mod,
    refresh as refresh_mod,
    yamlio,
)
from .models import FetchRequest, InvariantError, ObservationSchemaError, utc_now

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
    p_fetch.add_argument("url")
    p_fetch.add_argument("--intent", choices=("article", "media", "raw"), default="article")
    p_fetch.add_argument("--timeout", type=float, default=20.0)
    p_fetch.add_argument("--max-attempts", type=int, default=6)
    p_fetch.add_argument("--allow-browser", action="store_true")

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


def _battery_path(args: argparse.Namespace) -> tuple[Path, bool]:
    """(경로, 출하 배터리 여부)."""
    if getattr(args, "holdout", False):
        if getattr(args, "battery", None):
            raise bench_mod.UsageError("--holdout 과 --battery 는 함께 쓸 수 없다")
        return observe.state_dir() / "bench" / "holdout.yaml", False
    if args.battery:
        return Path(args.battery), False
    shipped = observe.repo_root() / "bench" / f"battery-tier{args.tier}.yaml"
    if not shipped.exists():
        raise bench_mod.UsageError(
            f"출하 배터리가 아직 없다 ({shipped}). --battery 로 경로를 지정하라"
        )
    return shipped, True


def cmd_fetch(args: argparse.Namespace) -> int:
    result = fetcher.fetch(
        FetchRequest(
            url=args.url,
            intent=args.intent,
            timeout_s=args.timeout,
            allow_browser=args.allow_browser,
            max_attempts=args.max_attempts,
        )
    )
    _emit(result.to_dict())
    return result.exit_code()


def cmd_bench(args: argparse.Namespace) -> int:
    if args.no_browser:
        # 플래그를 받아만 두고 아무 의미도 없는 것보다, 왜 무의미한지 말하는 편이 낫다
        sys.stderr.write(
            "[open-reach] --no-browser: R1 에는 브라우저 티어가 없다 — 이미 기본 동작이다\n"
        )
    path, shipped = _battery_path(args)
    battery = bench_mod.load_battery(path)
    bench_mod.check_governance(battery, shipped=shipped)

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
    if report["negative_violations"] or report["measurement_violations"]:
        return EXIT_GATE

    bench_mod.record_run(report, battery_path=path)
    sys.stdout.write(bench_mod.render(report) + "\n")
    return EXIT_OK


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
    # 음성 오분류는 bench 와 같은 관문이다 — 대조 명령이라고 통과시키면 같은 결함이
    # 명령 하나 바꾸는 것만으로 우회된다. 측정 불가는 여기서 막지 않는다:
    # AC-B-005-2 가 "측정 불가는 기록해야 할 사실" 로 정했고 payload 의
    # status="unmeasurable" 과 reason 이 그 기록이다.
    if violations:
        for violation in violations:
            sys.stderr.write(f"[open-reach] G-3: 음성 케이스 오분류 — {violation}\n")
        return EXIT_GATE
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
            raise bench_mod.UsageError("서브커맨드를 지정하라 (fetch/bench/compare/baseline/refresh/explain)")
        _check_common(args)
        return _COMMANDS[args.command](args)
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
