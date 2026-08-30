"""M06 私有调用载荷存储：内存实现与 AES-GCM 加密文件实现。

该存储不通过 SSE、Prompt、日志或 Artifact 下载接口暴露。
"""

from __future__ import annotations

import base64
import json
import os
import stat
import tempfile
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .errors import ToolError

_KEY_BYTES = 32
_NONCE_BYTES = 12


class InvocationPayloadNotFound(ToolError):
    code = "invocation_payload_not_found"


class InvocationStoreError(ToolError):
    code = "invocation_store_error"


def decode_invocation_key(value: str) -> bytes:
    """从配置字符串解码 32 字节密钥，失败时抛 InvocationStoreError。"""
    return _key_from_env(value)


def _key_from_env(value: str | None) -> bytes:
    if not value:
        raise InvocationStoreError("VENAGENT_INVOCATION_ENCRYPTION_KEY is not configured")
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise InvocationStoreError("VENAGENT_INVOCATION_ENCRYPTION_KEY is not valid base64") from exc
    if len(raw) != _KEY_BYTES:
        raise InvocationStoreError("VENAGENT_INVOCATION_ENCRYPTION_KEY must decode to 32 bytes")
    return raw


def _aad(
    run_id: str,
    owner_id: str,
    tool_call_id: str,
    operation_key: str,
) -> bytes:
    return f"{run_id}\x00{owner_id}\x00{tool_call_id}\x00{operation_key}".encode("utf-8")


class InvocationStore(ABC):
    @abstractmethod
    def save(
        self,
        *,
        run_id: str,
        owner_id: str,
        operation_id: str,
        tool_call_id: str,
        operation_key: str,
        arguments: dict[str, Any],
        expires_at: datetime | None = None,
    ) -> None: ...

    @abstractmethod
    def get(
        self,
        *,
        run_id: str,
        owner_id: str,
        tool_call_id: str,
        operation_key: str,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def delete(
        self,
        *,
        run_id: str,
        owner_id: str,
        tool_call_id: str,
        operation_key: str,
    ) -> None: ...

    @abstractmethod
    def delete_run(self, run_id: str) -> None: ...

    @abstractmethod
    def operation_id(
        self,
        *,
        run_id: str,
        owner_id: str,
        tool_call_id: str,
        operation_key: str,
    ) -> str | None: ...


@dataclass
class InMemoryInvocationStore(InvocationStore):
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _items: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    _owners: dict[tuple[str, str, str], str] = field(default_factory=dict)
    _operations: dict[tuple[str, str, str], str] = field(default_factory=dict)
    _expires: dict[tuple[str, str, str], datetime] = field(default_factory=dict)

    def save(
        self,
        *,
        run_id: str,
        owner_id: str,
        operation_id: str,
        tool_call_id: str,
        operation_key: str,
        arguments: dict[str, Any],
        expires_at: datetime | None = None,
    ) -> None:
        key = (run_id, tool_call_id, operation_key)
        with self._lock:
            self._items[key] = dict(arguments)
            self._owners[key] = owner_id
            self._operations[key] = operation_id
            self._expires[key] = expires_at

    def get(
        self,
        *,
        run_id: str,
        owner_id: str,
        tool_call_id: str,
        operation_key: str,
    ) -> dict[str, Any]:
        key = (run_id, tool_call_id, operation_key)
        with self._lock:
            if key not in self._items or self._owners.get(key) != owner_id:
                raise InvocationPayloadNotFound
            expires = self._expires.get(key)
            if expires is not None and expires <= datetime.now(timezone.utc):
                self._delete_locked(key)
                raise InvocationPayloadNotFound
            return dict(self._items[key])

    def delete(
        self,
        *,
        run_id: str,
        owner_id: str,
        tool_call_id: str,
        operation_key: str,
    ) -> None:
        key = (run_id, tool_call_id, operation_key)
        with self._lock:
            if self._owners.get(key) == owner_id:
                self._delete_locked(key)

    def delete_run(self, run_id: str) -> None:
        with self._lock:
            for key in [key for key in self._items if key[0] == run_id]:
                self._delete_locked(key)

    def operation_id(
        self,
        *,
        run_id: str,
        owner_id: str,
        tool_call_id: str,
        operation_key: str,
    ) -> str | None:
        key = (run_id, tool_call_id, operation_key)
        with self._lock:
            if key not in self._items or self._owners.get(key) != owner_id:
                return None
            return self._operations.get(key)

    def _delete_locked(self, key: tuple[str, str, str]) -> None:
        self._items.pop(key, None)
        self._owners.pop(key, None)
        self._operations.pop(key, None)
        self._expires.pop(key, None)


class EncryptedFileInvocationStore(InvocationStore):
    def __init__(
        self,
        path: Path,
        *,
        key: bytes | None = None,
        key_version: int = 1,
        ttl: timedelta = timedelta(days=7),
    ) -> None:
        self._path = path
        self._key = key if key is not None else _key_from_env(
            os.environ.get("VENAGENT_INVOCATION_ENCRYPTION_KEY")
        )
        self._key_version = key_version
        self._ttl = ttl
        self._lock = threading.Lock()
        self._items: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._load_locked()

    def save(
        self,
        *,
        run_id: str,
        owner_id: str,
        operation_id: str,
        tool_call_id: str,
        operation_key: str,
        arguments: dict[str, Any],
        expires_at: datetime | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        key = (run_id, tool_call_id, operation_key)
        payload = json.dumps(arguments, ensure_ascii=False, sort_keys=True).encode("utf-8")
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = AESGCM(self._key).encrypt(
            nonce,
            payload,
            _aad(run_id, owner_id, tool_call_id, operation_key),
        )
        with self._lock:
            self._items[key] = {
                "run_id": run_id,
                "owner_id": owner_id,
                "operation_id": operation_id,
                "tool_call_id": tool_call_id,
                "operation_key": operation_key,
                "key_version": self._key_version,
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
                "created_at": now.isoformat(),
                "expires_at": (expires_at or now + self._ttl).isoformat(),
            }
            self._persist_locked()

    def get(
        self,
        *,
        run_id: str,
        owner_id: str,
        tool_call_id: str,
        operation_key: str,
    ) -> dict[str, Any]:
        key = (run_id, tool_call_id, operation_key)
        with self._lock:
            item = self._items.get(key)
            if item is None or item["owner_id"] != owner_id:
                raise InvocationPayloadNotFound
            expires = datetime.fromisoformat(item["expires_at"])
            if expires <= datetime.now(timezone.utc):
                self._items.pop(key, None)
                self._persist_locked()
                raise InvocationPayloadNotFound
            return self._decrypt_locked(item)

    def delete(
        self,
        *,
        run_id: str,
        owner_id: str,
        tool_call_id: str,
        operation_key: str,
    ) -> None:
        key = (run_id, tool_call_id, operation_key)
        with self._lock:
            item = self._items.get(key)
            if item is not None and item["owner_id"] == owner_id:
                self._items.pop(key, None)
                self._persist_locked()

    def delete_run(self, run_id: str) -> None:
        with self._lock:
            changed = False
            for key in [key for key in self._items if key[0] == run_id]:
                self._items.pop(key, None)
                changed = True
            if changed:
                self._persist_locked()

    def operation_id(
        self,
        *,
        run_id: str,
        owner_id: str,
        tool_call_id: str,
        operation_key: str,
    ) -> str | None:
        key = (run_id, tool_call_id, operation_key)
        with self._lock:
            item = self._items.get(key)
            if item is None or item["owner_id"] != owner_id:
                return None
            return item.get("operation_id")

    def _decrypt_locked(self, item: dict[str, Any]) -> dict[str, Any]:
        if int(item["key_version"]) != self._key_version:
            raise InvocationStoreError("invocation key_version mismatch")
        try:
            nonce = base64.b64decode(item["nonce"])
            ciphertext = base64.b64decode(item["ciphertext"])
            plaintext = AESGCM(self._key).decrypt(
                nonce,
                ciphertext,
                _aad(
                    item["run_id"],
                    item["owner_id"],
                    item["tool_call_id"],
                    item["operation_key"],
                ),
            )
        except Exception as exc:
            raise InvocationStoreError("invocation payload decryption failed") from exc
        return json.loads(plaintext.decode("utf-8"))

    def _load_locked(self) -> None:
        if not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise InvocationStoreError("invocation store file is corrupt") from exc
        for item in raw.get("items", ()):
            key = (item["run_id"], item["tool_call_id"], item["operation_key"])
            self._items[key] = item

    def _persist_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "key_version": self._key_version,
            "items": list(self._items.values()),
        }
        fd, temp_name = tempfile.mkstemp(
            prefix=f"{self._path.name}-", suffix=".tmp", dir=self._path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            if os.name == "posix":
                os.chmod(temp_name, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(temp_name, self._path)
        finally:
            if os.path.exists(temp_name):
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
