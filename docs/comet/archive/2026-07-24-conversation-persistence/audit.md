# M03 conversation-persistence 审计

## 审计范围

- VenAgent 当前 M01/M02 实现、canonical 规格、测试和归档证据。
- 冻结参考仓库 `D:\VSCProject\AGI-saber` 中聊天历史、短期记忆和 PostgreSQL schema 行为。
- 当前环境的 LangGraph 与 checkpointer 安装情况。

## VenAgent 当前事实

- `venagent/agent_loop.py` 使用 LangGraph `InMemorySaver`，以 `configurable.thread_id` 隔离状态，并只在完整成功后提交最近 5 个 user/assistant 轮次。
- `venagent/conversation.py` 的 `ThreadRegistry` 仅在内存保存线程存在性和 busy；进程重启后所有旧线程均返回 `thread_not_found`。
- M02 的 `RunRegistry`、取消信号和 SSE 生命周期均为进程内状态。canonical `streaming-run-lifecycle` 明确排除断线续传、运行结果持久化和可靠恢复。
- Web UI 的 localStorage 保存完整可见记录，但 M01 canonical 规格明确它不是模型上下文或后端事实源。
- 当前依赖包含 `langgraph 1.2.x`，环境实装为 1.2.9；`langgraph.checkpoint.sqlite` 和 `langgraph.checkpoint.postgres` 均未安装，需要按最终后端决定增加官方扩展依赖。

## AGI-saber 参考结论

- 旧实现把 `chat_history` 按 `user_id` 写入 PostgreSQL，并在请求时加载最近若干条到自制 `ShortTerm` 容器。
- 旧表和读取路径没有稳定 conversation/thread identity，容易让同一用户的不同对话共享上下文。
- 旧实现将聊天记录恢复与短期记忆容器耦合，不是 LangGraph checkpointer，不能证明 checkpoint schema、pending writes、并发或恢复语义。
- 旧 schema 通过应用启动路径散落执行 `CREATE TABLE IF NOT EXISTS` 和 `ALTER TABLE`；缺少独立版本账本、完整回滚边界和针对半迁移状态的验证。

## 取舍

| 子能力 | 状态 | 结论 |
| --- | --- | --- |
| 跨重启保留线程存在性 | adopt | 保留产品目标，以独立线程元数据存储重新实现。 |
| LangGraph graph state 持久化 | replace | 使用官方持久 checkpointer，不用 chat history 或业务 snapshot 模拟。 |
| 按 `user_id` 加载共享 STM | drop | 与 M01 `thread_id` 隔离冲突，且身份属于 M04。 |
| active run / SSE 恢复 | defer | M02 明确排除，复杂可靠恢复属于 M15。 |
| 完整服务端会话库 | drop | M03A 已由路线明确舍弃。 |
| schema 迁移与清理 | replace | 建立有版本、可失败关闭和可离线测试的边界，不复制旧启动期散落 DDL。 |

## 风险与依赖

- 持久后端选择会改变部署依赖、并发上限和验证矩阵，必须由用户确认。
- 自动内存降级会让客户端误以为线程已持久化；若允许，必须公开 degraded 状态且不能声称 durable success。
- 浏览器旧记录是非可信客户端数据；自动导入会新增写入 API、校验、重复导入和数据归属问题，并接近已 drop 的 M03A import 能力。
- 持久 checkpoint 与线程元数据的跨存储删除无法天然获得单事务 exactly-once；实现必须定义可重试、失败关闭的删除顺序与残留清理。
- M04 前没有 owner 授权，持久 `thread_id` 泄露后的风险持续时间高于内存模式；部署边界必须继续明确为单用户或受信环境。

## 旧浏览器会话迁移审计

- 当前 Web UI 使用 `venagent.conversations.v1` 保存完整可见记录；user 消息具有 `sending/sent/failed`，assistant 消息具有 `streaming/cancelling/sent/cancelled/failed` 等状态。页面重载会把未完成状态转为 failed。
- 当前 v1 不保存 failure kind：SSE `error`、普通连接失败以及页面重载时遗留的 `streaming/cancelling` 最终都可能表现为 assistant `failed`。因此历史 v1 数据无法可靠执行“只接受连接失败、排除模型错误”的筛选。
- localStorage 是客户端可修改数据，不能证明某条 assistant 文本确由服务端完整成功生成。导入保持 assistant 角色会提高连续性，但也会把客户端内容置于更高语义角色；改为单条用户引用文本则更保守但不能恢复原对话结构。
- M03A 已 drop 的是通用会话库、归档、分叉和备份导入导出。用户选择的 Q3=B 只能定义为现有 v1 本地格式的一次受限迁移，不能演化为通用 import API 或服务端会话浏览能力。
- 导入必须生成新的服务端 `thread_id`，不能复活 M01 失效 ID。由于线程元数据和官方 checkpointer 不共享可控事务边界，需使用稳定 import key 与 `importing` 状态或等价恢复协议，避免响应丢失或崩溃产生重复线程和孤儿 checkpoint。
- 迁移只在 durable 模式有意义；memory degraded 模式必须保留本地记录并明确不可导入。超过 5 轮的可见记录仍可留在浏览器，但模型上下文只接收经确认规则筛选后的最近 5 个完整轮次。
- 用户确认 v1 `failed` partial 一律排除。这样不会根据缺失的 failure kind 猜测历史事实；明确 `cancelled` 且有非空 partial 的轮次仍可由用户逐轮选择，以保留有限连续性。

## 健康与降级审计

- AGI-saber 的 `/healthz` 与 `/readyz` 都无条件返回 HTTP 200 `ok`，不能区分基础设施缺失、能力降级或真正就绪，因此不适合作为 M03 契约。
- 旧 `final` 的 `/health` 保持顶层 `status: ok`，同时逐项返回 PostgreSQL、Milvus、Elasticsearch 和 Kafka 的 `connected/disconnected` 状态；该兼容形状值得保留。
- 旧 Phase 1 健康评估器进一步证明 PostgreSQL 断开时基础 chat 仍可 `available`，但 durable workflow 应为 `unavailable`；可选能力失败不应拖垮无关能力，也不能报告为成功。
- M03 采用分层状态：进程可服务时 `/health` 继续 HTTP 200 且顶层 `status: ok`；另行公开 `durable/degraded` 运行模式、PostgreSQL 基础设施状态和 chat/conversation-persistence 能力状态。
- 启动终端使用“稳定结构化字段 + 中文自然语言说明”表达已选择的运行模式。中文说明直接解释 PostgreSQL 状态、当前使用的存储模式以及对话能否跨重启恢复；未配置或不可用导致的预期内存降级不使用“显著警告”或装饰性符号。运行中已建立的 durable 连接失效仍按真实故障记录和失败关闭。
