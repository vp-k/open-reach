# 코드 리뷰 R11 — 분류기·추출기·거버넌스 경로 (codex)

- **일시**: 2026-08-28
- **리뷰어**: codex (외부 CLI, fresh context)
- **대상**: R1 실측에서 나온 5개 변경 — `detect.py`(문면 신호·nav shell), `extract.py`(본문 후보 우선순위), `bench.py`(G-8 `vendor_scope`), `engine.py`(출하 배터리 경로 판정), `transport.py`(임퍼소네이션 시 UA 제거)
- **입력**: `scratchpad/r11.prompt.txt` + diff·신규 파일 전문 1,314줄
- **판정**: CRITICAL 1 · MAJOR 1 · MINOR 0 — **2건 모두 반영**

리뷰 프롬프트에는 제품 불변식을 명시했다: SSRF fail-closed, 윤리 경계, **게이트는
fail-closed**, **돌파율을 부풀릴 수 있는 경로는 결함**. 나온 두 건은 정확히 뒤의 두
불변식을 하나씩 때렸다 — 앞의 R10 이 전송 계층을 봤다면 이번은 **측정 계층**이다.

| # | 심각도 | 지적 | 반영 |
|---|---|---|---|
| 1 | CRITICAL | `engine._shipped_paths` 가 holdout 을 `state_dir()` 기준으로 계산해, `OPENREACH_STATE_DIR` 를 옮기면 진짜 출하 holdout 이 "출하가 아닌" 것이 되고 `role: production` 검사가 꺼진다 | 반영 — 두 경로 모두 `repo_root()/bench/` 기준으로 고정 |
| 2 | MAJOR | 긴 `<noscript>` 안내문이 본문 후보로 채택되면 길이·문단 검사를 통과해 `success` 가 된다 (`js_shell` 검사는 그 뒤에만 있다) | 반영 — `_is_js_notice` 두 축 규칙 신설, 성공 판정 앞으로 이동 |

---

## 1 (CRITICAL) — 방금 막은 우회로가 환경변수로 다시 열려 있었다

바로 앞 라운드에서 고친 것이 "출하 배터리 판정을 **플래그**가 아니라 **경로**로 한다"
였다. SPEC:329 가 막으라고 적어 둔 우회로 — 출하 배터리를 `role: fixture` 로 강등해
G-1(벤더별 ≥2건)을 건너뛰는 길 — 을 닫는 수정이었다.

그런데 그 경로 계산이 이랬다:

```python
return (
    observe.repo_root() / "bench" / "battery.yaml",
    observe.state_dir() / "bench" / "holdout.yaml",   # ← 여기
)
```

`state_dir()` 는 `OPENREACH_STATE_DIR` 로 갈린다. 그러면:

1. `OPENREACH_STATE_DIR=/tmp/state` 로 두고
2. 진짜 출하 파일 `<repo>/bench/holdout.yaml` 을 `--battery` 로 가리키면
3. 비교 대상이 `/tmp/state/bench/holdout.yaml` 이라 `_same_file` 이 어긋나 `shipped=False`
4. 그 파일의 `role` 을 `fixture` 로 낮추면 G-1 없이 실행된다

**경로 동일성으로 판정하도록 고쳤는데 그 동일성의 기준점 자체가 환경변수였다.**
문 자물쇠를 갈아 끼우고 열쇠를 문 옆에 걸어 둔 셈이다.

SPEC 을 다시 읽으면 답이 명확하다. :454 가 `OPENREACH_STATE_DIR` 로 옮기라고 한 것은
**상태 파일**(`observations.jsonl`, `bench/history.jsonl` — 실행하면서 쌓이는 것)이고,
:329 는 두 배터리를 `bench/battery.yaml`·`bench/holdout.yaml` 로 **나란히** 적었다.
배터리는 저장소에 체크인되는 출하물이지 상태가 아니다.

```python
bench_dir = observe.repo_root() / "bench"
return (bench_dir / "battery.yaml", bench_dir / "holdout.yaml")
```

회귀 테스트 `test_shipped_paths_do_not_move_with_the_state_dir` — `OPENREACH_STATE_DIR`
를 `monkeypatch` 로 옮긴 뒤 ① 두 경로가 그대로인지 ② 그 상태에서 출하 holdout 을
`--battery` 로 가리켜도 `shipped=True` 인지 둘 다 본다. ①만 보면 경로 계산을 고쳐도
판정 함수가 다른 이유로 어긋나는 경우를 놓친다.

## 2 (MAJOR) — `<noscript>` 를 열어 준 대가

`extract.py` 는 R1 에서 후보 우선순위를 갖게 됐다: `<main>` 안 → 문서 전체 →
`<noscript>` 안. 마지막 후보를 넣은 이유는 정당했다 — 서버가 본문을 안 주고
안내문만 주는 문서에서 **실패 원인이 사라지지 않게** 하려던 것이다(NG-10).

문제는 분류기의 순서였다:

```python
substantial = len(extracted) >= MIN_ARTICLE_CHARS and not _is_nav_shell(extracted)
if substantial:
    return ContentVerdict(None, "success", (), False)   # ← 여기서 끝난다
...
if 200 <= status < 300:
    if _is_js_shell(html):        # ← 여기까지 오지 못한다
```

안내문이 200자를 넘고(길이 통과) 문장 형태이면(`_is_nav_shell` 통과) **성공**이다.
공개 본문은 한 글자도 못 받았는데 돌파율만 오른다 — 프롬프트에 적어 둔 "돌파율을
부풀릴 수 있는 경로" 그 자체다.

### 왜 `html` 전체에 정규식을 걸지 않았나

가장 싼 수정은 `if substantial and not _is_js_shell(html)` 이다. 하지만 `_is_js_shell`
은 `enable javascript|requires javascript|...` 를 **문서 전체**에서 찾는다. 그 문구는
그것을 설명하는 **진짜 기사**에도 나온다(점진적 향상, 접근성, 브라우저 설정 안내…).
그 수정은 정상 기사를 셸로 오판해 돌파율을 반대 방향으로 왜곡한다.

그래서 `_is_nav_shell` 과 같은 모양의 **두 축 규칙**으로 만들었다:

```python
def _is_js_notice(extracted: str, html: str) -> bool:
    if not _JS_REQUIRED.search(extracted):   # ① 손에 쥔 본문이 안내문인가
        return False
    return len(_text_outside_noscript(html)) < MIN_ARTICLE_CHARS   # ② 밖에 본문이 없는가
```

②가 오탐을 막는다. 본문이 따로 있는 문서는 `<noscript>` 를 걷어내도 글자가 남으므로
걸리지 않는다. `_text_outside_noscript` 는 `<script>`·`<style>`·`<template>` 를 먼저
지운다 — 스크립트 소스를 글자로 세면 어떤 셸이든 "본문이 있다" 가 되기 때문이다.

걸렸을 때의 판정은 새로 만들지 않았다. `substantial` 을 통과시키지 않고 떨어뜨리면
기존 2xx 분기가 `validation_failed` + 신호 `js_shell` 로 적는다 — 실패 사유 집합은
SPEC 분류표로 닫혀 있고, 다음 수(브라우저 티어)를 가리키는 신호도 이미 그것이다.

회귀 테스트 4종 (`tests/unit/test_detect_js_notice.py`). 픽스처가 **길이 검사를
통과하는지 먼저 단언**한다 — 픽스처가 우연히 짧아서 통과하면 회귀를 못 잡는데
테스트는 초록으로 남는다.

## 반영 후 상태

| 항목 | 값 |
|---|---|
| 단위 테스트 | 40 passed (R11 전 35 → +5) |
| 동결 인수 스위트 | `total=8 passed=8 failed=0` |
| 재측정 | `bench/evidence/a1-r11-run1.json` — **60/70, 판정이 바뀐 URL 0건** |

재측정을 한 이유는 2번 수정이 성공 판정을 **깎는 방향으로만** 작동하기 때문이다.
보고서 §0 의 X=85.7% 는 수정 전에 잰 값이므로, 그 60건 중에 `<noscript>` 안내문으로
성공 처리된 것이 있었다면 숫자가 내려간다. 대조 결과 70건 전부 판정이 동일했다 —
이 표본에는 해당 경로로 성공한 URL 이 없었고, **§0·§2·§3 의 수치는 그대로 유효하다.**

(crates.io 는 수정 전에도 실패였다. 그 문서의 `<noscript>` 안내문이 73자로 짧아
길이 검사에서 이미 떨어졌기 때문이지 판정 논리가 옳아서가 아니다 — 안내문이 200자만
넘었으면 성공으로 셌을 것이고, 그것이 이 리뷰가 잡은 구멍이다.)

## 남긴 것

MINOR 없음. R10 에서 넘긴 R2 항목(JS 셸 **구제** — 안내문 대신 실제 본문을 가져오는
쪽)은 이번 수정과 방향이 반대가 아니다. 이번 것은 "못 가져왔다는 사실을 정확히
기록하는" 일이고, R2 는 "가져오는" 일이다. 기록이 정확해야 R2 의 성과를 측정할 수 있다.
