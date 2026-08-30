"""durable M06 本地状态目录的单实例租约。"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import BinaryIO


class StateDirectoryInUse(RuntimeError):
    """同一 durable 状态目录已被当前或另一进程占用。"""


_PROCESS_LOCK = threading.Lock()
_PROCESS_PATHS: set[Path] = set()


class StateDirectoryLease:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir.resolve()
        self._handle: BinaryIO | None = None

    def acquire(self) -> None:
        if self._handle is not None:
            return
        with _PROCESS_LOCK:
            if self.state_dir in _PROCESS_PATHS:
                raise StateDirectoryInUse("durable_state_directory_in_use")
            self.state_dir.mkdir(parents=True, exist_ok=True)
            handle = (self.state_dir / "venagent-state.lock").open("a+b")
            try:
                _lock_handle(handle)
            except OSError as exc:
                handle.close()
                raise StateDirectoryInUse(
                    "durable_state_directory_in_use"
                ) from exc
            self._handle = handle
            _PROCESS_PATHS.add(self.state_dir)

    def release(self) -> None:
        with _PROCESS_LOCK:
            handle = self._handle
            if handle is None:
                return
            self._handle = None
            try:
                _unlock_handle(handle)
            finally:
                handle.close()
                _PROCESS_PATHS.discard(self.state_dir)


def _lock_handle(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        if handle.read(1) == b"":
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_handle(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
