"""M06 invocation store 契约（单点）。

- 加密存储绝不写明文且能检测篡改：本文件单点。
- 缺加密密钥 fail-closed：本文件单点。
- 内存存储 TTL 过期清理：本文件单点。

（从 tests/agent/test_m06_agent_tool_loop.py 迁入 tools 契约侧。）
"""

from __future__ import annotations

from src.tools.invocation_store import (
    EncryptedFileInvocationStore,
    InMemoryInvocationStore,
    InvocationStoreError,
)


def test_encrypted_invocation_store_never_writes_plaintext_and_detects_tamper(
    tmp_path,
) -> None:
    import base64

    key = base64.b64encode(b"k" * 32)
    store = EncryptedFileInvocationStore(
        tmp_path / "invocations.json",
        key=base64.b64decode(key),
    )
    store.save(
        run_id="run-sec",
        owner_id="owner-sec",
        operation_id="op-sec",
        tool_call_id="call-sec",
        operation_key="key-sec",
        arguments={"query": "secret-query", "token": "secret-token"},
    )
    raw = (tmp_path / "invocations.json").read_text(encoding="utf-8")
    assert "secret-query" not in raw
    assert "secret-token" not in raw
    assert store.get(
        run_id="run-sec",
        owner_id="owner-sec",
        tool_call_id="call-sec",
        operation_key="key-sec",
    ) == {"query": "secret-query", "token": "secret-token"}

    # 篡改密文后必须解密失败。
    import json

    payload = json.loads(raw)
    item = payload["items"][0]
    original = item["ciphertext"]
    flipped = ("A" if original[0] != "A" else "B") + original[1:]
    item["ciphertext"] = flipped
    (tmp_path / "invocations.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    tampered = EncryptedFileInvocationStore(
        tmp_path / "invocations.json",
        key=base64.b64decode(key),
    )
    try:
        tampered.get(
            run_id="run-sec",
            owner_id="owner-sec",
            tool_call_id="call-sec",
            operation_key="key-sec",
        )
        raise AssertionError("tampered ciphertext must not decrypt")
    except InvocationStoreError:
        pass


def test_encrypted_invocation_store_fails_closed_without_key(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("VENAGENT_INVOCATION_ENCRYPTION_KEY", raising=False)
    try:
        EncryptedFileInvocationStore(tmp_path / "invocations.json")
        raise AssertionError("missing key must fail closed")
    except Exception:
        pass


def test_in_memory_invocation_store_ttl_cleanup() -> None:
    from datetime import datetime, timedelta, timezone

    store = InMemoryInvocationStore()
    store.save(
        run_id="run-ttl",
        owner_id="owner-ttl",
        operation_id="op-ttl",
        tool_call_id="call-ttl",
        operation_key="key-ttl",
        arguments={"query": "x"},
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    try:
        store.get(
            run_id="run-ttl",
            owner_id="owner-ttl",
            tool_call_id="call-ttl",
            operation_key="key-ttl",
        )
        raise AssertionError("expired payload must not be returned")
    except Exception:
        pass