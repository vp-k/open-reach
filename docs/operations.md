# open-reach 운영 문서 (Operations / Runbook)

이 문서는 open-reach 를 **설치한 뒤 시간이 지나며 유지보수하는** 사람을 위한 것이다.
"무엇인가"는 [`overview.md`](../overview.md), "어떻게 검증되는가"는 [`SPEC.md`](SPEC.md),
"왜 이렇게 결정했나"는 [`adr/`](adr/) 에 있다. 여기서는 **정기적으로 무엇을 하는가**만 다룬다.

운영의 대원칙은 하나다 — **돌파율은 시간이 지나면 떨어진다.** WAF 는 지문·챌린지를
계속 바꾸고, 우리가 시드로 받은 벤더 프로필은 늙는다. 운영은 이 노후를 **조용히 두지 않고
수치로 감지해 갱신하는 일**이다. 이 문서의 모든 절차는 그 한 문장의 파생이다.

---

## 1. 정기 점검 주기 (권장)

| 주기 | 할 일 | 근거 |
|------|-------|------|
| **매 실행(자동)** | 지문 노후 경고 확인 — `last_reviewed` 90일 초과 시 stderr 경고가 뜬다 | §2 · SPEC §263 |
| **월 1회** | `bench --tier 1` 3회 실행 → 돌파율 중앙값·벤더별 분해 확인, 회귀 감지 | §3 |
| **분기 1회 이상** | `refresh` 로 관측 반영 → `last_reviewed` 갱신, 노후 경고 해소 | §4 |
| **원본 갱신 시** | `compare` 로 `fivetaku/insane-search` 대비 격차 재측정 | §3 |
| **경계 검토** | 코드 변경 시마다 경계 회귀 없는지(§6), 브라우저 티어는 A8 4항 유지하는지 | §6 |

> 이 주기는 **권장선**이다. open-reach 는 상주 서비스가 아니라 리서치 중 호출되는 도구이므로,
> 실제 트리거는 "돌파율이 체감상 떨어졌다" 또는 "노후 경고가 떴다" 이다.

---

## 2. 지문 노후 경고 대응 (`last_reviewed`)

각 벤더 프로필(`engine/profiles.yaml`)에는 `last_reviewed` 날짜가 있다. **마지막 실측 검토
시점**이다. `fetch`·`bench` 등이 지문표를 로드할 때, `last_reviewed` 가 **90일을 초과한**
벤더가 있으면 stderr 에 **한 번** 경고한다(SPEC §263):

```
[open-reach] 지문 노후 경고 — 90일 초과: cloudflare(134일), akamai(134일), ... . `refresh` 로 갱신을 검토하라.
```

- 경고는 **fail-closed 가 아니다** — 동작은 계속된다. 노후는 "틀렸다"가 아니라 "오래됐으니
  실측으로 재확인할 때가 됐다" 는 신호다.
- `last_reviewed` 가 **없거나 날짜로 파싱되지 않으면** 신선도를 증명할 수 없으므로 함께
  경고한다(`검토 날짜 불명`). 검토되지 않은 지문을 조용히 통과시키지 않는다(NG-10 정신).
- 임계는 `open_reach/profiles.py` 의 `STALE_THRESHOLD_DAYS = 90` 상수다.

**대응 순서:**

1. `python -m open_reach.engine bench --tier 1 --runs 3` 로 해당 벤더의 실제 돌파율을 본다.
2. 여전히 잘 뚫리면 → 실측이 곧 재검토다. `refresh`(§4)가 관측을 반영하며 `last_reviewed`
   를 오늘로 갱신해 경고를 해소한다.
3. 돌파율이 떨어졌으면 → 지문이 실제로 늙은 것이다. §5 로 프로필을 손본 뒤 재측정한다.

경고를 **날짜만 밀어서** 끄지 않는다(세탁). `last_reviewed` 는 실측 검토의 기록이지 달력이
아니다. 갱신은 `refresh`(관측 근거) 또는 실측 후 §5 수정으로만 한다.

---

## 3. 돌파율 모니터링과 회귀 감지 (`bench` · `compare`)

**정기 계측:**

```bash
cd skills/open-reach
python -m open_reach.engine bench --tier 1 --runs 3
```

- 출력의 `rate_median` 은 3회 실행 돌파율의 중앙값이다(SC-2 합격선 ≥80%, 벤더별 ≥50%).
- `by_vendor` 분해로 **어느 벤더가 떨어졌는지** 국소화한다. 전체 평균만 보면 한 벤더의
  붕괴가 다른 벤더의 여유에 가려진다.
- 결과는 `bench_history` 에 배터리 해시별로 append-only 로 쌓인다. 같은 배터리의 과거
  중앙값과 비교해 **회귀**를 본다.

**원본 대비 격차:**

```bash
python -m open_reach.engine compare --tier 1 --original-cmd "<원본 fetch 명령>" --out bench/evidence/compare-YYYY-MM-DD.json
```

원본(`fivetaku/insane-search`)이 갱신됐거나 우리 돌파율이 의심스러울 때, 같은 배터리에서
양쪽을 돌려 격차를 수치로 남긴다. "우연히"가 아니라 "원본 대비 몇 %p" 로 말한다.

**holdout(과적합 점검):**

```bash
python -m open_reach.engine bench --holdout --runs 3
```

배터리에 **한 번도 넣지 않은** 도메인 집합(`bench/holdout.yaml`)으로 돌린다. 배터리 돌파율
대비 낙폭이 크면(>15%p) 지문이 배터리에 과적합된 것이다(SC-6). holdout 은 배터리와
**서로소**로 유지한다 — 겹치면 점검 의미가 사라진다.

---

## 4. 관측 반영 (`refresh`)

성공한 `fetch` 는 어떤 경로(임퍼소네이션·라우트)로 뚫렸는지 `observations.jsonl` 에
관측으로 남긴다(금지 필드 없음 — 자격증명·쿠키·본문 미보관, NG-4). `refresh` 는 이
관측을 프로필의 우선순위에 반영한다.

```bash
python -m open_reach.engine refresh --dry-run   # 변경 미리보기 (파일 안 씀)
python -m open_reach.engine refresh             # 실제 반영
```

- **관측 존재 → exit 0**, diff 출력, 성공 벤더의 `impersonate_candidates` 를 성공 빈도순
  재정렬, `last_reviewed` 를 오늘로 갱신(AC-B-007-2).
- diff 는 **기계 생성**이다 — 수동 편집 0. 사람이 손으로 프로필 순서를 바꾸지 않는다.
- **경계 위반 관측은 학습하지 않는다** — `outcome != success` 인 관측은 `refresh` 가
  제외한다(AC-B-006-5). 차단·실패에서 배운 "우회"가 프로필에 스며들 수 없다.
- 항상 `--dry-run` 으로 먼저 diff 를 확인한 뒤 반영한다.

---

## 5. 지문·인덱스 유지보수

### 5.1 벤더 지문 추가·수정 (`engine/profiles.yaml`)

- `detectors[].pattern` 에 **호스트명·도메인 리터럴을 넣을 수 없다**(NG-9). 린트가 로드 시
  `ProfilesError` 로 차단한다. 지문은 **벤더의 것**이어야 하지 "우리가 아는 사이트 목록"이
  되어선 안 된다.
- 새 벤더를 선언하면 그 벤더의 **실측 표본이 배터리에 ≥2건** 있어야 한다(bench 거버넌스
  `VENDOR_MIN_PER_TIER1`). 표본 없는 벤더는 SC-8 이 "미측정"이 되어 게이트가 막는다.
- `seeded_from` 은 시드 출처(`insane-search@<commit>`)를 명시한다(ADR-003, NG-7). 원본
  코드를 벤더링하지 않는다.

### 5.2 공개 API 인덱스 (`engine/api_index.yaml`, Phase 0)

- 항목 상한 **20개**, 각 항목은 `source`·`verified_at` 의무(AC-B-010-15). 근거 없는 항목은
  넣지 않는다(NG-10).
- Phase 0 인덱스 조립 체인은 **동일 오리진 유지**가 설계 결정이다(AC-B-010-12). 응답이
  우리를 다른 호스트로 보낼 수 없다. 일반 `fetch` 의 리디렉션 추종과는 다른 규칙임에
  유의(자세한 근거는 `api_index.yaml` 상단 주석과 r3-contract §5).

### 5.3 배터리·holdout (`bench/battery.yaml` · `bench/holdout.yaml`)

- 각 항목은 `expected`·`tier`·`waf_expected`·`added_reason` 필수, positive 는 검증 assertion
  ≥1(`title_contains`·`body_contains`·`min_chars`·`normalized_hash` 중), tier1 에 negative
  케이스 ≥1(bench 거버넌스 `check_governance`).
- holdout 은 배터리와 도메인이 **서로소**여야 한다(§3). 배터리에 있는 걸 holdout 에 넣으면
  과적합 점검이 무의미해진다.

---

## 6. 경계 상시 확인 (완화 금지)

운영 중 어떤 변경도 아래를 넘어설 수 없다. 이들은 코드 정책 계층에서 fail-closed 로
강제되며(NG-1~NG-13), **완화는 SPEC 재동결(사용자 승인)로만** 가능하다.

- 로그인월·페이월 **미돌파**(감지·보고만, 종료코드 2), CAPTCHA 미해결, 프록시 로테이션
  없음, 지속 신원 위장 없음, rate limit 존중, **SSRF 차단**(사설 IP·루프백·메타데이터),
  취득 본문 미보관.
- **브라우저 티어(T2)** 는 존재 자격이 A8 4항 판정에 걸려 있다(ADR-006 · r3-contract §1):
  ① 신원 비지속(임시 프로필), ② 행동 시뮬 없음, ③ 자격증명·쿠키 미취급, ④ 성공 지표에
  탐지 회피도 없음. **넷 중 하나라도 깨지면 그 티어는 '회피 도구'이며 삭제 대상이다.**
  브라우저 티어에 지문 위조·쿠키 저장·마우스 시뮬을 추가하려는 변경은 거부한다.
- 인수 테스트(`tests/acceptance/`)는 **동결**돼 있다(`.manifest.json` 해시 + SPEC 해시).
  경계를 바꾸려면 SPEC 을 고쳐야 하고, 그것은 `acceptance-freeze --approved-by-user`
  재동결로만 가능하다. 게이트 통과 후 몰래 고치는 세탁을 해시 대조가 막는다.

---

## 7. 트러블슈팅

| 증상 | 원인 | 대응 |
|------|------|------|
| 돌파율이 전반적으로 낮게 나온다 | `curl_cffi` 미설치 → TLS 임퍼소네이션 없음 | stderr 경고 확인. `curl_cffi` 설치 시 회복(없어도 동작은 함) |
| `--allow-browser` 인데 브라우저가 안 뜬다 | `patchright` 미설치 → `browser_disabled` 로 강등 | 지연 설치 대상이다. 없는 돌파를 지어내지 않는다(NG-10). 필요 시 patchright 설치 |
| `refresh` 가 "관측 없음"으로 끝난다 | 성공 `fetch` 이력이 아직 없다 | 실제 `fetch` 를 몇 번 돌린 뒤 재시도 |
| 로드 시 `ProfilesError: 린트 위반` | 지문 `pattern` 에 호스트 리터럴이 들어갔다(NG-9) | 해당 detector 를 벤더 일반 신호로 바꾼다(§5.1) |
| bench 가 `gated`/`baseline_unsafe` | negative 케이스의 `failure_reason` 불일치 등 거버넌스 위반 | `check_governance` 메시지대로 배터리 항목 교정(§5.3) |
| 노후 경고가 계속 뜬다 | 90일 초과 프로필이 실측 재검토되지 않았다 | §2 순서대로 `bench` → `refresh` |

---

## 8. 배포 (유지보수자용)

open-reach 는 devncat 마켓플레이스에 **HTTPS git URL 직접 참조**로 등록돼 있다. 플러그인
레포(`vp-k/open-reach`)에 푸시하면 사용자는 `/plugin marketplace update` 로 즉시 받는다.

- 동작·기능 변경 시 **버전을 올린다**: `.claude-plugin/plugin.json` 의 `version`(SemVer),
  필요 시 SKILL.md·루트 CLAUDE.md 표기.
- 커밋 규약: 플러그인 레포에 먼저 push → devncat 루트에서 서브모듈 ref 갱신(루트에서
  `plugins/` 내부 파일을 직접 add 하지 않는다 — 서브모듈이 깨진다).

---

*이 문서는 R4 산출물이다(SPEC §568: "마켓플레이스 등록 · `last_reviewed` 노후 경고 · 운영 문서").*
