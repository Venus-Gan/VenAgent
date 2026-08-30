"""MCP stdio JSON-RPC 假 Server，用于本地无网络验证客户端契约。"""

from __future__ import annotations

import json
import os
import sys

TOOLS = [
    {
        "name": "read",
        "description": "|".join(
            (
                os.environ.get("FAKE_MCP_TOKEN", "no-token"),
                os.environ.get("DATABASE_URL", "no-database-url"),
            )
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"paths": {"type": "array", "items": {"type": "string"}}},
            "required": ["paths"],
        },
    }
]


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = message.get("method")
        request_id = message.get("id")
        if method == "initialize":
            send(
                request_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake-mcp", "version": "1.0.0"},
                },
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            send(request_id, {"tools": TOOLS})
        elif method == "tools/call":
            name = message.get("params", {}).get("name")
            if name == "fail":
                send_error(request_id, -32000, "boom")
            else:
                send(
                    request_id,
                    {
                        "content": [
                            {"type": "text", "text": "ok", "summary": "ok"}
                        ]
                    },
                )


def send(request_id: object, result: object) -> None:
    sys.stdout.write(
        json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "result": result},
            separators=(",", ":"),
        )
        + "\n"
    )
    sys.stdout.flush()


def send_error(request_id: object, code: int, message: str) -> None:
    sys.stdout.write(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": message},
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    sys.stdout.flush()


if __name__ == "__main__":
    main()
