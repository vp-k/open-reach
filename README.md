# open-reach

**공개 웹 문서를 정직하게 가져오거나, 왜 못 가져왔는지 분류해 보고한다.**

리서치 중 공개 소스가 표준 fetch(WebFetch/curl)로 막히면(WAF 403·JS 챌린지·봇 차단),
조사의 근거가 "실제로 중요한 소스"가 아니라 **"우연히 열리는 소스"**로 좁혀진다. open-reach 는
정책상 허용되는 공개 접근 경로를 순서대로 시도하고, **결과·한계·근거를 재현 가능하게** 남긴다.
성공하면 본문 마크다운을, 실패하면 분류된 사유와 시도 이력을 낸다.

이 저장소는 [devncat 마켓플레이스](https://github.com/vp-k/devncat)의 Claude Code 플러그인이다.

## 설치

```
/plugin marketplace add vp-k/devncat
/plugin install open-reach
```

설치만 하면 동작한다(API 키·로그인·수동 설정 0회). 순수 표준 라이브러리로 동작하며,
`curl_cffi` 가 있으면 브라우저 TLS 임퍼소네이션을 추가로 쓴다(없어도 됨).

## 사용

Claude 가 리서치 중 막힌 소스를 만나면 `open-reach` 스킬을 자동으로 쓴다. 직접 실행도 가능하다:

```bash
cd skills/open-reach
python -m open_reach.engine fetch "https://example.com/article"
python -m open_reach.engine explain "https://example.com/article"   # 정책 판정만 미리 보기
```

슬래시 커맨드: `/open-reach <URL>`

## 경계 (완화 금지)

공개 콘텐츠만 취급한다. 코드의 정책 계층에서 fail-closed 로 강제된다:

- 로그인월·페이월 **미돌파**(감지·보고만, 종료코드 2)
- 인증 우회·CAPTCHA 해결·프록시 로테이션·지속 신원 위장 없음
- rate limit 존중 · **SSRF 차단**(사설 IP·루프백·메타데이터 fail-closed)
- 취득 본문 미보관

## 문서

- [`docs/overview.md`](docs/overview.md) — 문제 정의·Non-Goals(헌법)
- [`docs/SPEC.md`](docs/SPEC.md) — 데이터 모델·인수 기준·실패 사유 분류
- [`docs/adr/`](docs/adr/) — 주요 설계 결정
- [`docs/policy-boundaries.md`](docs/policy-boundaries.md) — 경계 상세

## 라이선스

`NOTICE` 참고. 원본 `fivetaku/insane-search`(MIT)의 WAF 프로필을 시드로 참조했으며 출처를 명시한다
(ADR-003).
