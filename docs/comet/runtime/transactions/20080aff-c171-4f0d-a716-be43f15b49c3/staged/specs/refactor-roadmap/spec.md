# VenAgent 选择性重构路线规范

## 目标

VenAgent SHALL 以 `AGI-saber` 为行为参考，通过独立、可审批、可验收的阶段逐步扩展，不进行源码迁移或一次性全量重构。

## 架构不变量

- 运行时编排 SHALL 使用 LangGraph；模型和工具适配 SHALL 使用 LangChain 公开边界。
- Web/API、应用服务、图运行时、领域能力、Ports 和 Adapters SHALL 保持可识别边界。
- 对话线程、LangGraph checkpoint、长期语义记忆、用户偏好、任务状态、文档和运行事件 SHALL 分别建模。
- 外部服务失败不得被伪装成真实成功；降级状态 SHALL 可测试、可观察。
- 新能力 SHALL 默认提供无网络、无真实凭据的验证路径。

## 阶段顺序

1. Phase 0：最小 Agent Loop、真实模型适配器和基础 Web UI，已完成。
2. Phase 1：以 `thread_id` 为核心的多轮会话、内存 checkpointer、SSE 和会话隔离。
3. Phase 2：持久化 conversation/checkpoint、恢复、可选身份边界与数据生命周期。
4. Phase 3：偏好与长期语义记忆、召回、安全审计、删除和替代。
5. Phase 4：工具循环、结构化工具结果、受控 MCP、沙箱和人工审批。
6. Phase 5：文档库、最小可评测 RAG、引用与按证据引入的混合检索。
7. Phase 6：任务规划、并行/恢复、子 Agent 和产物交付。
8. Phase 7：完整 Web 产品体验、Skill 取舍、观测、部署和平台治理。

## 阶段治理

- 路线批准只授权把 Phase 1 作为下一候选，不授权任何阶段直接进入 Build。
- 每阶段 SHALL 使用独立 Comet Native change，并在 Shape 中重新确定用户可见行为、范围、非目标和验收标准。
- 每阶段完成、验证和归档后 SHALL 由用户决定是否进入下一阶段。
- `AGI-saber` 中存在的功能如果未被当前阶段明确选择，SHALL 视为非范围。

## Phase 1 起点

路线获批后，Phase 1 SHALL 首先审计旧项目的 UI session、STM、chat_history、SSE 和取消行为，并定义稳定的 `thread_id` 契约。初始存储可以是进程内实现，但后续更换持久化后端不得改变线程隔离和 API 语义。
