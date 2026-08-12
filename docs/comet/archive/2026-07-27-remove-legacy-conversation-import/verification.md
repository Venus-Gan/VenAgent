# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-24c7ccc822687e58ff4785d1db5c34cc960bd355c92de2c7e4ae9fecbe6747b0",
    "evidence_refs": [
      "web/src/modules/chat/store.ts",
      "web/tests/e2e/workspace.spec.ts"
    ]
  },
  {
    "acceptance_id": "acceptance-6c37bc66e67942c017cb6c256356c1e3d5c76df4efb372a35f7cc5ebf436cf31",
    "evidence_refs": [
      "web/src/modules/chat/ChatWorkspace.vue",
      "web/src/modules/chat/store.ts",
      "web/tests/e2e/workspace.spec.ts"
    ]
  },
  {
    "acceptance_id": "acceptance-7a3d303e32620747d9f08bc9c96b91782dcfc89733cb4aac4ef46856f0fd8c14",
    "evidence_refs": [
      "tests/test_persistence.py",
      "venagent/interfaces/http/routes.py"
    ]
  },
  {
    "acceptance_id": "acceptance-8fe67102f070d7e50155eb2178a1d15a0c248164be2121c25d43d724919afa19",
    "evidence_refs": [
      "web/src/modules/chat/ChatWorkspace.vue",
      "web/src/style.css",
      "web/tests/e2e/workspace.spec.ts"
    ]
  },
  {
    "acceptance_id": "acceptance-a159a4b04d303fe3725e0b99e71680565860aa20469d9d1f77d80e08996f3c8a",
    "evidence_refs": [
      "tests/test_persistence.py",
      "venagent/bootstrap.py",
      "venagent/infra/platform/runtime.py"
    ]
  },
  {
    "acceptance_id": "acceptance-c0bbf97abf39d57a3e11503176413fcad846a199b0569256ad564dadc21298b5",
    "evidence_refs": [
      "tests/test_persistence.py",
      "venagent/infra/platform/migrations.py",
      "venagent/infra/platform/postgres.py"
    ]
  },
  {
    "acceptance_id": "acceptance-c33c15045e7a50cd40fbba9597d2b48a04723ed6935fdbf7deb481b0f3ae2845",
    "evidence_refs": [
      "web/src/modules/chat/store.ts",
      "web/tests/e2e/workspace.spec.ts"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `.\.venv\Scripts\python.exe -m pytest -q`：111 passed，1 skipped；跳过项是需要显式测试数据库连接的 PostgreSQL 集成场景。
- 设置进程内 `VENAGENT_TEST_DATABASE_URL` 后运行 `tests/test_persistence.py::test_postgres_migration_and_restart_recovery`：1 passed；真实 Docker PostgreSQL 已升级到 schema v3，`conversation_imports` 不存在，active thread 可跨 runtime 继续并正常删除。
- `npm.cmd run test:e2e -- workspace.spec.ts`：5 passed；真实 Chrome 覆盖创建删除、流式重试、取消、失效会话提示与禁用、刷新保持、移动端查看和删除。
- `npm.cmd run build`：Vue TypeScript 检查与 Vite 生产构建通过。
- `.\.venv\Scripts\python.exe -m compileall -q venagent tests`：通过。
- Node 编译 `venagent/web/index.html` 内联脚本：通过，输出 `static web script syntax ok`。
- `.\.venv\Scripts\python.exe -m pip check`：通过，无损坏依赖。
- `comet native check remove-legacy-conversation-import --json`：通过；扫描 21 个 scope 文件、94282 bytes、0 issues，receipt 为 `runtime/evidence/check-receipts/3bc906fe765989affcb8e206bfd9307cc756be7bf6622a343fed058c2ce4b433.json`。

# Skipped checks

- 未调用真实外部 LLM；聊天、SSE、错误和持久化路径均使用可控模型或 HTTP mock，避免外部请求与凭据使用。
- 未进行额外的人工探索式浏览器验收；真实 Chrome Playwright 已模拟并断言本次要求的完整用户操作路径。
- Ruff、mypy、Bandit、pip-audit、Black 和 isort 未安装，未将其写成通过；已执行 Python 编译、完整 pytest、依赖完整性检查及 Python/FastAPI/通用人工复核。

# Spec consistency

`conversation-persistence`、`frontend-foundation` 与 `skill-orchestration` 三份拟议完整规格一致移除旧会话导入要求。运行时不再包含导入 schema、领域服务、repository port、PostgreSQL adapter 或健康能力；HTTP 仅保留不进入 OpenAPI、固定返回 404 的已删除端点 tombstone，避免动态线程路由误报 405。前端在 `thread_not_found` 后持久化不可用状态，显示持续横幅并禁用发送与重试。

# Known limitations and risks

- `venagent/config/config.yaml` 是 change 创建后的无关用户改动，经用户确认通过 partial-scope allowance 排除；本 change 未修改或回退该文件，也不把它作为验证证据。
- 已经成功导入并成为 `active` durable thread 的历史会话继续作为普通持久线程可用；本 change 只删除新的导入入口与映射表。
- schema 仍识别升级前可能遗留的 `importing` lifecycle 值，仅用于启动时通过公开 checkpointer API 清理，不重新暴露导入能力。

# Conclusion

PASS。旧会话导入的用户入口、API 表面、领域逻辑、持久化实现、健康字段与数据库映射已删除；后端拒绝的浏览器本地会话在桌面和移动端均明确显示为不可用，只能查看或删除。全部 7 项验收均有项目内实现或自动化测试证据。
