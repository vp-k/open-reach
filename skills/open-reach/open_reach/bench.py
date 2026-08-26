"""배터리 측정(`bench`) · 원본 대조(`compare`) · 실패율 기준선(`baseline`).

측정 전에 거버넌스를 먼저 검사한다 — 규칙을 어긴 배터리로 낸 수치는 수치가 아니다.
단일 수치만 인용하는 출력 경로는 존재하지 않는다 (AC-B-004-1).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from . import __version__, extract, fetcher, observe, yamlio
from .models import WAF_VENDORS, FetchRequest, utc_now

TIER1_MAX_ENTRIES = 50  # G-6
VENDOR_MIN_PER_TIER1 = 2  # G-1
REQUIRED_ENTRY_KEYS = ("expected", "tier", "waf_expected", "added_reason")  # G-4
# Expected 의 네 필드 중 최소 1개가 non-null 이어야 한다 (SPEC Data Model)
EXPECTED_ASSERTIONS = ("title_contains", "body_contains", "min_chars", "normalized_hash")
VALID_ROLES = ("production", "fixture")

DEFAULT_MAX_ATTEMPTS = 6
# `bench --tier 1 --runs 3` 벽시계 상한 (SPEC 성능) — 초과 시 부분 결과 + incomparable
WALL_CLOCK_CAP_S = 1800.0
# 회귀 판정 dead-band 3%p
DEAD_BAND = 0.03


class UsageError(ValueError):
    """사용 오류 — exit 4."""


class GovernanceError(RuntimeError):
    """거버넌스 위반 — exit 3. 위반 규칙 ID 를 모두 담는다."""

    def __init__(self, violations: list[str]) -> None:
        super().__init__("; ".join(violations))
        self.violations = violations


# ── 배터리 ──────────────────────────────────────────────────────────────


def battery_hash(path: Path) -> str:
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()


def load_battery(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise UsageError(f"배터리 파일이 없다: {path}")
    try:
        data = yamlio.loads(path.read_text(encoding="utf-8"))
    except yamlio.YamlError as exc:
        raise UsageError(f"배터리 파싱 실패: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise UsageError("배터리 최상위는 `role:` 과 `entries:` 를 가져야 한다")
    return data


def _assertion_count(entry: dict[str, Any]) -> int:
    expected = entry.get("expected")
    if not isinstance(expected, dict):
        return 0
    return sum(1 for key in EXPECTED_ASSERTIONS if expected.get(key) is not None)


def check_governance(battery: dict[str, Any], *, shipped: bool) -> None:
    """G-1 / G-3 / G-4 / G-6. role 에 따라 적용 범위가 달라진다."""
    role = battery.get("role")
    if role not in VALID_ROLES:
        # role 을 모르면 어느 거버넌스를 적용할지도 모른다 — 조용히 건너뛰면
        # G-1 을 우회하는 가장 쉬운 방법이 "role 오타" 가 된다
        raise UsageError(f"role 은 {' | '.join(VALID_ROLES)} 중 하나여야 한다 (현재: {role!r})")
    if shipped and role != "production":
        raise UsageError("출하 배터리는 role: production 이어야 한다")

    entries = [e for e in battery["entries"] if isinstance(e, dict)]
    tier1 = [e for e in entries if e.get("tier") == 1]
    violations: list[str] = []

    missing = [
        str(e.get("id"))
        for e in entries
        if any(key not in e for key in REQUIRED_ENTRY_KEYS)
    ]
    if missing:
        violations.append(f"G-4: 필수 필드 누락 항목 {missing}")

    empty_expected = [
        str(e.get("id"))
        for e in entries
        if not e.get("negative_case") and _assertion_count(e) == 0
    ]
    if empty_expected:
        # 무엇을 성공으로 볼지 정의하지 않은 항목은 항상 통과한다 — 돌파율이 부풀려진다
        violations.append(
            f"G-4: expected 의 4개 필드가 모두 null 인 항목 {empty_expected}"
        )

    if not any(e.get("negative_case") for e in tier1):
        violations.append("G-3: Tier-1 에 음성 케이스가 없다")

    if len(tier1) > TIER1_MAX_ENTRIES:
        violations.append(f"G-6: Tier-1 항목이 {len(tier1)} 개로 상한 {TIER1_MAX_ENTRIES} 초과")

    if role == "production":
        counts = {v: 0 for v in WAF_VENDORS}
        for entry in tier1:
            vendor = entry.get("waf_expected")
            if vendor in counts:
                counts[vendor] += 1
        thin = sorted(v for v, n in counts.items() if n < VENDOR_MIN_PER_TIER1)
        if thin:
            violations.append(
                f"G-1: 벤더별 {VENDOR_MIN_PER_TIER1}건 미만 — {thin}"
            )

    if violations:
        raise GovernanceError(violations)


# ── 측정 ────────────────────────────────────────────────────────────────


def _expected_ok(entry: dict[str, Any], result) -> tuple[bool, str | None]:
    expected = entry.get("expected") or {}
    if _assertion_count(entry) == 0:
        # 거버넌스에서 이미 걸러지지만, 측정 경로에서도 통과시키지 않는다
        return False, "expected 가 비어 있다 — 무엇을 성공으로 볼지 정의되지 않았다"
    markdown = result.content_markdown or ""
    title = (result.metadata or {}).get("title") or ""

    want_title = expected.get("title_contains")
    if want_title and want_title not in title:
        return False, f"title_contains 불일치: {want_title!r}"

    want_body = expected.get("body_contains")
    if want_body and want_body not in markdown:
        return False, f"body_contains 불일치: {want_body!r}"

    min_chars = expected.get("min_chars")
    if isinstance(min_chars, int) and len(markdown) < min_chars:
        return False, f"본문 길이 {len(markdown)} < {min_chars}"

    want_hash = expected.get("normalized_hash")
    if want_hash:
        got = hashlib.sha256(extract.normalized(markdown).encode("utf-8")).hexdigest()
        if got != want_hash:
            return False, "normalized_hash 불일치"

    return True, None


def _fetch_entry(entry: dict[str, Any], *, timeout: float, max_attempts: int):
    return fetcher.fetch(
        FetchRequest(
            url=str(entry.get("url") or ""),
            intent="article",
            timeout_s=timeout,
            allow_browser=False,
            max_attempts=max_attempts,
        )
    )


def run_battery(
    battery: dict[str, Any],
    *,
    tier: int,
    runs: int,
    shuffle: bool,
    timeout: float,
    max_attempts: int,
) -> dict[str, Any]:
    entries = [
        e
        for e in battery["entries"]
        if isinstance(e, dict) and e.get("tier") == tier
    ]
    positives = [e for e in entries if not e.get("negative_case")]
    negatives = [e for e in entries if e.get("negative_case")]

    by_vendor: dict[str, int] = {}
    by_route: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    per_run_rates: list[float] = []
    passed = 0
    failed = 0
    # 위반은 성격이 둘이고 처분도 달라야 한다.
    #   negative_violations   — 음성을 **틀리게 분류**했다. 엔진 정확도의 관문(G-3).
    #   measurement_violations — 아예 **재지 못했다**. 측정 불가.
    # bench 는 둘 다 막지만, compare 는 다르다 — SPEC AC-B-005-2 가 "측정 불가는
    # 실패가 아니라 기록해야 할 사실"이라고 정해 두었으므로 후자는 status 로 남긴다.
    # 한 목록에 섞으면 이 구분을 소비자 쪽에서 문자열로 되짚어야 한다.
    negative_violations: list[str] = []
    measurement_violations: list[str] = []
    deadline = time.monotonic() + WALL_CLOCK_CAP_S
    truncated = False
    attempted = 0

    # 음성 케이스는 돌파율의 분모가 아니라 정확도의 **관문**이다 (AC-B-004-3).
    # 그래서 양성 실행보다 먼저 돌린다 — 벽시계 상한에 걸렸다는 이유로 관문을 건너뛰면
    # "검증하지 않음"이 "통과"가 되고, 이 프로젝트에서 판정 불가는 통과가 아니다.
    # 음성셋은 경계 확인용 소수이므로 예산에서 차지하는 몫도 작다.
    negatives_checked = 0
    for entry in negatives:
        if time.monotonic() >= deadline:
            measurement_violations.append(f"{entry.get('id')}: 벽시계 상한으로 판정 불가")
            continue
        result = _fetch_entry(entry, timeout=timeout, max_attempts=max_attempts)
        negatives_checked += 1
        want = str(entry.get("negative_case"))
        if result.ok:
            negative_violations.append(f"{entry.get('id')}: success 로 분류됨 (기대 {want})")
        elif result.failure_reason != want:
            negative_violations.append(
                f"{entry.get('id')}: {result.failure_reason} 로 분류됨 (기대 {want})"
            )

    for run_index in range(runs):
        if time.monotonic() >= deadline:
            truncated = True
            break
        order = list(positives)
        if shuffle:
            # 결정적 셔플 — 실행마다 달라지면 dead-band 비교가 무의미해진다
            order.sort(key=lambda e: hashlib.sha256(
                f"{run_index}:{e.get('id')}".encode("utf-8")
            ).hexdigest())

        run_passed = 0
        run_attempted = 0
        for entry in order:
            if time.monotonic() >= deadline:
                truncated = True
                break
            run_attempted += 1
            attempted += 1
            result = _fetch_entry(entry, timeout=timeout, max_attempts=max_attempts)
            vendor = str(entry.get("waf_expected") or "none")
            if result.ok:
                ok, detail = _expected_ok(entry, result)
                if ok:
                    run_passed += 1
                    passed += 1
                    by_vendor[vendor] = by_vendor.get(vendor, 0) + 1
                    route = result.final_route or "unknown"
                    by_route[route] = by_route.get(route, 0) + 1
                    continue
                failed += 1
                by_reason["validation_failed"] = by_reason.get("validation_failed", 0) + 1
                by_vendor.setdefault(vendor, 0)
                continue
            failed += 1
            reason = result.failure_reason or "unknown"
            by_reason[reason] = by_reason.get(reason, 0) + 1
            by_vendor.setdefault(vendor, 0)

        # 분모는 실제로 시도한 건수다 — 중단된 실행을 완주한 것처럼 계산하지 않는다
        per_run_rates.append(run_passed / run_attempted if run_attempted else 0.0)
        if truncated:
            break

    # 양성을 한 건도 못 돌았는데 rate=0.000 을 내놓으면, 소비자는 "측정했더니 0%"와
    # "측정을 못 했다"를 구분할 수 없다. 앞의 것은 실패고 뒤의 것은 판정 불가인데
    # 둘 다 exit 0 으로 나가면 판정 불가가 통과가 된다 — 음성 관문을 먼저 돌리게 되면서
    # 예산이 음성에서 다 소진되는 경로가 새로 생겼으므로 여기서 명시적으로 막는다.
    #
    # 양성이 애초에 0건인 배터리(tier 필터 결과 0)도 마찬가지다. 원인이 예산이냐
    # 구성이냐만 다를 뿐 소비자가 받는 것은 똑같이 "근거 없는 rate=0.000 · exit 0" 이고,
    # 오히려 이쪽이 더 위험하다 — tier 오타 하나로 관문 전체가 조용히 무력해진다.
    if attempted == 0:
        measurement_violations.append(
            "양성 케이스를 한 건도 실행하지 못했다 — 벽시계 상한으로 측정 불가"
            if positives
            else f"tier={tier} 에 해당하는 양성 케이스가 배터리에 없다 — 측정 불가"
        )

    total = attempted if truncated else len(positives) * runs
    return {
        "tier": tier,
        "runs": runs,
        "total": total,
        "passed": passed,
        "failed": failed,
        "rate_median": round(statistics.median(per_run_rates), 3) if per_run_rates else 0.0,
        "by_vendor": by_vendor,
        "by_route": by_route,
        "by_reason": by_reason,
        "negatives_checked": negatives_checked,
        "negative_violations": negative_violations,
        "measurement_violations": measurement_violations,
        "truncated": truncated,
    }


def classify_regression(
    rate: float, prior_rate: float | None, *, truncated: bool
) -> str:
    """dead-band 3%p 를 적용한 회귀 판정 (순수 함수).

    부분 결과는 좋아졌는지 나빠졌는지 말할 자격이 없다 — `incomparable` 이다.
    """
    if truncated or prior_rate is None:
        return "incomparable"
    if rate < prior_rate - DEAD_BAND:
        return "regressed"
    return "none"


def render(report: dict[str, Any]) -> str:
    """분해 3종을 먼저, BENCH_RESULT 를 마지막 줄에. 다른 출력 경로는 없다."""
    lines = [
        f"tier={report['tier']} runs={report['runs']} "
        f"negatives_checked={report['negatives_checked']}",
        "by_vendor: " + json.dumps(report["by_vendor"], ensure_ascii=False, sort_keys=True),
        "by_route: " + json.dumps(report["by_route"], ensure_ascii=False, sort_keys=True),
        "by_reason: " + json.dumps(report["by_reason"], ensure_ascii=False, sort_keys=True),
        f"regression={report.get('regression', 'incomparable')} "
        f"truncated={str(bool(report.get('truncated'))).lower()}",
        f"BENCH_RESULT: rate={report['rate_median']:.3f} total={report['total']} "
        f"passed={report['passed']} failed={report['failed']}",
    ]
    return "\n".join(lines)


def prior_rate(battery_hash_value: str, tier: int) -> float | None:
    """같은 배터리·같은 tier 의 가장 최근 **완주** 실행 돌파율. 없으면 None.

    중단된 실행은 건너뛴다. `classify_regression` 이 부분 결과를 "좋아졌는지 나빠졌는지
    말할 자격이 없다"고 보면서 같은 부분 결과를 **비교 기준**으로는 받아들이면 앞뒤가
    맞지 않는다 — 게다가 양성 0건 중단이 남긴 0.0 이 기준이 되면 이후 어떤 실행도
    회귀로 잡히지 않아, 회귀 탐지기가 조용히 꺼진다.
    """
    for record in observe.iter_recent(observe.bench_history_path()):
        if record.get("battery_hash") != battery_hash_value or record.get("tier") != tier:
            continue
        if record.get("truncated"):
            continue
        value = record.get("rate_median")
        return float(value) if isinstance(value, (int, float)) else None
    return None


def record_run(report: dict[str, Any], *, battery_path: Path) -> None:
    digest = battery_hash(battery_path)
    report["regression"] = classify_regression(
        report["rate_median"],
        prior_rate(digest, report["tier"]),
        truncated=bool(report.get("truncated")),
    )
    observe.append_jsonl(
        observe.bench_history_path(),
        {
            "ts": utc_now(),
            "engine": f"open-reach@{__version__}",
            "regression": report["regression"],
            "tier": report["tier"],
            "runs": report["runs"],
            "total": report["total"],
            "passed": report["passed"],
            "failed": report["failed"],
            "rate_median": report["rate_median"],
            # 중단 여부를 남겨야 다음 실행이 이 줄을 기준으로 삼을지 판단할 수 있다
            "truncated": bool(report.get("truncated")),
            "by_vendor": report["by_vendor"],
            "by_route": report["by_route"],
            "by_reason": report["by_reason"],
            "battery_hash": digest,
        },
    )


# ── 원본 대조 ───────────────────────────────────────────────────────────


def _git_toplevel(directory: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() or None


def _original_commit(original_cmd: str | None) -> str | None:
    """원본 엔진의 커밋. 확실하지 않으면 null 로 둔다.

    설치된 바이너리의 디렉토리에서 무턱대고 `git rev-parse HEAD` 를 돌리면
    (예: 원본을 우리 저장소 안이나 `~/.local/bin` 에 두었을 때) **우리 커밋**이
    원본 커밋으로 기록된다 — 증적이 증적을 오염시킨다.
    """
    override = os.environ.get("OPENREACH_ORIGINAL_COMMIT", "").strip()
    if override:
        return override
    if not original_cmd:
        return None
    which = shutil.which(original_cmd.split()[0])
    if not which:
        return None
    directory = Path(which).resolve().parent
    toplevel = _git_toplevel(directory)
    if toplevel is None:
        return None
    ours = _git_toplevel(observe.repo_root())
    if ours is not None and Path(toplevel).resolve() == Path(ours).resolve():
        # 우리 저장소다 — 원본의 커밋이 아니다
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() or None


def _evidence(battery_path: Path, original_cmd: str | None) -> dict[str, Any]:
    commit = _original_commit(original_cmd)
    return {
        "original_commit": commit,
        "ran_at": utc_now(),
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "python": platform.python_version(),
        "battery_hash": battery_hash(battery_path),
    }


def _run_original(original_cmd: str, battery_path: Path) -> tuple[float | None, str | None]:
    """원본 엔진의 돌파율을 얻는다. 얻지 못하면 (None, 사유)."""
    if not original_cmd:
        return None, "--original-cmd 가 지정되지 않았다"
    if shutil.which(original_cmd.split()[0]) is None:
        return None, f"원본 명령을 찾을 수 없다: {original_cmd}"
    try:
        proc = subprocess.run(
            original_cmd.split() + [str(battery_path)],
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"원본 실행 실패: {exc}"
    for line in reversed(proc.stdout.splitlines()):
        if "rate=" in line:
            try:
                value = float(line.split("rate=", 1)[1].split()[0])
            except (ValueError, IndexError):
                break
            if not 0.0 <= value <= 1.0:
                # 87 과 0.87 을 같은 축에서 비교하면 대조 결과가 통째로 뒤집힌다
                return None, f"원본 rate 가 0..1 범위 밖이다: {value}"
            return value, None
    return None, "원본 출력에서 rate 를 읽지 못했다"


def compare(
    *,
    battery_path: Path,
    out_path: Path,
    original_cmd: str | None,
    tier: int,
    runs: int,
    timeout: float,
    max_attempts: int,
) -> tuple[dict[str, Any], list[str]]:
    """증적 payload 와 **정확도 관문 위반**을 함께 돌려준다.

    위반을 payload 안에 넣지 않는 이유는 SPEC Response 0 의 필드 구성을 바꾸지 않기
    위해서다. 종료 코드는 다른 명령과 마찬가지로 engine 층이 정한다.
    """
    if out_path.exists():
        raise UsageError(f"출력 파일이 이미 있다 — 덮어쓰지 않는다: {out_path}")

    battery = load_battery(battery_path)
    check_governance(battery, shipped=False)

    ours = run_battery(
        battery,
        tier=tier,
        runs=runs,
        shuffle=False,
        timeout=timeout,
        max_attempts=max_attempts,
    )
    original_rate, reason = _run_original(original_cmd or "", battery_path)

    # 우리 쪽을 재지 못했으면 원본이 멀쩡해도 그것은 **비교가 아니다**. 0/0 을 rate 0.0
    # 으로 흘려보내면 `status="measured"` 와 `delta=-0.77` 이 근거 없이 만들어져,
    # 합격 기준의 근거 문서(SC-1 증적)가 측정 없이 생성된다. SPEC AC-B-005-2 가 원본
    # 쪽에 대해 정한 원칙("측정 불가는 실패가 아니라 기록해야 할 사실")을 우리 쪽에도
    # 그대로 적용해 unmeasurable 로 남긴다 — 사유는 기존 reason 필드에 잇는다
    # (Response 0 의 필드 구성을 바꾸지 않기 위해).
    unmeasured = ours["measurement_violations"]
    if unmeasured:
        reason = "; ".join([r for r in [reason] if r] + unmeasured)
    comparable = original_rate is not None and not unmeasured

    payload = {
        "status": "measured" if comparable else "unmeasurable",
        "reason": reason,
        "open_reach": {
            "rate": ours["rate_median"],
            "total": ours["total"],
            "passed": ours["passed"],
            "failed": ours["failed"],
        },
        "original": {"rate": original_rate},
        "delta": round(ours["rate_median"] - original_rate, 3) if comparable else None,
        "regression": classify_regression(
            ours["rate_median"],
            original_rate,
            truncated=bool(ours.get("truncated")) or bool(unmeasured),
        ),
        "by_vendor": ours["by_vendor"],
        "by_route": ours["by_route"],
        "by_reason": ours["by_reason"],
        "evidence": _evidence(battery_path, original_cmd),
    }
    # 관문 위반이 있어도 파일은 남긴다 — 실패했다는 사실 자체가 증적이고,
    # 파일을 안 남기면 무엇이 왜 틀렸는지 사후에 확인할 방법이 사라진다.
    observe.atomic_write(out_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload, list(ours["negative_violations"])


# ── 실패율 기준선 ───────────────────────────────────────────────────────


def baseline(sample_path: Path, *, timeout: float) -> dict[str, Any]:
    """표준 클라이언트만으로 샘플 URL 목록의 실패율을 잰다 (A0 중단 조건의 근거)."""
    if not sample_path.exists():
        raise UsageError(f"샘플 파일이 없다: {sample_path}")
    urls = [
        line.strip()
        for line in sample_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not urls:
        raise UsageError("샘플 파일에 URL 이 없다")
    if len(urls) > 200:
        raise UsageError(f"샘플은 200줄 이하여야 한다 (현재 {len(urls)})")

    by_reason: dict[str, int] = {}
    failed = 0
    for url in urls:
        result = fetcher.fetch(
            FetchRequest(url=url, timeout_s=timeout, allow_browser=False, max_attempts=1)
        )
        if not result.ok:
            failed += 1
            reason = result.failure_reason or "unknown"
            by_reason[reason] = by_reason.get(reason, 0) + 1
    return {
        "total": len(urls),
        "failed": failed,
        "fail_rate": round(failed / len(urls), 2),
        "by_reason": by_reason,
    }
