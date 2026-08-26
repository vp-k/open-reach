"""지문표 자동 갱신 — 관측된 성공 경로를 근거로 후보 순서를 재정렬한다.

근거(성공 관측)가 0건이면 아무것도 바꾸지 않는다. 추측으로 지문표를 흔들지 않는다.
기록은 임시 파일 + rename 으로 원자적으로 수행한다 (AC-B-007-3).
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from . import observe, yamlio
from .models import utc_today


def leading_comments(text: str) -> str:
    """파일 선두의 주석 블록 — 시드 출처 고지(ADR-003)가 여기 있으므로 보존한다."""
    kept: list[str] = []
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            kept.append(line)
            continue
        break
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept) + "\n" if kept else ""


def _evidence(records: list[dict]) -> dict[str, dict[str, int]]:
    """{vendor: {impersonate 표기: 성공 횟수}}. 성공 관측만 들어온다 (AC-B-006-5)."""
    table: dict[str, dict[str, int]] = {}
    for record in records:
        if record.get("outcome") != "success":
            continue
        vendor = str(record.get("waf_vendor") or "none")
        key = record.get("impersonate")
        label = "-" if key is None else str(key)
        table.setdefault(vendor, {})
        table[vendor][label] = table[vendor].get(label, 0) + 1
    return table


def plan_update(current: dict[str, Any], records: list[dict]) -> dict[str, Any]:
    """새 지문표 데이터를 만든다 (순수 함수 — 파일을 건드리지 않는다).

    근거가 있는 벤더 프로파일만 손댄다. 관측되지 않은 벤더는 그대로 둔다.
    """
    evidence = _evidence(records)
    updated = dict(current)
    profiles: list[dict[str, Any]] = []

    for profile in current.get("profiles") or []:
        if not isinstance(profile, dict):
            profiles.append(profile)
            continue
        vendor = str(profile.get("vendor") or "")
        hits = evidence.get(vendor)
        if not hits:
            profiles.append(profile)
            continue

        entry = dict(profile)
        entry["observed_success"] = sum(hits.values())

        candidates = list(entry.get("impersonate_candidates") or [])
        if candidates:
            # 성공 횟수 내림차순, 동률은 기존 순서 유지 — 근거가 없으면 흔들지 않는다
            order = {name: index for index, name in enumerate(candidates)}
            candidates.sort(key=lambda name: (-hits.get(name, 0), order[name]))
            entry["impersonate_candidates"] = candidates

        entry["last_reviewed"] = utc_today()  # AC-B-007-2
        profiles.append(entry)

    updated["profiles"] = profiles
    return updated


def run(*, dry_run: bool) -> tuple[int, str]:
    """(exit_code, 출력 문자열)."""
    path = observe.profiles_path()
    if not path.exists():
        return 1, f"지문표가 없다: {path}"

    records = [
        r
        for r in observe.read_jsonl(observe.observations_path())
        if r.get("outcome") == "success"
    ]
    if not records:
        return 0, "no observations — 근거가 없어 지문표를 바꾸지 않는다."

    before = path.read_text(encoding="utf-8")
    try:
        current = yamlio.loads(before)
    except yamlio.YamlError as exc:
        # SPEC Response 4 — 파싱 실패는 사용 오류다 (일반 실패 1 이 아니다)
        return 4, f"지문표 파싱 실패: {exc}"
    if not isinstance(current, dict):
        return 4, "지문표 최상위가 매핑이 아니다"

    after = leading_comments(before) + yamlio.dumps(plan_update(current, records))
    diff = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="profiles.yaml (before)",
            tofile="profiles.yaml (after)",
            lineterm="",
        )
    )

    header = [
        f"observations={len(records)} profiles_path={path}",
        "mode=dry-run" if dry_run else "mode=apply",
    ]
    body = diff if diff else ["(변경 없음 — 관측이 기존 순서를 그대로 지지한다)"]

    if not dry_run and diff:
        observe.atomic_write(path, after)

    return 0, "\n".join(header + body)
