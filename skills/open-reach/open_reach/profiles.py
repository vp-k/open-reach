"""지문표(`profiles.yaml`) 로드와 시도 계획 수립.

R1 은 URL 변형을 아직 구현하지 않으므로 실행 가능한 변형은 `original` 하나다.
계획에 없는 것을 계획에 있는 척하지 않는다 (NG-10).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import observe, transport, yamlio

SUPPORTED_VARIANTS = ("original",)

# `example.com`·`www.site.co.kr` 같은 호스트/도메인 리터럴 (NG-9)
_HOST_LITERAL = re.compile(r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]{2,})+\b", re.I)
_URL_LITERAL = re.compile(r"https?://", re.I)


class ProfilesError(ValueError):
    """지문표를 읽을 수 없거나 스키마가 어긋났다."""


def lint(profiles: list[dict[str, Any]]) -> list[str]:
    """`detectors[].pattern` 의 호스트·도메인 리터럴을 잡는다 (SPEC 213, NG-9).

    사이트별 예외를 지문표에 축적하기 시작하면 이 도구는 "일반적인 취득 엔진"이
    아니라 "우리가 아는 사이트 목록"이 된다. 벤더 지문은 벤더의 것이어야 한다.
    """
    violations: list[str] = []
    for profile in profiles:
        vendor = profile.get("vendor", "?")
        for detector in profile.get("detectors") or []:
            pattern = str(detector.get("pattern", ""))
            if not pattern:
                continue
            if _URL_LITERAL.search(pattern) or _HOST_LITERAL.search(pattern):
                violations.append(
                    f"{vendor}.{detector.get('id', '?')}: 호스트·도메인 리터럴 금지 — {pattern!r}"
                )
    return violations


def load(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or observe.profiles_path()
    if not target.exists():
        raise ProfilesError(f"지문표가 없다: {target}")
    try:
        data = yamlio.loads(target.read_text(encoding="utf-8"))
    except yamlio.YamlError as exc:
        raise ProfilesError(f"지문표 파싱 실패: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), list):
        raise ProfilesError("지문표 최상위는 `profiles:` 리스트여야 한다")
    profiles = [p for p in data["profiles"] if isinstance(p, dict)]
    violations = lint(profiles)
    if violations:
        raise ProfilesError("지문표 린트 위반 (NG-9):\n  " + "\n  ".join(violations))
    return profiles


def profile_for(profiles: list[dict[str, Any]], vendor: str) -> dict[str, Any]:
    for profile in profiles:
        if profile.get("vendor") == vendor:
            return profile
    for profile in profiles:
        if profile.get("vendor") == "none":
            return profile
    return {"vendor": vendor, "impersonate_candidates": [], "impersonate_avoid": []}


def candidates_for(profile: dict[str, Any]) -> list[str | None]:
    """실제로 실행 가능한 임퍼소네이션 후보만 돌려준다."""
    if not transport.impersonation_available():
        # 후보를 나열해도 전부 같은 요청이 된다 — 같은 요청의 반복은 시도가 아니다.
        return [None]
    avoid = set(profile.get("impersonate_avoid") or [])
    candidates = [c for c in (profile.get("impersonate_candidates") or []) if c not in avoid]
    return list(candidates) or [None]


def build_plan(
    profile: dict[str, Any],
    *,
    max_attempts: int,
    prior: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """시도 격자를 만든다. 직전 성공 경로가 있으면 맨 앞으로 올린다 (AC-B-006-4)."""
    variants = [v for v in (profile.get("transform_order") or ["original"]) if v in SUPPORTED_VARIANTS]
    if not variants:
        variants = ["original"]

    steps: list[dict[str, Any]] = []
    for variant in variants:
        for impersonate in candidates_for(profile):
            steps.append({"route": "http", "impersonate": impersonate, "url_variant": variant})

    if prior:
        key = (prior.get("route"), prior.get("impersonate"), prior.get("url_variant"))
        for index, step in enumerate(steps):
            if (step["route"], step["impersonate"], step["url_variant"]) == key:
                steps.insert(0, steps.pop(index))
                break

    steps = steps[: max(1, max_attempts)]
    for order, step in enumerate(steps, 1):
        step["order"] = order
    return steps
