# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-68ab9ee93df7782359736de08961d881ec0a56f3b077923ce67c2ac21ab2b15b",
    "evidence_refs": [
      "tests/test_memory_semantics.py",
      "venagent/memory/model_adapters.py"
    ]
  },
  {
    "acceptance_id": "acceptance-86ea2d13180a46c99dab867659467c7d17375e8b13fe234a19b650d2597d4ac0",
    "evidence_refs": [
      "tests/test_memory_index.py",
      "venagent/llm/__init__.py",
      "venagent/llm/embeddings.py"
    ]
  },
  {
    "acceptance_id": "acceptance-95e93cbd768204e8312732e6cedc6f982f8ea29ddd98c60324e3fe3640e29dc9",
    "evidence_refs": [
      "tests/test_memory_graph_store.py",
      "tests/test_memory_index.py",
      "venagent/bootstrap.py",
      "venagent/memory/embedding/__init__.py",
      "venagent/memory/graph_memory/__init__.py"
    ]
  },
  {
    "acceptance_id": "acceptance-e5c2f7e2ad00b586abb19a10b0c08ee0f78849d04ed818993841b6eb29d1b1c1",
    "evidence_refs": [
      "tests/test_memory_context.py",
      "tests/test_memory_graph_store.py",
      "tests/test_memory_index.py",
      "tests/test_persistence.py",
      "web/tests/e2e/memory.real.spec.ts"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `.venv\Scripts\python.exe -m pytest -q`：214 passed，包含真实 PostgreSQL 与 Neo4j 集成测试。
- `.venv\Scripts\python.exe -m ruff check venagent tests`：通过。
- `.venv\Scripts\python.exe -m compileall -q venagent`：通过。
- `npm.cmd run build`：Vue TypeScript 检查与 Vite 生产构建通过。
- 布局契约探针：`HttpEmbeddingClient`、`MemoryIndex`、`EmbeddingPort`、`GraphMemory` 和 disabled store 可从目标包导入；`venagent.llm.memory` 导入失败，符合删除旧边界的契约。
- 真实 DeepSeek 提取探针：稳定双事实输出 2 个合法候选；问题、假设和提示注入分别输出 0 个候选。
- `npx.cmd playwright test tests/e2e/memory.real.spec.ts`：1 passed；真实 durable 后端完成刷新、跨会话召回、更新、遗忘、开关及全部删除。
- `comet native check refine-m05-memory-boundaries`：通过，receipt 为 `runtime/evidence/check-receipts/fb61317f2f4b3c4407141ff77345c2de94128f3051bbbf8e1cbd7130265febb6.json`。

# Skipped checks

- 未调用真实外部 embedding endpoint：当前 `.env` 未配置完整 embedding 服务。HTTP adapter 的成功、失败脱敏和降级行为由 `tests/test_memory_index.py` 覆盖，真实运行状态明确报告 `embedding_not_configured`。

# Spec consistency

- `venagent.llm.embeddings` 保留为不含 M05 业务语义的通用 HTTP embedding adapter，供后续 RAG 复用。
- M05 专用索引 port/实现位于 `venagent.memory.embedding`，图记忆服务位于 `venagent.memory.graph_memory`，模型记忆 adapter 位于 `venagent.memory.model_adapters`。
- 提取提示词只以用户原文为来源，使用整段安全闸门、逐候选资格判断、完整 schema 正反例和精确半开 source span；没有引入 AGI-saber 的 KV 表结构、偏好写入或 assistant 派生记忆。
- 更新命令在原有授权边界内允许读取其待更新目标，仍由 action class 和 scope 限制访问。

# Known limitations and risks

- 当前真实环境的向量索引保持禁用；配置真实 embedding endpoint 后仍需补一次供应商级联调。
- LLM 输出具有供应商非确定性；严格 JSON/schema/span 校验会将不合规输出作为提取失败处理，不会写入未经验证的事实。

# Conclusion

通过。实现与当前确认契约一致，自动化、真实数据库、真实模型、真实浏览器和 Comet 内置检查均未发现阻塞问题。
