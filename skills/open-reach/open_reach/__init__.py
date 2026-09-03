"""open-reach — 공개 웹 문서를 정직하게 가져오거나, 왜 못 가져왔는지 분류해 보고한다.

경계(NG-1~NG-13)는 이 패키지의 정책 계층에서 fail-closed 로 강제된다.
자격증명을 취급하지 않으며, 취득 본문을 디스크에 남기지 않는다.
"""

# 이 값은 두 곳에 실린다 — Phase 0 요청의 ``HONEST_UA`` (우리가 상대에게 밝히는 신원) 와
# ``bench`` 증적의 ``engine`` 필드 (측정이 어느 버전의 것인지). 둘 다 사실 진술이므로
# ``.claude-plugin/plugin.json`` 의 version 과 어긋나면 안 된다 (NG-10).
# 어긋남은 tests/unit/test_version_consistency.py 가 잡는다.
__version__ = "2.0.0"
