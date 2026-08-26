"""상태 파일 — 관측 로그와 벤치 이력.

append 는 배타 생성 락 파일을 잡고 `O_APPEND` 단일 write 로 수행한다.
관측에는 허용 필드 8개만 들어가고 본문·쿠키·헤더는 어떤 필드로도 들어가지 않는다
(NG-4, NG-12).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from .models import Observation, utc_now

OBSERVATIONS_MAX_BYTES = 50 * 1024 * 1024
_LOCK_ACQUIRE_TIMEOUT_S = 10.0
# 락 보유 구간은 write 1회(밀리초)다. 이보다 훨씬 긴 나이의 락만 죽은 것으로 본다.
_LOCK_STALE_S = 30.0
_TAIL_SCAN_BYTES = 512 * 1024


def repo_root() -> Path:
    # <root>/skills/open-reach/open_reach/observe.py -> parents[3] == <root>
    return Path(__file__).resolve().parents[3]


def state_dir() -> Path:
    raw = os.environ.get("OPENREACH_STATE_DIR", "").strip()
    return Path(raw).expanduser().resolve() if raw else repo_root()


def profiles_path() -> Path:
    raw = os.environ.get("OPENREACH_PROFILES", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return repo_root() / "skills" / "open-reach" / "engine" / "profiles.yaml"


def observations_path() -> Path:
    return state_dir() / "observations.jsonl"


def bench_history_path() -> Path:
    return state_dir() / "bench" / "history.jsonl"


class _FileLock:
    """배타 생성 락 — 같은 파일에 두 프로세스가 동시에 append 하지 않게 한다."""

    def __init__(self, target: Path) -> None:
        self.lock_path = target.with_suffix(target.suffix + ".lock")

    def _is_stale(self) -> bool:
        """락 파일의 나이로만 판단한다. 대기 시간이 길다는 이유로 남의 락을 뺏으면
        두 프로세스가 동시에 append 하게 되고, 그게 바로 이 락이 막으려던 상황이다."""
        try:
            age = time.time() - self.lock_path.stat().st_mtime
        except OSError:
            return False
        return age > _LOCK_STALE_S

    def __enter__(self) -> "_FileLock":
        deadline = time.monotonic() + _LOCK_ACQUIRE_TIMEOUT_S
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except FileExistsError:
                if self._is_stale():
                    # 죽은 프로세스의 잔해만 회수한다
                    try:
                        self.lock_path.unlink()
                    except OSError:
                        pass
                    continue
                if time.monotonic() > deadline:
                    raise TimeoutError(f"락 획득 실패: {self.lock_path}")
                time.sleep(0.02)

    def __exit__(self, *exc_info: object) -> None:
        try:
            self.lock_path.unlink()
        except OSError:
            pass


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    with _FileLock(path):
        _rotate_if_needed(path)
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o644)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)


def _rotate_if_needed(path: Path) -> None:
    try:
        if path.stat().st_size < OBSERVATIONS_MAX_BYTES:
            return
    except FileNotFoundError:
        return
    rotated = path.with_name(path.stem + ".1" + path.suffix)
    try:
        if rotated.exists():
            rotated.unlink()
        path.rename(rotated)
    except OSError:
        pass


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def normalize_url(url: str) -> tuple[str, str]:
    """(host, path) 로 정규화한다 — query·fragment·userinfo 는 버린다 (AC-B-006-2)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path or "/"
    return host, path


def record_success(
    url: str, *, waf_vendor: str, route: str, impersonate: str | None, url_variant: str
) -> None:
    """성공한 시도 1건만 기록한다. 경계·실패 경로는 학습하지 않는다 (AC-B-006-5)."""
    host, path = normalize_url(url)
    observation = Observation(
        ts=utc_now(),
        host=host,
        path=path,
        waf_vendor=waf_vendor,
        route=route,
        impersonate=impersonate,
        url_variant=url_variant,
    )
    append_jsonl(observations_path(), observation.to_record())


def _iter_tail_records(path: Path, *, scan_bytes: int = _TAIL_SCAN_BYTES):
    """파일 끝에서부터 최근 레코드를 하나씩 내놓는다.

    최근 성공 1건을 찾자고 매 fetch 마다 최대 50MB 를 통째로 읽어 들이면,
    관측이 쌓일수록 취득이 느려진다 — 학습이 성능을 갉아먹는 구조가 된다.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return
    with open(path, "rb") as handle:
        start = max(0, size - scan_bytes)
        handle.seek(start)
        chunk = handle.read(size - start)
    if start > 0:
        # 첫 줄은 잘렸을 수 있다 — 버린다
        newline = chunk.find(b"\n")
        chunk = chunk[newline + 1 :] if newline >= 0 else b""
    for line in reversed(chunk.split(b"\n")):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(record, dict):
            yield record


def iter_recent(path: Path):
    """최근 레코드부터 훑는다 (파일 끝에서부터). 전체 적재를 하지 않는다."""
    return _iter_tail_records(path)


def last_success_for(url: str) -> dict | None:
    """같은 host+path 의 가장 최근 성공 경로 (AC-B-006-4)."""
    host, path = normalize_url(url)
    for record in _iter_tail_records(observations_path()):
        if record.get("host") == host and record.get("path") == path:
            return record
    return None


def atomic_write(path: Path, text: str) -> None:
    """임시 파일 + rename. 실패해도 원본이 반쯤 쓰인 상태로 남지 않는다."""
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="or-swap-", suffix=".part", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
