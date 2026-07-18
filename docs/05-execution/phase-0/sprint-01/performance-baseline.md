# Phase 0 Legacy 安全性能基线

## 测试边界

本基线使用本地 mock、内存逻辑和降级路径，不启动 Compose、不连接真实 LLM/Embedding、RAG 基础设施或外部 HTTP 服务。它用于记录当前 legacy 的可重复安全基线，不代表生产服务性能，也不代表 Phase 3 真流式性能。

采样方式：多次运行后记录 min、median、p95、max，单位为毫秒。

## 结果

| 场景 | 样本 | min | median | p95 | max |
|---|---:|---:|---:|---:|---:|
| `default_config()` 配置加载 | 15 | 5.746 | 6.056 | 10.881 | 10.881 |
| legacy mock chat stream（逐字符 sleep） | 7 | 770.885 | 775.770 | 788.655 | 788.655 |
| legacy `/api/chat/stream` fake agent endpoint | 15 | 4.899 | 5.847 | 12.786 | 12.786 |
| RAG 未加载降级路径 | 30 | 0.000 | 0.000 | 0.003 | 0.004 |
| legacy GraphRuntime 两节点 workflow | 15 | 0.578 | 0.637 | 0.929 | 0.929 |

## 解释

- mock chat stream 的约 0.78 秒主要来自当前逐字符 `sleep`，不能作为真流式目标；
- fake endpoint 只验证 HTTP/SSE 适配开销；
- RAG 项为未加载降级路径，不等价于真实向量检索；
- 真流式 TTFT、增量间隔、取消延迟和真实 RAG 性能在 Phase 3 实现后重新测量。
