"""R5 — endpoints 쿼리 치환자·검색 선언의 **변이 사멸** 테스트.

R5 가 여는 것은 정확히 두 가지다: ① chain 없는 endpoints 템플릿의 쿼리 값 위치
치환자(AC-B-010-11 R5 개정), ② 선언된 검색 URL 의 nav_shell 면제(AC-B-014).
여기서 고정하는 것은 "열린 폭이 정확히 그만큼인가"다 — 각 테스트에 죽여야 할
변이를 적어 둔다. 인수 테스트(us-b-012·014)가 엔진 전체 경로를 보므로, 여기는
함수 단위의 경계(위치 인지 금지 문자, 합산 상한, 선언 검증)를 좁게 조인다.
"""

import pathlib
import sys

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import api_index, detect  # noqa: E402

_PROVENANCE = '''    source: "https://docs.invalid/api"
    verified_at: "2026-09-02"
'''

_QUERY_ENDPOINT_YAML = (
    """entries:
  - host: h.invalid
    url_pattern: '^/item\\?id=(?P<id>[0-9]+)$'
"""
    + _PROVENANCE
    + """    response_kind: json
    content_pointer: "text"
    endpoints:
      - "https://api.invalid/v1/items?id={id}"
"""
)

_CHAIN_QUERY_YAML = (
    """entries:
  - host: h.invalid
    url_pattern: "^/x/(?P<name>[a-z]+)$"
"""
    + _PROVENANCE
    + """    response_kind: html
    chain:
      - request: "https://api.invalid/v1/meta?name={name}"
        response_kind: html
"""
)

_FRAGMENT_YAML = (
    """entries:
  - host: h.invalid
    url_pattern: "^/x/(?P<name>[a-z]+)$"
"""
    + _PROVENANCE
    + """    response_kind: html
    endpoints:
      - "https://api.invalid/v1/{name}#frag{name}"
"""
)

_SEARCH_YAML = (
    """entries:
  - host: h.invalid
    url_pattern: "^/x/(?P<name>[a-z]+)$"
"""
    + _PROVENANCE
    + """    response_kind: html
    endpoints:
      - "https://api.invalid/v1/{name}"
search:
  - host: s.invalid
    url_pattern: '^/find\\?q=.+'
"""
    + _PROVENANCE
)


def _load(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return api_index.load(p)


# ── AC-B-010-11 R5 개정: 쿼리 치환자의 허용 폭 ──────────────────────────


def test_query_placeholder_allowed_only_in_endpoints(tmp_path):
    """죽여야 할 변이: `allow_query_placeholders=True` 를 chain 검사에도 넘기기.

    endpoints 의 치환 입력은 입력 URL 캡처뿐이라 "응답이 쿼리 구조를 바꾼다"가
    성립하지 않지만, chain 은 응답 유래 값이 섞이므로 원래 금지의 근거가 산다.
    """
    idx = _load(tmp_path, "ok.yaml", _QUERY_ENDPOINT_YAML)
    assert len(idx.entries) == 1

    with pytest.raises(api_index.IndexLoadError):
        _load(tmp_path, "chain.yaml", _CHAIN_QUERY_YAML)


def test_fragment_placeholder_is_always_rejected(tmp_path):
    """죽여야 할 변이: allow_query_placeholders 가 프래그먼트 검사까지 끄기."""
    with pytest.raises(api_index.IndexLoadError):
        _load(tmp_path, "frag.yaml", _FRAGMENT_YAML)


def test_substitute_is_position_aware():
    """죽여야 할 변이: 쿼리 위치에도 SEGMENT_FORBIDDEN 만 적용하기 (혹은 그 반대).

    `=` 는 경로 세그먼트에서는 원래 합법이다 — 전역으로 금지하면 기존에 정상이던
    경로 값이 깨지고(회귀), 쿼리에서 허용하면 값이 키/값 경계를 바꾼다.
    """
    # 쿼리 위치: `&`·`=` 거부 (쿼리 구조 변경 차단)
    for bad in ("45&x=1", "45=1"):
        with pytest.raises(api_index.Rejected):
            api_index.substitute("https://api.invalid/v1/items?id={id}", {"id": bad})
    # 쿼리 위치도 경로 금지 문자를 상속한다 (`/` 등)
    with pytest.raises(api_index.Rejected):
        api_index.substitute("https://api.invalid/v1/items?id={id}", {"id": "a/b"})
    # 경로 위치: `=` 는 여전히 허용 (위치 인지가 없으면 여기가 빨개진다)
    assert (
        api_index.substitute("https://api.invalid/v1/{tag}", {"tag": "k=v"})
        == "https://api.invalid/v1/k=v"
    )
    # 정상 쿼리 치환
    assert (
        api_index.substitute("https://api.invalid/v1/items?id={id}", {"id": "45"})
        == "https://api.invalid/v1/items?id=45"
    )


def test_substitute_common_rejections_apply_to_query_values():
    """죽여야 할 변이: 쿼리 브랜치에서 빈 값·공백·점 세그먼트 검사를 빼기."""
    template = "https://api.invalid/v1/items?id={id}"
    for bad in ("", " ", "a b", ".", ".."):
        with pytest.raises(api_index.Rejected):
            api_index.substitute(template, {"id": bad})


# ── entry_for: `경로?쿼리` 매칭 (R5 개정) ────────────────────────────────


def test_entry_for_matches_path_with_query():
    """죽여야 할 변이: 매칭 대상을 경로만으로 되돌리기."""
    entries = [
        {"host": "h.invalid", "url_pattern": r"^/item\?id=(?P<id>[0-9]+)$"},
    ]
    found = api_index.entry_for(entries, "https://h.invalid/item?id=45")
    assert found is not None and found[1] == {"id": "45"}
    # 앵커 덕에 여분 파라미터는 매치 자체가 안 된다 — 느슨한 패턴은 substitute 가 막는다
    assert api_index.entry_for(entries, "https://h.invalid/item?id=45&x=1") is None


def test_entry_for_query_less_urls_are_unchanged():
    """죽여야 할 변이: 쿼리 없는 URL 에 `?` 를 붙여 매칭하기 (기존 패턴 회귀)."""
    entries = [{"host": "h.invalid", "url_pattern": "^/questions/(?P<id>[0-9]+)"}]
    found = api_index.entry_for(entries, "https://h.invalid/questions/12/title")
    assert found is not None and found[1] == {"id": "12"}


# ── AC-B-010-15 R5 개정: 합산 상한 + AC-B-014-4: 선언 검증 ───────────────


def _bulk_yaml(n_entries: int, n_search: int) -> str:
    lines = ["entries:"]
    for i in range(n_entries):
        lines += [
            f'  - host: h{i}.invalid',
            f'    url_pattern: "^/a{i}/(?P<name>[a-z]+)$"',
            '    source: "https://docs.invalid/api"',
            '    verified_at: "2026-09-02"',
            "    response_kind: html",
            "    endpoints:",
            '      - "https://api.invalid/v1/{name}"',
        ]
    if n_search:
        lines.append("search:")
        for i in range(n_search):
            lines += [
                f'  - host: s{i}.invalid',
                '    url_pattern: "^/find"',
                '    source: "https://docs.invalid/api"',
                '    verified_at: "2026-09-02"',
            ]
    return "\n".join(lines) + "\n"


def test_cap_counts_entries_and_search_together(tmp_path):
    """죽여야 할 변이: 상한 검사에서 search 를 빼기 (entries 만 세기).

    NG-9 가 막은 "목록의 무한 증식"이 search 쪽으로 우회하면 상한이 장식이 된다.
    """
    idx = _load(tmp_path, "at-cap.yaml", _bulk_yaml(19, 1))
    assert len(idx.entries) + len(idx.search) == api_index.MAX_ENTRIES

    with pytest.raises(api_index.IndexLoadError):
        _load(tmp_path, "over.yaml", _bulk_yaml(20, 1))


@pytest.mark.parametrize(
    "mutation",
    [
        ('    source: "https://docs.invalid/api"\n', ""),          # source 누락
        ('    verified_at: "2026-09-02"\n', ""),                    # verified_at 누락
        ('"https://docs.invalid/api"', '"http://docs.invalid/api"'),  # http 출처
        ("'^/find\\?q=.+'", "'^/find(?q=.+'"),                      # 패턴 컴파일 실패
        ("host: s.invalid", "host: s{x}.invalid"),                  # host 치환자
    ],
)
def test_search_declaration_is_validated(tmp_path, mutation):
    """죽여야 할 변이: `_check_search` 에서 출처·패턴·host 검사 중 하나를 빼기.

    선언은 요청을 만들지 않지만 "이 URL 이 검색이다"는 주장이다 — 주장은 출처
    없이 성립하지 않는다 (AC-B-014-4). 검증 위치는 로드 시점(exit 3)이다.
    """
    old, new = mutation
    # search 블록(마지막 출현)만 변이한다 — entries 쪽 출현은 건드리지 않는다.
    head, sep, tail = _SEARCH_YAML.rpartition(old)
    assert sep, f"변이 대상이 없다: {old!r}"
    with pytest.raises(api_index.IndexLoadError):
        _load(tmp_path, "mut.yaml", head + new + tail)


def test_search_section_must_be_a_list(tmp_path):
    with pytest.raises(api_index.IndexLoadError):
        _load(tmp_path, "notlist.yaml", _SEARCH_YAML.split("search:")[0] + "search: {}\n")


# ── AC-B-014-1·2: is_explicit_search ─────────────────────────────────────


def test_is_explicit_search_scope(tmp_path):
    """죽여야 할 변이: host 대조를 빼거나 패턴 매칭을 prefix 검사로 바꾸기."""
    idx = _load(tmp_path, "s.yaml", _SEARCH_YAML)
    assert api_index.is_explicit_search(idx, "https://s.invalid/find?q=rust") is True
    # 다른 호스트·패턴 불일치·빈 쿼리는 전부 False
    assert api_index.is_explicit_search(idx, "https://h.invalid/find?q=rust") is False
    assert api_index.is_explicit_search(idx, "https://s.invalid/other?q=rust") is False
    assert api_index.is_explicit_search(idx, "https://s.invalid/find") is False
    # 인덱스가 없으면(모듈 monkeypatch 등) 판정은 조용히 False 다
    assert api_index.is_explicit_search(None, "https://s.invalid/find?q=rust") is False


# ── AC-B-014-1·3: classify 의 면제 폭 ────────────────────────────────────

# 검색 결과 목록의 형태 — 짧은 블록의 나열, 합계는 길이 하한 이상.
_RESULTS = "\n\n".join(
    f"항목 {i} — rust 주제를 다루는 공개 문서의 한 줄 요약이 여기 놓인다." for i in range(10)
)

_CHALLENGE = (
    "We've detected unusual activity from your computer network\n\n"
    "To continue, please click the box below to let us know you're not a robot. "
    "Please make sure your browser supports JavaScript and cookies."
)


def test_explicit_search_exempts_only_nav_shell():
    """죽여야 할 변이: 면제를 substantial 전체(길이 하한 포함)로 넓히기.

    기본 판정에서 이 형태는 nav_shell 이어야 하고(전제 검증), explicit_search 는
    정확히 그 판정 하나만 뒤집는다.
    """
    assert len(_RESULTS) >= detect.MIN_ARTICLE_CHARS
    base = detect.classify(200, f"<html><body>{_RESULTS}</body></html>", _RESULTS)
    assert base.reason == "validation_failed" and base.signals == ("nav_shell",)

    exempt = detect.classify(
        200, f"<html><body>{_RESULTS}</body></html>", _RESULTS, explicit_search=True
    )
    assert exempt.outcome == "success" and exempt.reason is None

    # 길이 하한은 면제되지 않는다 — 빈 결과 페이지는 검색 URL 이라도 실패다
    short = _RESULTS[: detect.MIN_ARTICLE_CHARS - 10]
    verdict = detect.classify(
        200, f"<html><body>{short}</body></html>", short, explicit_search=True
    )
    assert verdict.outcome != "success"


def test_explicit_search_does_not_mask_challenges():
    """죽여야 할 변이: explicit_search 를 wall/challenge 판별보다 먼저 보기 (AC-B-014-3)."""
    verdict = detect.classify(
        200, f"<html><body>{_CHALLENGE}</body></html>", _CHALLENGE, explicit_search=True
    )
    assert verdict.reason == "waf_challenge"


# ── codex 리뷰 R5 수정 4종 — 각 수정의 변이 사멸 ─────────────────────────


def test_query_placeholder_forbidden_in_param_name(tmp_path):
    """죽여야 할 변이(R5-H2): 쿼리 치환자 허용을 이름 위치까지 넓히기.

    `?{key}=1` 은 입력 캡처가 **어떤 파라미터를 보낼지**를 고르게 한다 — 값
    위치("무엇을 조회하나")와 달리 요청의 형태 자체가 입력에 넘어간다. 로드
    시점(exit 3)에 거부되어야 요청이 아예 안 나간다.
    """
    bad_name = _QUERY_ENDPOINT_YAML.replace(
        "https://api.invalid/v1/items?id={id}", "https://api.invalid/v1/items?{id}=1"
    )
    with pytest.raises(api_index.IndexLoadError):
        _load(tmp_path, "badname.yaml", bad_name)

    # 되다 만 중괄호 — 올바른 치환자가 아니면 값 위치라도 거부
    dangling = _QUERY_ENDPOINT_YAML.replace(
        "https://api.invalid/v1/items?id={id}", "https://api.invalid/v1/items?id={id"
    )
    with pytest.raises(api_index.IndexLoadError):
        _load(tmp_path, "dangling.yaml", dangling)

    # 값 위치의 올바른 치환자는 그대로 통과 (수정이 허용 폭을 좁히지 않았다)
    idx = _load(tmp_path, "ok2.yaml", _QUERY_ENDPOINT_YAML)
    assert len(idx.entries) == 1


def test_host_match_semantics(tmp_path):
    """죽여야 할 변이(R5-M1): hostname 비교 분기가 userinfo 를 무시하기 /
    포트 명시 선언이 다른 포트에 업히기 / 포트 없는 선언이 포트에 막히기.

    선언의 단위는 호스트다 — 포트 없는 선언은 모든 포트를 덮는다 (동결 픽스처
    인덱스가 `127.0.0.1` 선언 + 임시 포트 서버로 이 의미론을 계약해 둠, us-b-009).
    포트를 적으면 정확히 그 netloc 만이다. userinfo 실린 URL 은 어느 쪽에도
    매치되지 않는다 — 자격증명 미취급 도구가 인증 의미가 실린 URL 을 "확인된
    선언 대상"으로 판정할 수 없다.
    """
    entries = [{"host": "h.invalid", "url_pattern": r"^/item\?id=(?P<id>[0-9]+)$"}]
    assert api_index.entry_for(entries, "https://h.invalid/item?id=45") is not None
    # 포트 없는 선언 = 모든 포트 (픽스처 계약)
    assert api_index.entry_for(entries, "https://h.invalid:8443/item?id=45") is not None
    # userinfo 는 항상 거부
    assert api_index.entry_for(entries, "https://user@h.invalid/item?id=45") is None
    assert api_index.entry_for(entries, "https://u:p@h.invalid:8443/item?id=45") is None

    ported = [{"host": "127.0.0.1:8080", "url_pattern": r"^/item\?id=(?P<id>[0-9]+)$"}]
    assert api_index.entry_for(ported, "http://127.0.0.1:8080/item?id=45") is not None
    assert api_index.entry_for(ported, "http://127.0.0.1:9090/item?id=45") is None

    idx = _load(tmp_path, "hostmatch.yaml", _SEARCH_YAML)
    assert api_index.is_explicit_search(idx, "https://user@s.invalid/find?q=x") is False


def test_declared_host_with_userinfo_is_rejected_at_load(tmp_path):
    """죽여야 할 변이(R5-M1 잔존): 선언 host 의 `@` 를 로드가 통과시키기.

    선언에 `user@h.invalid` 를 적으면 netloc 정확 일치 분기가 자격증명 실린
    URL 을 통과시킨다 — 로드 시점(exit 3)에 거부해야 경로가 닫힌다. entries·
    search 양쪽 다.
    """
    with pytest.raises(api_index.IndexLoadError):
        _load(
            tmp_path, "ui-entry.yaml",
            _QUERY_ENDPOINT_YAML.replace("host: h.invalid", "host: user@h.invalid"),
        )
    with pytest.raises(api_index.IndexLoadError):
        _load(
            tmp_path, "ui-search.yaml",
            _SEARCH_YAML.replace("host: s.invalid", "host: user@s.invalid"),
        )


def test_userinfo_url_never_matches_even_matching_netloc():
    """죽여야 할 변이(R5-M1 잔존): `@` 가드를 netloc 정확 일치 분기 뒤에 두기.

    _host_matches 는 선언 검사를 가정하지 않고 스스로 fail-closed 여야 한다 —
    선언이 어떤 경로로든 `user@h.invalid` 가 되어도 매치는 일어나지 않는다.
    """
    entries = [{"host": "user@h.invalid", "url_pattern": "^/item"}]
    assert api_index.entry_for(entries, "https://user@h.invalid/item") is None


def test_load_cached_returns_isolated_copies(tmp_path):
    """죽여야 할 변이(R5-L1): load_cached 가 캐시 객체를 그대로 돌려주기.

    호출자가 반환 항목(내부 dict)을 변형하면 같은 경로의 **다음** 판정이
    오염된다 — 캐시는 파싱 비용 절약이지 공유 가변 상태가 아니다.
    """
    p = tmp_path / "iso.yaml"
    p.write_text(_SEARCH_YAML, encoding="utf-8")
    first = api_index.load_cached(str(p))
    first.entries[0]["host"] = "tampered.invalid"
    second = api_index.load_cached(str(p))
    assert second.entries[0]["host"] == "h.invalid"


# ── R5-H1: 선언된 검색 → 리디렉트 이탈 → 면제 상실 (fetcher 경유) ─────────

from open_reach import fetcher, transport  # noqa: E402
from open_reach.models import FetchRequest  # noqa: E402

_SEARCH_ONLY_YAML = (
    """entries:
  - host: h.invalid
    url_pattern: "^/x/(?P<name>[a-z]+)$"
"""
    + _PROVENANCE
    + """    response_kind: html
    endpoints:
      - "https://api.invalid/v1/{name}"
search:
  - host: s.invalid
    url_pattern: '^/find\?q=.+'
"""
    + _PROVENANCE
)


# 검색 결과 목록의 HTML 표현형 — <p> 블록의 나열이라야 extract 뒤에도 짧은 블록이
# 유지되어 기본 판정이 nav_shell 이 된다 (평문 나열은 한 문단으로 합쳐져 통과한다).
_RESULT_HTML = (
    "<html><body>"
    + "".join(f"<p>항목 {i} — rust 요약 한 줄.</p>" for i in range(14))
    + "</body></html>"
)


def _fake_transport(final_url: str):
    def _request(url, **_kwargs):
        html = _RESULT_HTML.encode("utf-8")
        return transport.Response(
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=html,
            final_url=final_url,
            elapsed_ms=1,
        )

    return _request


def _attempt(tmp_path, monkeypatch, final_url):
    p = tmp_path / "h1.yaml"
    p.write_text(_SEARCH_ONLY_YAML, encoding="utf-8")
    monkeypatch.setattr(fetcher.transport, "request", _fake_transport(final_url))
    request = FetchRequest(url="https://s.invalid/find?q=rust", api_index=str(p))
    result = fetcher._attempt_step(
        request,
        {"impersonate": None, "url_variant": "original"},
        deadline=0.0,
        attempts=[],
        budget={},
        explicit_search=api_index.is_explicit_search(
            api_index.load_cached(str(p)), request.url
        ),
    )
    assert result is not None
    return result[4]


def test_redirect_departing_declaration_loses_exemption(tmp_path, monkeypatch):
    """죽여야 할 변이(R5-H1): 입력 URL 판정 하나로 면제를 끝까지 끌고 가기.

    선언된 검색 URL 로 시작해도 서버가 비선언 페이지로 리디렉트하면 도착지는
    우발이다 — nav_shell 판정이 원래대로 돌아와야 한다. AC-B-014-2 의 인수
    케이스(비선언→선언 도착 = 면제 없음)와 합쳐 계약이 양방향으로 조여진다.
    """
    verdict = _attempt(tmp_path, monkeypatch, "https://s.invalid/plain")
    assert verdict.reason == "validation_failed" and verdict.signals == ("nav_shell",)

    # 다른 선언 밖 호스트로 이탈해도 동일
    verdict = _attempt(tmp_path, monkeypatch, "https://other.invalid/find?q=rust")
    assert verdict.reason == "validation_failed"


def test_declared_arrival_keeps_exemption(tmp_path, monkeypatch):
    """전제 검증: 도착 URL 이 여전히 선언 안이면 면제가 산다 (수정의 과잉 차단 방지).

    리디렉트가 없거나(final_url == 입력) 선언 안의 다른 검색 URL 로 정규화되는
    경우까지 면제를 끄면 R5 가 연 것이 도로 닫힌다.
    """
    verdict = _attempt(tmp_path, monkeypatch, "https://s.invalid/find?q=rust")
    assert verdict.outcome == "success"

    verdict = _attempt(tmp_path, monkeypatch, "https://s.invalid/find?q=rust&page=2")
    assert verdict.outcome == "success"
