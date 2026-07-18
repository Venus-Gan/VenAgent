# Phase 0 HTTP/SSE/OpenAPI Legacy 基线

## 范围

本记录只冻结当前 legacy 外部契约，不把当前伪流式 token 时序当作重构目标。真流式链路属于 Phase 3 的 `P3-15`。

## OpenAPI

当前应用标题为 `AGI Assistant`，版本为 `1.0`。基线路由集合为：

- `/health`
- `/api/chat`、`/api/chat/stream`、`/api/chat/cancel`
- `/api/docs/delete`、`/api/upload`
- `/api/documents`、`/api/documents/{document_id}`、`/api/documents/{document_id}/ingest`
- `/api/tools`、`/api/tools/mcp`
- `/api/status`、`/api/memory`、`/api/snapshots`

`ChatRequest.message` 为必填且最小长度为 1；`use_rag` 和 `explicit` 默认值为 `false`。

## SSE

当前 chat stream legacy 基线要求：

- `start` 首发；
- `route` 最多一次；
- `token` 按当前实现顺序发送；
- `done` 恰好一次；
- 以 `data: [DONE]` 结束；
- payload 带有 `request_id`；
- 测试使用 fake agent，不访问真实 LLM。

已覆盖测试：

```text
python -m pytest tests/test_phase0_http_contract.py tests/test_frontend_main_alignment.py -q
12 passed
```

后续真流式迁移允许改变 token 到达时序，但必须保持 envelope、字段、结束语义和取消边界，并新增 Phase 3 真流式测试。
