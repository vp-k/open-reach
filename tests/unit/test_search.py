"""R6/W5 — 검색 계층의 **변이 사멸** 테스트.

이 라운드에서 open-reach 는 "URL 하나를 받는 fetcher" 에서 "질의를 받는 서처" 가
된다. NG-5 를 "단건만" 에서 "사용자가 명시한 유한 집합" 으로 개정하면서, 크롤러가
되지 않게 하는 방벽은 **입력 개수** 가 아니라 **재귀 부재** 하나로 좁아졌다.
그래서 여기서 가장 중요한 테스트는 마지막의 구조 검사다 — `search` 가 취득 본문에
닿는 경로를 애초에 임포트하지 않는다는 것.

나머지는 "열린 폭이 정확히 그만큼인가" 를 조인다: 질의 치환의 안전 근거(퍼센트
인코딩), 후보 정규화, 소스별 상한과 인터리브, 그리고 인덱스 선언 검증.
"""

import ast
import pathlib
import sys

import pytest

sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parents[2] / "skills" / "open-reach")
)

from open_reach import api_index, engine, fetcher, policy, search  # noqa: E402

_PROVENANCE = """    source: "https://docs.invalid/api"
    verified_at: "2026-09-03"
"""


def _yaml(body: str) -> str:
    # 인덱스 최상위는 `entries:` 를 요구한다 — 검색 소스만 선언한 인덱스도 성립한다
    return "entries: []\nsearch_sources:\n" + body


def _load(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return api_index.load(path)


_JSON_SOURCE = _yaml(
    """  - name: alpha
    host: a.invalid
    kind: json
    query_template: "https://a.invalid/s?q={query}"
    result_pointer: items
    link_pointer: url
    title_pointer: title
"""
    + _PROVENANCE
)


# ── ① 입력 검증 ──────────────────────────────────────────────────────────


def test_check_query_rejects_empty_and_oversize():
    assert search.check_query("  clean arch  ") == "clean arch"
    for bad in ("", "   ", "\n"):
        with pytest.raises(search.SearchError):
            search.check_query(bad)
    with pytest.raises(search.SearchError):
        search.check_query("x" * (search.MAX_QUERY_CHARS + 1))
    # 경계는 통과한다 — off-by-one 으로 상한을 하나 낮추는 변이를 죽인다
    assert len(search.check_query("x" * search.MAX_QUERY_CHARS)) == search.MAX_QUERY_CHARS


def test_check_max_results_bounds():
    assert search.check_max_results(1) == 1
    assert search.check_max_results(search.MAX_RESULTS_CAP) == search.MAX_RESULTS_CAP
    for bad in (0, -1, search.MAX_RESULTS_CAP + 1):
        with pytest.raises(search.SearchError):
            search.check_max_results(bad)


# ── ② 질의 치환 ──────────────────────────────────────────────────────────


def test_build_url_percent_encodes_delimiters():
    """죽여야 할 변이: 치환을 그냥 문자열 대입으로 두기.

    질의는 사용자 입력이라 `&`·`=`·`/` 가 정상적으로 들어온다("c++ vs c#", "a/b").
    인코딩 없이 붙이면 질의가 쿼리 구조를 바꿔 **다른 파라미터를 주입**할 수 있다.
    `safe=""` 인코딩을 거치면 결과는 정의상 비예약 문자와 %XX 뿐이다.
    """
    source = {"query_template": "https://a.invalid/s?q={query}&fmt=json"}
    url = search.build_url(source, "a&b=c/d")
    assert url == "https://a.invalid/s?q=a%26b%3Dc%2Fd&fmt=json"
    # 치환 결과 안에 새 구분자가 생기지 않았다
    assert url.count("&") == 1 and url.count("=") == 2


def test_build_url_rejects_over_length():
    source = {"query_template": "https://a.invalid/s?q={query}"}
    with pytest.raises(search.SearchError):
        search.build_url(source, "x" * policy.MAX_URL_LENGTH)


# ── ③ 후보 정규화 ────────────────────────────────────────────────────────


def test_normalize_drops_unusable_and_strips_fragment():
    assert search.normalize("https://x.invalid/a?b=1#frag") == "https://x.invalid/a?b=1"
    for bad in (
        None,
        123,
        "",
        "   ",
        "/relative/path",
        "javascript:alert(1)",
        "mailto:a@b.invalid",
        "ftp://x.invalid/f",
        "https://user:pw@x.invalid/",  # NG-4 — 자격증명 실린 URL 은 취급하지 않는다
    ):
        assert search.normalize(bad) is None


def test_normalize_fragment_stripping_makes_dedupe_work():
    """죽여야 할 변이: 프래그먼트를 남기기 — `#a` 와 `#b` 가 다른 후보가 된다."""
    a = search.normalize("https://x.invalid/doc#one")
    b = search.normalize("https://x.invalid/doc#two")
    assert a == b


# ── ④ 소스 자기 기계장치 제외 ────────────────────────────────────────────


def test_excluded_matches_host_and_subdomains_only():
    """죽여야 할 변이: 접미사 비교에서 점을 빼기 (`notduckduckgo.com` 오탐).

    실측 계기는 ddg 광고다 — 유기적 결과와 같은 래퍼로 나오지만 목적지가
    `duckduckgo.com/y.js` 라 검색 엔진 자신을 가리킨다.
    """
    source = {"exclude_hosts": ("duckduckgo.com",)}
    assert search._excluded("https://duckduckgo.com/y.js?ad_domain=x", source)
    assert search._excluded("https://lite.duckduckgo.com/lite/", source)
    assert not search._excluded("https://notduckduckgo.com/a", source)
    assert not search._excluded("https://example.com/duckduckgo.com", source)
    # 선언이 없으면 아무것도 걷어내지 않는다
    assert not search._excluded("https://duckduckgo.com/y.js", {})


def test_parse_html_drops_excluded_candidates():
    source = {
        "name": "s",
        "result_link_pattern": r'href="//w\.invalid/l\?u=([^"&]+)',
        "link_transform": "percent",
        "exclude_hosts": ("w.invalid",),
    }
    body = (
        '<a href="//w.invalid/l?u=https%3A%2F%2Fw.invalid%2Fy.js%3Fad%3D1">ad</a>'
        '<a href="//w.invalid/l?u=https%3A%2F%2Freal.invalid%2Fpost">real</a>'
    )
    found = search.parse_html(source, body)
    assert [c.url for c in found] == ["https://real.invalid/post"]


def test_parse_json_drops_excluded_candidates():
    source = {
        "name": "s",
        "result_pointer": "items",
        "link_pointer": "url",
        "exclude_hosts": ("w.invalid",),
    }
    payload = {
        "items": [
            {"url": "https://w.invalid/self"},
            {"url": None},  # 링크 없는 항목 — 지어내지 않고 건너뛴다 (NG-10)
            {"url": "https://real.invalid/a"},
        ]
    }
    assert [c.url for c in search.parse_json(source, payload)] == [
        "https://real.invalid/a"
    ]


# ── ⑤ 파싱 ───────────────────────────────────────────────────────────────


def test_parse_json_respects_per_source_cap():
    """죽여야 할 변이: 소스별 상한을 빼기 — 한 소스가 후보 전부를 채운다."""
    source = {"name": "s", "result_pointer": "items", "link_pointer": "url"}
    payload = {
        "items": [{"url": f"https://x.invalid/{i}"} for i in range(search.PER_SOURCE_CAP + 5)]
    }
    assert len(search.parse_json(source, payload)) == search.PER_SOURCE_CAP


def test_parse_json_returns_empty_when_pointer_is_not_a_list():
    source = {"name": "s", "result_pointer": "items", "link_pointer": "url"}
    assert search.parse_json(source, {"items": {"url": "https://x.invalid/"}}) == []
    assert search.parse_json(source, {"other": []}) == []


def test_parse_html_pairs_titles_by_position():
    source = {
        "name": "s",
        "result_link_pattern": r'href="(https://[^"]+)"',
        "title_pattern": r"<h3>([^<]+)</h3>",
    }
    body = '<h3>First</h3><a href="https://a.invalid/1"></a><h3>Second</h3><a href="https://a.invalid/2"></a>'
    found = search.parse_html(source, body)
    assert [(c.url, c.title) for c in found] == [
        ("https://a.invalid/1", "First"),
        ("https://a.invalid/2", "Second"),
    ]


# ── ⑥ 팬아웃 합성 ────────────────────────────────────────────────────────


def test_interleave_is_round_robin():
    """죽여야 할 변이: 이어 붙이기.

    이어 붙이면 `--max-results 10` 이 첫 소스로 다 차서, 팬아웃해 놓고 한 소스만
    쓴 것과 결과가 같아진다.
    """
    a = [search.Candidate(f"https://a/{i}", None, "a") for i in range(3)]
    b = [search.Candidate(f"https://b/{i}", None, "b") for i in range(2)]
    assert [c.url for c in search._interleave([a, b])] == [
        "https://a/0",
        "https://b/0",
        "https://a/1",
        "https://b/1",
        "https://a/2",
    ]


def _stub_query_one(mapping):
    def _inner(source, query, *, timeout, robots_mode):
        found = mapping.get(source["name"], [])
        outcome = search.SourceOutcome(source["name"], "https://e/", True, 200, len(found), 1)
        return outcome, found
    return _inner


def _decl(name):
    return {"name": name, "kind": "json", "host": f"{name}.invalid"}


def test_run_dedupes_across_sources_and_truncates(monkeypatch):
    shared = "https://shared.invalid/doc"
    monkeypatch.setattr(
        search,
        "_query_one",
        _stub_query_one(
            {
                "a": [
                    search.Candidate(shared, "A", "a"),
                    search.Candidate("https://a.invalid/1", None, "a"),
                ],
                "b": [
                    search.Candidate(shared, "B", "b"),
                    search.Candidate("https://b.invalid/1", None, "b"),
                ],
            }
        ),
    )
    candidates, outcomes = search.run(
        "q", [_decl("a"), _decl("b")], max_results=3
    )
    urls = [c.url for c in candidates]
    assert urls == [shared, "https://a.invalid/1", "https://b.invalid/1"]
    # 먼저 본 쪽이 남는다 — dedupe 가 나중 것으로 덮으면 출처가 뒤집힌다
    assert candidates[0].source == "a"
    assert len(outcomes) == 2


def test_run_truncation_is_applied_after_interleave(monkeypatch):
    """죽여야 할 변이: 절단을 인터리브 **전에** 하기 (= 첫 소스만 쓰기)."""
    monkeypatch.setattr(
        search,
        "_query_one",
        _stub_query_one(
            {
                "a": [search.Candidate(f"https://a.invalid/{i}", None, "a") for i in range(5)],
                "b": [search.Candidate(f"https://b.invalid/{i}", None, "b") for i in range(5)],
            }
        ),
    )
    candidates, _ = search.run("q", [_decl("a"), _decl("b")], max_results=4)
    assert [c.source for c in candidates] == ["a", "b", "a", "b"]


def test_run_drops_private_band_candidates(monkeypatch, capsys):
    """죽여야 할 변이: 소스가 준 주소를 그대로 후보로 내놓기 (NG-11).

    후보 목록은 `--urls-only` 로 그대로 나가고 사람과 도구는 그것을 "열 수 있는
    주소"로 읽는다. 검색 소스가 돌려준 것이라는 사실은 안전을 보증하지 않으므로,
    취득 시점의 가드에만 기대지 않고 내놓기 전에 거른다. 조용히 지우지도 않는다.
    """
    monkeypatch.setattr(
        search,
        "_query_one",
        _stub_query_one(
            {
                "a": [
                    search.Candidate("http://169.254.169.254/latest/meta-data/", None, "a"),
                    search.Candidate("https://a.invalid/1", None, "a"),
                ],
            }
        ),
    )
    candidates, _ = search.run("q", [_decl("a")], max_results=5)
    assert [c.url for c in candidates] == ["https://a.invalid/1"]
    assert "169.254.169.254" in capsys.readouterr().err, "제외 사실이 보여야 한다 (NG-10)"


def test_unresolvable_candidate_is_not_dropped(monkeypatch):
    """이름이 안 풀리는 것은 사설 대역을 가리키는 것과 다르다.

    못 푸는 주소는 취득 시점에 어차피 fail-closed 로 실패한다. 후보에서 지우면
    일시적 DNS 실패가 조용히 결과를 깎는다.
    """
    monkeypatch.setattr(
        search,
        "_query_one",
        _stub_query_one({"a": [search.Candidate("https://nope.invalid/1", None, "a")]}),
    )
    candidates, _ = search.run("q", [_decl("a")], max_results=5)
    assert [c.url for c in candidates] == ["https://nope.invalid/1"]


def test_run_requires_sources():
    with pytest.raises(search.SearchError):
        search.run("q", [])


def test_select_sources_rejects_unknown_names(tmp_path):
    """죽여야 할 변이: 모르는 이름을 조용히 무시하기 — 오타 하나로 팬아웃이 준다."""
    index = _load(tmp_path, "s.yaml", _JSON_SOURCE)
    assert [d["name"] for d in search.select_sources(index, None)] == ["alpha"]
    assert [d["name"] for d in search.select_sources(index, "alpha,alpha")] == ["alpha"]
    with pytest.raises(search.SearchError) as exc:
        search.select_sources(index, "alpah")
    assert "alpah" in str(exc.value)


def test_select_sources_errors_when_none_declared(tmp_path):
    index = _load(tmp_path, "empty.yaml", "entries: []\n")
    with pytest.raises(search.SearchError):
        search.select_sources(index, None)


# ── ⑦ 인덱스 선언 검증 ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "body, hint",
    [
        # 이름 규약 — `--sources` 파싱과 같은 문법이어야 한다
        ('  - name: Alpha\n    host: a.invalid\n    kind: json\n'
         '    query_template: "https://a.invalid/s?q={query}"\n    result_pointer: items\n',
         "name"),
        # 선언 host 와 템플릿 netloc 불일치 — 고른 곳과 두드리는 곳이 갈린다
        ('  - name: alpha\n    host: a.invalid\n    kind: json\n'
         '    query_template: "https://b.invalid/s?q={query}"\n    result_pointer: items\n',
         "호스트"),
        # kind 에 안 맞는 키 — 조용한 무동작 방지
        ('  - name: alpha\n    host: a.invalid\n    kind: json\n'
         '    query_template: "https://a.invalid/s?q={query}"\n    result_pointer: items\n'
         '    link_transform: percent\n',
         "쓰이지 않는 키"),
        # 치환자는 {query} 하나뿐
        ('  - name: alpha\n    host: a.invalid\n    kind: json\n'
         '    query_template: "https://a.invalid/s?q={query}&u={user}"\n    result_pointer: items\n',
         "query"),
        # 치환자가 값 위치 밖 (파라미터 이름) — R5 규칙 상속
        ('  - name: alpha\n    host: a.invalid\n    kind: json\n'
         '    query_template: "https://a.invalid/s?{query}=1"\n    result_pointer: items\n',
         ""),
        # HTML 소스의 캡처 그룹은 정확히 1개
        ('  - name: alpha\n    host: a.invalid\n    kind: html\n'
         '    query_template: "https://a.invalid/s?q={query}"\n'
         "    result_link_pattern: '(a)(b)'\n",
         "캡처 그룹"),
        # 포인터는 점 표기 — 슬래시(JSON Pointer)를 쓰면 조용히 못 찾는다
        ('  - name: alpha\n    host: a.invalid\n    kind: json\n'
         '    query_template: "https://a.invalid/s?q={query}"\n    result_pointer: "/items"\n',
         "점 표기"),
        # exclude_hosts 는 스킴·경로 없는 호스트명 목록
        ('  - name: alpha\n    host: a.invalid\n    kind: json\n'
         '    query_template: "https://a.invalid/s?q={query}"\n    result_pointer: items\n'
         "    exclude_hosts:\n      - \"https://x.invalid/\"\n",
         "호스트명"),
    ],
)
def test_search_source_declaration_rejections(tmp_path, body, hint):
    with pytest.raises(api_index.IndexLoadError) as exc:
        _load(tmp_path, "bad.yaml", _yaml(body + _PROVENANCE))
    if hint:
        assert hint in str(exc.value)


def test_search_source_requires_provenance(tmp_path):
    """죽여야 할 변이: search_sources 에만 출처 의무를 면제하기 (AC-B-012-6)."""
    with pytest.raises(api_index.IndexLoadError):
        _load(
            tmp_path,
            "noprov.yaml",
            _yaml(
                '  - name: alpha\n    host: a.invalid\n    kind: json\n'
                '    query_template: "https://a.invalid/s?q={query}"\n'
                "    result_pointer: items\n"
            ),
        )


def test_duplicate_source_names_rejected(tmp_path):
    body = (
        '  - name: alpha\n    host: a.invalid\n    kind: json\n'
        '    query_template: "https://a.invalid/s?q={query}"\n    result_pointer: items\n'
        + _PROVENANCE
    )
    with pytest.raises(api_index.IndexLoadError):
        _load(tmp_path, "dup.yaml", _yaml(body + body))


def test_combined_cap_counts_search_sources(tmp_path):
    """죽여야 할 변이: 합산 상한에서 search_sources 를 빼기.

    상한은 "이 도구가 아는 문의 개수" 라 섹션별로 따로 세면 의미가 없다.
    """
    one = (
        '  - name: s{n}\n    host: a.invalid\n    kind: json\n'
        '    query_template: "https://a.invalid/s?q={{query}}"\n    result_pointer: items\n'
        + _PROVENANCE
    )
    body = "".join(one.format(n=i) for i in range(api_index.MAX_ENTRIES + 1))
    with pytest.raises(api_index.IndexLoadError) as exc:
        _load(tmp_path, "cap.yaml", _yaml(body))
    assert str(api_index.MAX_ENTRIES) in str(exc.value)


def test_exclude_hosts_cap(tmp_path):
    hosts = "".join(f"      - h{i}.invalid\n" for i in range(api_index.MAX_EXCLUDE_HOSTS + 1))
    with pytest.raises(api_index.IndexLoadError):
        _load(
            tmp_path,
            "ex.yaml",
            _yaml(
                '  - name: alpha\n    host: a.invalid\n    kind: json\n'
                '    query_template: "https://a.invalid/s?q={query}"\n    result_pointer: items\n'
                "    exclude_hosts:\n" + hosts + _PROVENANCE
            ),
        )


def test_shipped_index_search_sources_load():
    """배포되는 인덱스가 스키마를 실제로 통과하는지 — 선언만 고치고 검증을 못 도는
    상황을 막는다."""
    index = api_index.load_cached(None)
    names = [decl["name"] for decl in index.search_sources]
    assert "ddg" in names
    ddg = next(d for d in index.search_sources if d["name"] == "ddg")
    assert "duckduckgo.com" in ddg["exclude_hosts"]


# ── ⑧ CLI 배선 ───────────────────────────────────────────────────────────


def test_cli_urls_only_performs_zero_fetches(monkeypatch, capsys):
    """죽여야 할 변이: `--urls-only` 에서도 취득을 돌리기.

    "후보만 보고 싶다" 는 요청에 상대 서버를 두드리면, 검색 계층을 훑어보는 것만으로
    호스트에 부하가 간다.
    """
    calls: list[str] = []
    monkeypatch.setattr(fetcher, "fetch", lambda req: calls.append(req.url))
    monkeypatch.setattr(
        search,
        "run",
        lambda *a, **k: (
            [search.Candidate("https://x.invalid/1", None, "a")],
            [search.SourceOutcome("a", "https://e/", True, 200, 1, 1)],
        ),
    )
    code = engine.main(["search", "q", "--urls-only"])
    assert code == engine.EXIT_OK
    assert calls == []
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1  # 요약 한 줄뿐 — FetchResult 줄이 없다
    assert "https://x.invalid/1" in out[0]


def test_cli_empty_candidates_is_failure(monkeypatch, capsys):
    """죽여야 할 변이: 빈 결과를 성공(0)으로 내기 — "찾았는데 없었다" 와
    "찾지 못했다" 가 같아진다 (NG-10)."""
    monkeypatch.setattr(search, "run", lambda *a, **k: ([], []))
    code = engine.main(["search", "q", "--urls-only"])
    assert code == engine.EXIT_FAILED
    assert "후보 URL 이 없다" in capsys.readouterr().err


def test_cli_rejects_bad_max_results(capsys):
    code = engine.main(["search", "q", "--max-results", "0"])
    assert code == engine.EXIT_USAGE


def test_cli_rejects_unknown_source(capsys):
    code = engine.main(["search", "q", "--sources", "nope-not-declared"])
    assert code == engine.EXIT_USAGE


# ── ⑨ 재귀 부재 (NG-5 개정판의 유일한 방벽) ──────────────────────────────


def test_search_module_cannot_reach_fetched_bodies():
    """죽여야 할 변이: 취득 본문에서 링크를 뽑아 후보에 다시 넣기.

    문서로 "안 한다" 고 적는 것과 **할 수 없게** 만드는 것은 다르다. 후보를 만드는
    모듈이 `fetcher`·`batch`·`extract`·`alternates` 를 임포트하지 않으면 그 행위는
    이 모듈 안에서 표현될 수 없다. 임포트가 생기는 순간 여기가 빨개진다.

    문자열 검색이 아니라 AST 로 본다 — 주석·독스트링에 모듈 이름이 나오는 것은
    금지할 일이 아니고(지금 이 설명이 그렇다), 겨누는 것은 실제 임포트다.
    """
    tree = ast.parse(pathlib.Path(search.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    dynamic: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.update(node.module.split("."))
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Name) and node.id in ("__import__",):
            dynamic.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr == "import_module":
            dynamic.append(node.attr)

    for forbidden in ("fetcher", "batch", "extract", "alternates"):
        assert forbidden not in imported, f"search.py 가 {forbidden} 을 임포트한다"
    # 동적 임포트로 우회하면 위 검사가 무력해진다
    assert dynamic == []
