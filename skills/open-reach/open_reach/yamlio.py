"""제한된 YAML 서브셋 로더/에미터.

`profiles.yaml` 과 `battery.yaml` 은 우리가 스키마를 통제하는 파일이고,
SPEC 이식성 절이 "신규 런타임 의존성은 curl_cffi 하나"로 못박혀 있다.
그래서 PyYAML 을 끌어오는 대신 실제로 쓰는 문법만 정확히 지원한다.

지원: 중첩 매핑, 매핑의 시퀀스, 스칼라(null/bool/int/float/문자열), 전행 주석,
그리고 **빈** 컨테이너의 흐름 표기(`[]`/`{}`) — 블록 표기로는 쓸 수 없기 때문이다.
미지원: 앵커, 태그, 내용이 있는 흐름 스타일, 블록 스칼라(`|`/`>`), 다중 문서.
미지원 문법을 만나면 조용히 넘기지 않고 YamlError 를 던진다.
"""

from __future__ import annotations

from typing import Any

_UNSUPPORTED = ("&", "*", "!", "|", ">", "{", "[")


class YamlError(ValueError):
    """제한 서브셋을 벗어난 YAML 입력."""


# ── 로드 ─────────────────────────────────────────────────────────────────


def _tokenize(text: str) -> list[list[Any]]:
    lines: list[list[Any]] = []
    for lineno, raw in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        if not raw.strip():
            continue
        stripped = raw.lstrip(" ")
        if stripped.startswith("#"):
            continue
        if raw.startswith("\t") or "\t" in raw[: len(raw) - len(stripped)]:
            raise YamlError(f"line {lineno}: 들여쓰기에 탭을 쓸 수 없다")
        if stripped in ("---", "..."):
            raise YamlError(f"line {lineno}: 다중 문서는 지원하지 않는다")
        lines.append([len(raw) - len(stripped), stripped, lineno])
    return lines


_UNESCAPE_MAP = {"\\": "\\", '"': '"', "'": "'", "n": "\n", "t": "\t", "r": "\r", "0": "\0"}


def _unescape(text: str) -> str:
    """큰따옴표 스칼라의 역이스케이프 — 에미터가 쓰는 집합과 정확히 대칭이다."""
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            nxt = text[index + 1]
            out.append(_UNESCAPE_MAP.get(nxt, "\\" + nxt))
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _scalar(token: str, lineno: int) -> Any:
    token = token.strip()
    if token == "":
        return None
    if token == "[]":
        return []
    if token == "{}":
        return {}
    if token[0] in ("'", '"'):
        quote = token[0]
        if len(token) < 2 or token[-1] != quote:
            raise YamlError(f"line {lineno}: 닫히지 않은 인용부호")
        inner = token[1:-1]
        # 인용부호를 벗기기만 하고 이스케이프를 되돌리지 않으면 dumps→loads 가
        # 손실 없이 왕복하지 못한다 — refresh 가 지문표를 쓸 때마다 문자열이 상한다
        return _unescape(inner) if quote == '"' else inner.replace("''", "'")
    if token[0] in _UNSUPPORTED:
        raise YamlError(f"line {lineno}: 지원하지 않는 YAML 문법: {token[0]}")
    lowered = token.lower()
    if lowered in ("null", "~"):
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    return token


def _split_key(content: str, lineno: int) -> tuple[str, str]:
    """`key: value` 를 분리한다. 값 안의 `://` 는 콜론+공백 규칙으로 보호된다."""
    idx = content.find(": ")
    if idx >= 0:
        return content[:idx].strip(), content[idx + 2 :].strip()
    if content.endswith(":"):
        return content[:-1].strip(), ""
    raise YamlError(f"line {lineno}: `key: value` 형태가 아니다 -> {content!r}")


class _Parser:
    def __init__(self, lines: list[list[Any]]) -> None:
        self.lines = lines
        self.pos = 0

    def peek(self) -> list[Any] | None:
        return self.lines[self.pos] if self.pos < len(self.lines) else None

    def parse_block(self, indent: int) -> Any:
        line = self.peek()
        if line is None or line[0] != indent:
            return None
        if line[1].startswith("- ") or line[1] == "-":
            return self.parse_sequence(indent)
        return self.parse_mapping(indent)

    def parse_mapping(self, indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while True:
            line = self.peek()
            if line is None or line[0] != indent or line[1].startswith("- "):
                break
            _, content, lineno = line
            key, raw_value = _split_key(content, lineno)
            self.pos += 1
            if raw_value == "":
                nxt = self.peek()
                if nxt is not None and nxt[0] > indent:
                    result[key] = self.parse_block(nxt[0])
                else:
                    result[key] = None
            else:
                result[key] = _scalar(raw_value, lineno)
        return result

    def parse_sequence(self, indent: int) -> list[Any]:
        result: list[Any] = []
        while True:
            line = self.peek()
            if line is None or line[0] != indent or not line[1].startswith("- "):
                break
            _, content, lineno = line
            rest = content[2:].strip()
            if ": " in rest or rest.endswith(":"):
                # `- key: value` — 항목 자체가 매핑이다. 키 열을 indent+2 로 맞춘다.
                self.lines[self.pos] = [indent + 2, rest, lineno]
                result.append(self.parse_mapping(indent + 2))
            else:
                self.pos += 1
                result.append(_scalar(rest, lineno))
        return result


def loads(text: str) -> Any:
    lines = _tokenize(text)
    if not lines:
        return None
    parser = _Parser(lines)
    value = parser.parse_block(lines[0][0])
    if parser.pos != len(parser.lines):
        leftover = parser.lines[parser.pos]
        raise YamlError(f"line {leftover[2]}: 들여쓰기가 맞지 않는다 -> {leftover[1]!r}")
    return value


# ── 에미터 ───────────────────────────────────────────────────────────────

_NEEDS_QUOTE_EXACT = {"null", "true", "false", "yes", "no", "on", "off", "~", ""}


def _emit_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if (
        text.lower() in _NEEDS_QUOTE_EXACT
        or text != text.strip()
        or text[0] in ("'", '"', "-", "#", "&", "*", "!", "|", ">", "{", "[", "%", "@", "`")
        or ": " in text
        or text.endswith(":")
        or any(ch in text for ch in "\n\r\t")
    ):
        escaped = (
            text.replace("\\", "\\\\")
            .replace('"', '\\"')
            # 줄바꿈을 그대로 두면 한 줄짜리 스칼라가 여러 줄이 되어 파서가 깨진다
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return '"' + escaped + '"'
    return text


def _emit_key(key: Any) -> str:
    """키는 인용하지 않는다 — 인용이 필요한 키는 이 서브셋의 파서가 되읽지 못한다."""
    text = str(key)
    if text != _emit_scalar(text):
        raise YamlError(f"인용이 필요한 키는 지원하지 않는다: {text!r}")
    return text


def _dump_into(node: Any, indent: int, out: list[str]) -> None:
    pad = " " * indent
    if isinstance(node, dict):
        for raw_key, value in node.items():
            key = _emit_key(raw_key)
            if isinstance(value, dict) and value:
                out.append(f"{pad}{key}:")
                _dump_into(value, indent + 2, out)
            elif isinstance(value, list) and value:
                out.append(f"{pad}{key}:")
                _dump_into(value, indent + 2, out)
            elif isinstance(value, list):
                out.append(f"{pad}{key}: []")
            elif isinstance(value, dict):
                out.append(f"{pad}{key}: {{}}")
            else:
                out.append(f"{pad}{key}: {_emit_scalar(value)}")
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, dict):
                inner: list[str] = []
                _dump_into(item, indent + 2, inner)
                if not inner:
                    out.append(f"{pad}- null")
                    continue
                out.append(f"{pad}- {inner[0].strip()}")
                out.extend(inner[1:])
            else:
                out.append(f"{pad}- {_emit_scalar(item)}")
    else:
        out.append(f"{pad}{_emit_scalar(node)}")


def dumps(node: Any) -> str:
    out: list[str] = []
    _dump_into(node, 0, out)
    return "\n".join(out) + "\n"
