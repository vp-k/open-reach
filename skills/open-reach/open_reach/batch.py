"""병렬 배치 취득 — 사용자가 **명시한 유한 목록**을 동시에 가져온다 (R6/W4).

NG-5 는 R6 에서 "단건만"에서 "사용자가 명시한 유한 집합"으로 개정됐다. 크롤러가 되지
않게 하는 실질 방벽은 입력 개수가 아니라 **재귀 부재**이기 때문이다. 이 모듈은 받은
목록만 처리하고, 취득한 본문에서 링크를 뽑아 큐에 다시 넣는 코드를 두지 않는다.

페이싱은 새로 만들지 않는다 — `transport.host_gate` 가 이미 **호스트당 동시성 1 +
최소 간격 1.0 초**를 락으로 강제하므로, 여기서 병렬화하는 것은 전역 워커 수뿐이다.
같은 호스트로 몰린 URL 은 워커가 몇이든 직렬로 나간다. 이 분리가 중요하다: 배치가
자기 페이싱을 따로 구현하면 단건 경로와 두 벌이 되어 한쪽만 고쳐지는 날이 온다.

출력은 URL 당 NDJSON 한 줄이며 단건 `FetchResult` 스키마 그대로다. 본문은 표준 출력으로
흐를 뿐 어디에도 저장하지 않는다 (NG-12).
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Callable, Iterator

from . import fetcher
from .models import BOUNDARY_REASONS, FetchRequest, FetchResult

DEFAULT_CONCURRENCY = 4
MAX_CONCURRENCY = 8
# 상한 있는 수집기다 (NG-5 개정판). 목록이 이보다 길면 사용자가 나눠서 부른다 —
# "긴 목록을 넣으면 알아서 크롤링해 준다" 로 읽히는 도구가 되지 않게 한다.
MAX_URLS = 50


class BatchError(ValueError):
    """입력 자체가 배치로 성립하지 않는다 — 요청이 나가기 전에 거절한다."""


def parse_urls(text: str) -> list[str]:
    """줄 단위 목록을 읽는다. 빈 줄과 `#` 주석은 건너뛴다.

    중복은 **순서를 유지한 채** 제거한다. 같은 URL 을 두 번 두드리는 것은 결과가
    같으면서 상대 서버만 한 번 더 때리는 일이라, 우연한 복붙을 조용히 실행하지 않는다.
    """
    seen: set[str] = set()
    urls: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line in seen:
            continue
        seen.add(line)
        urls.append(line)
    if not urls:
        raise BatchError("배치 목록이 비어 있다")
    if len(urls) > MAX_URLS:
        raise BatchError(
            f"배치 목록이 {len(urls)} 건이다 — 상한은 {MAX_URLS} 건이다 (NG-5)"
        )
    return urls


def check_concurrency(value: int) -> int:
    if not (1 <= value <= MAX_CONCURRENCY):
        raise BatchError(f"--concurrency 는 1..{MAX_CONCURRENCY} 여야 한다")
    return value


def run(
    urls: list[str],
    template: FetchRequest,
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    fetch: Callable[[FetchRequest], FetchResult] | None = None,
) -> Iterator[FetchResult]:
    """목록을 병렬로 취득하고 **입력 순서대로** 결과를 흘린다.

    완료 순서가 아니라 입력 순서로 내는 이유: 동시성 때문에 같은 입력이 실행마다 다른
    순서로 나오면 진단·비교·회귀 감사에서 diff 를 쓸 수 없다. 전체 소요는 같다 —
    모든 작업은 이미 동시에 돌고 있고 여기서는 받아 적는 순서만 고정한다.
    """
    do_fetch = fetch or fetcher.fetch
    if not urls:
        return
    workers = min(check_concurrency(concurrency), len(urls))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_guarded, do_fetch, replace(template, url=url)) for url in urls
        ]
        for future in futures:
            yield future.result()


def _guarded(
    do_fetch: Callable[[FetchRequest], FetchResult], request: FetchRequest
) -> FetchResult:
    """한 건의 실패가 배치 전체를 죽이지 않게 한다.

    다만 **조용히 넘기지는 않는다** (NG-10) — 실패는 `unknown` 사유의 정상적인
    FetchResult 로 그 줄에 남고, 예외 종류·메시지는 stderr 로 나가며, 종료 코드에도
    반영된다. `unknown` 을 쓰는 것은 그것이 사실이기 때문이다: 우리는 왜 실패했는지
    분류하지 못했다. 새 사유를 만들면 SPEC 의 실패 분류표가 배치 때문에 늘어난다.
    """
    try:
        return do_fetch(request)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[open-reach] batch: {request.url} — {type(exc).__name__}: {exc}\n")
        return FetchResult(
            url=request.url,
            ok=False,
            content_markdown=None,
            metadata=None,
            failure_reason="unknown",
            attempts=[],
            final_route=None,
        )


def exit_code(results: list[FetchResult]) -> int:
    """전부 성공 0 / 실패가 경계 사유뿐이면 2 / 그 밖의 실패가 하나라도 있으면 1.

    경계(로그인월·페이월·정책)만 남은 배치를 1 로 내면 "고칠 수 있는 실패" 와 "넘지
    않기로 한 벽" 이 호출자에게 같아 보인다. 단건 경로가 exit 2 로 그 둘을 갈라 놓은
    것과 같은 이유다.
    """
    failures = [r.failure_reason for r in results if not r.ok]
    if not failures:
        return 0
    if all(reason in BOUNDARY_REASONS for reason in failures):
        return 2
    return 1
