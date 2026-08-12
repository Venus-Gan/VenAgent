# Outcome

将 FastAPI/Starlette TestClient 的开发测试依赖从已弃用的 `httpx` 兼容路径迁移到 `httpx2`，消除当前全量测试中的 `StarletteDeprecationWarning`。

# Scope

- 更新根目录 `pyproject.toml` 的 `dev` 可选依赖。
- 在项目虚拟环境中重新安装开发依赖。
- 运行 API 相关测试与根目录全量测试，确认 TestClient 和 M02 流式契约保持正常。

# Non-goals

- 不修改生产运行时依赖、HTTP/SSE 接口、Agent Loop 或浏览器 UI 行为。
- 不修改已归档的 M02 change 或 canonical streaming spec。
- 不处理与本测试依赖迁移无关的现有工作区改动。

# Acceptance examples

- 安装开发依赖后，`fastapi.testclient.TestClient` 使用 Starlette 首选的 `httpx2` 路径，API 测试通过。
- 根目录全量测试全部通过，测试输出不再包含 `StarletteDeprecationWarning` 或 `Using httpx with starlette.testclient is deprecated`。

# Constraints and invariants

- 只调整测试开发依赖，不改变应用生产行为。
- 保留现有 FastAPI、Starlette 和其他项目依赖约束，除非安装解析证明迁移必须调整。
- 不回退或覆盖用户已有的无关工作区改动。

# Decisions

- 使用 Starlette 1.3.1 明确推荐的 `httpx2>=2.0,<3.0` 替换 `httpx>=0.27,<1.0`。
- 先运行 API/streaming 相关测试，再运行全部 87 项测试。
- 用户在了解范围、风险与完整验证耗时后明确授权执行该迁移。

# Open questions

- 无。

# Verification expectations

- 重新安装 `.[dev]` 成功且依赖解析无冲突。
- `tests/test_api.py` 与 `tests/test_streaming_api.py` 通过。
- `python -m pytest -q -W default` 全量通过且无上述弃用警告。
