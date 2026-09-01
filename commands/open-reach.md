---
description: "막힌 공개 웹 소스를 open-reach 로 가져오거나, 왜 못 가져왔는지 분류해 보고한다. 로그인월·페이월은 돌파하지 않고 감지·보고만."
argument-hint: <URL> [--intent article|media|raw] [--allow-browser]
---

# /open-reach

표준 fetch(WebFetch/curl)가 **403·WAF 챌린지·봇 차단**으로 막힌 공개 URL 에 대해,
정책상 허용되는 공개 접근 경로를 순서대로 시도한다.

## 실행

`skills/open-reach` 스킬을 사용해 다음을 실행한다:

```bash
cd "${CLAUDE_PLUGIN_ROOT}/skills/open-reach"
python -m open_reach.engine fetch "$ARGUMENTS"
```

정책 판정만 미리 보려면(실제 요청 없이):

```bash
python -m open_reach.engine explain "$ARGUMENTS"
```

## 결과 해석

- **종료코드 0** — 본문 마크다운 확보. 그대로 리서치 근거로 쓴다.
- **종료코드 1** — 네트워크·검증 실패. 재시도하거나 대체 공개 소스를 찾는다.
- **종료코드 2** — `auth_wall`/`paywall`/`policy_blocked`. **정책상 접근 불가**한 경계다.
  돌파하지 말고 "로그인/구독이 필요해 공개 접근 대상이 아니다"라고 보고한 뒤 대체 소스를 찾는다.

open-reach 는 공개 콘텐츠만 취급하며, 인증 우회·CAPTCHA 해결·프록시 로테이션·SSRF 를 하지 않는다
(코드 정책 계층에서 fail-closed 강제). 자세한 경계는 스킬 문서와 `docs/policy-boundaries.md` 참고.
