"""Per-library locking and atomic file writes for pipeline stages."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout


# Lock timeout is hard-coded to infinite wait.
# Do not read from environment to avoid accidental 300s timeout regressions.
_LOCK_TIMEOUT: float = -1.0


class LibraryLock:
    """File-based lock serializing pipeline access to one library workspace.

    Usage as context manager::

        with LibraryLock(workspace_path):
            ... critical section ...

    Only one thread/process per workspace can hold the lock at a time.
    On crash the OS releases the underlying file handle so stale locks
    are automatically cleaned up.
    """

    def __init__(self, workspace_path: str | Path, timeout: float = _LOCK_TIMEOUT) -> None:
        ws = Path(str(workspace_path or "").strip()).resolve()
        ws.mkdir(parents=True, exist_ok=True)
        self._lock_path = ws / ".pipeline.lock"
        self._lock = FileLock(str(self._lock_path), timeout=timeout)
        self._held = False

    def acquire(self) -> None:
        try:
            self._lock.acquire()
            self._held = True
        except Timeout:
            raise Timeout(
                f"library_locked:{self._lock_path}:timeout={self._lock.timeout}s"
            ) from None

    def release(self) -> None:
        if self._held:
            self._lock.release()
            self._held = False

    def __enter__(self) -> LibraryLock:
        self.acquire()
        return self

    def __exit__(self, *args: Any) -> None:
        self.release()


def file_write_lock(path: str | Path) -> FileLock:
    """Return a :class:`FileLock` for a single-file RMW operation.

    Usage::

        with file_write_lock("/path/to/file.json"):
            ... read-modify-write ...
    """
    p = Path(str(path or "").strip())
    lock_path = Path(str(p) + ".lock")
    return FileLock(str(lock_path), timeout=_LOCK_TIMEOUT)


def atomic_write_json(path: str | Path, payload: Any, *, indent: int = 2) -> None:
    """Atomically write *payload* as JSON to *path* (temp-file + rename)."""
    target = Path(str(path or "").strip())
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=indent, default=str)
    _atomic_write(target, text)


def atomic_write_text(path: str | Path, text: str) -> None:
    """Atomically write *text* to *path* (temp-file + rename)."""
    target = Path(str(path or "").strip())
    target.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(target, text)


def _atomic_write(target: Path, content: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix="." + target.name + ".")
    try:
        os.write(fd, content.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, str(target))
