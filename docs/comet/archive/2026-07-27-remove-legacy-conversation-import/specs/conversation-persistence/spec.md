# Conversation Persistence 完整目标规格

## 1. 模块取舍

M03 `conversation-persistence` 的整体状态为 `replace`。

VenAgent SHALL 保留持久对话、服务重启恢复、schema 迁移和明确清理的产品目标。VenAgent SHALL NOT 提供浏览器旧会话导入、按用户共享聊天历史、自制短期记忆预热、业务 snapshot 模拟框架 checkpoint 或启动路径中的无版本 DDL。

## 2. 能力目标

`conversation-persistence` SHALL 在 M01/M02 契约上建立 durable thread metadata 与官方 LangGraph persistent checkpointer，使最近 5 个完整成功轮次可跨服务重启继续使用。

首个持久化后端 SHALL 为 PostgreSQL，并提供根级最小 Docker Compose 服务。VenAgent 与官方 checkpointer schema SHALL 由显式迁移或初始化命令建立和升级；普通启动只校验兼容性。

浏览器 localStorage SHALL 只保存当前浏览器可见记录。后端判定 thread 不存在后，该本地记录 SHALL 变为不可用只读记录，且不得被上传、恢复或导入为新的 durable thread。

## 3. 持久状态边界

- 线程业务元数据 SHALL 记录权威 `thread_id` 及持久生命周期事实；LangGraph checkpointer SHALL 独立保存 graph state、checkpoint writes 与 blobs。
- 业务元数据与 checkpoint SHALL 分别建模，不得以浏览器 localStorage、chat history 表或自制 snapshot 代替官方 checkpointer。
- graph state SHALL 只包含 committed messages 与当前图执行所需字段；`thread_id` SHALL 通过 LangGraph config 传递。
- 只有完整成功且形成 M01 同步成功或 M02 `completed` 终态的 user/assistant 对才可进入 durable state。
- 模型异常、取消、断开、pending user、partial assistant、active run、取消信号和 SSE 事件 SHALL NOT 提交或恢复。
- 每个线程 SHALL 只保留最近 5 个完整成功轮次，按时间正序、以完整对为单位裁剪。
- VenAgent SHALL NOT 修改、扩展或直接查询官方 checkpointer 的物理表，也不得建立指向其内部表的业务外键。

## 4. VenAgent 线程元数据

- VenAgent SHALL 自有 `conversation_threads` 表，保存权威 UUID `thread_id`、生命周期、创建与更新时间和可空的删除请求时间。
- `conversation_threads` SHALL NOT 保存消息正文、checkpoint blob、owner、标题、文件夹、run、消息计数或通用 metadata。
- 新 schema SHALL 不包含 `conversation_imports` 或等价旧会话导入映射。
- `active` 线程可创建运行；`deleting` 线程不得创建新同步或流式运行，并 SHALL 返回 HTTP 409 与稳定 code `thread_deleting`。
- 删除 SHALL 先把元数据标记为 `deleting`，再通过官方 checkpointer API 删除该线程的 checkpoints、writes 与 blobs，最后删除线程元数据。
- 服务启动 SHALL 收敛遗留 `deleting` 记录；升级前遗留的 `importing` 记录 SHALL 作为兼容清理状态收敛，不得重新暴露导入功能。

## 5. 重启与运行生命周期

- 服务重启后，持久线程 SHALL 保持原 `thread_id`，同步与流式聊天可继续读取已提交上下文。
- 重启 SHALL 清空进程内 busy、active run 和取消 registry；旧 `run_id` SHALL 返回既有 `run_not_found`。
- 重启期间未形成成功终态的运行 SHALL 被视为未提交，不得自动继续、重放或补交。
- 同线程单活跃运行、不同线程并发、active thread 删除冲突和目标取消行为 SHALL 保持 M01/M02 契约。
- M03 SHALL NOT 新增 run status、resume、SSE replay 或 `Last-Event-ID` API。

## 6. 线程创建与删除

- `POST /api/threads` 成功前，权威线程元数据 SHALL 已持久化。
- 同步与流式聊天 SHALL 先依据权威线程事实判断存在性，再访问 checkpoint；格式非法与未知线程使用稳定安全错误。
- 删除空闲线程 SHALL 清理线程业务元数据及其全部 checkpoint 状态，且操作可安全重试。
- 删除完成后，同一 `thread_id` 的聊天 SHALL 返回 `thread_not_found`；重复删除 SHALL 幂等返回 HTTP 204。
- 删除部分失败不得伪装成完整成功；实现 SHALL 提供失败关闭与残留收敛路径。
- 自动 TTL、按 owner 保留、归档和批量清理不属于 M03。

## 7. Schema、降级与健康状态

- 持久 schema SHALL 有连续明确版本；初始化和升级 SHALL 幂等，并拒绝未知新版本或无法安全升级的状态。
- 显式 migration SHALL 从既有 v1/v2 schema 升级并删除 `conversation_imports` 表，不得删除已经处于 `active` 状态的 durable thread 或其 checkpoint。
- 普通应用启动 SHALL NOT 自动执行 DDL，只校验 VenAgent 与官方 checkpointer schema 是否兼容。
- PostgreSQL 未配置、连接失败或 schema 检查不可用时，应用 SHALL 固定选择 memory degraded 模式；基础聊天可用，但线程和消息不可跨重启恢复。
- durable 模式运行中数据库故障时 SHALL NOT 静默切换内存形成第二份状态。
- 启动日志 SHALL 以稳定结构化字段和中文说明公开模式、PostgreSQL 状态、reason code 与跨重启恢复能力，不得泄露连接串、凭据或原始数据库异常。
- `GET /health` SHALL 保持 HTTP 200 与顶层 `status: ok`，并公开 PostgreSQL、chat 和 conversation persistence 状态。
- `GET /health` SHALL NOT 公开 `legacy_browser_import` 或等价导入能力字段。
- M03 SHALL NOT 新增无真实依赖判断的 `/readyz`。

## 8. 失效浏览器记录

- Web UI SHALL 继续区分 localStorage 完整可见记录与后端模型上下文，不得把本地记录视为持久 checkpoint。
- 只有后端返回稳定 `thread_not_found` 时，当前本地会话 SHALL 被标记为失效；普通网络错误、模型错误或取消不得触发该状态。
- 失效会话 SHALL 在 localStorage 中持久保存失效状态，刷新页面后仍保持不可用。
- 失效会话的已有消息 MAY 继续显示，且用户 MAY 从本地会话列表删除该记录。
- 失效会话 SHALL 禁用消息输入、发送、失败消息重试和其他会创建运行的操作。
- 失效会话的列表项 SHALL 显示“不可用”状态；选择该会话后，消息区上方 SHALL 持续显示“后端上下文已失效。此对话仅保留在当前浏览器中，只能查看或删除，无法继续发送消息。”，不得只使用会消失的一次性通知表达该限制。
- 前端 SHALL NOT 显示导入、恢复、认领或重新绑定按钮，也不得向服务端上传该会话的本地消息。
- 后端 SHALL NOT 提供 `POST /api/threads/import` 或其他浏览器旧记录导入接口；OpenAPI SHALL 不包含此类路径。
- 已经成功导入并处于 `active` 状态的 durable thread SHALL 继续作为普通持久线程工作，不因移除导入能力而失效。

## 9. Web UI 与兼容性

- M01 同步 API、M02 SSE 事件和取消 API 的请求与成功结构 SHALL 保持兼容。
- Web UI SHALL 准确说明 durable 与 memory degraded 模式，不得把 degraded 模式表示为已持久化。
- 新建、切换、删除、completed、cancelled、error 和连接丢失状态 SHALL 保持既有行为；页面不得跨线程写入恢复结果。
- 服务端会话列表、历史读取、标题、文件夹、归档、分叉、备份导入导出和会话资料引用不属于 M03。

## 10. 相邻模块边界

- M01 定义线程身份、上下文隔离、最近 5 个成功轮次、同步 API 和基础 Web UI。
- M02 定义 `run_id`、SSE、token streaming、目标取消、断开和流中错误；M03 不改变断开即取消契约。
- 身份授权、跨用户边界和用户级数据生命周期属于后续明确批准的能力。
- 可靠并行、幂等重试、长任务 checkpoint 恢复和复杂部分失败属于后续 agent orchestration 能力。

## 11. 验收基线

实现 SHALL 使用无网络、无真实凭据的可控模型和隔离数据库证明：

- 已提交对话跨服务实例重建后可继续，且最多保留最近 5 个完整成功轮次；
- 不同线程跨重启后仍隔离，同步失败、流式错误、取消和异常断流不持久化半轮；
- 重启清空 busy、active run 和旧取消句柄，不恢复或重放运行；
- 线程创建、未知、显式删除、重复删除和清理失败符合契约；
- schema 从 v1/v2 升级后不再包含导入映射，既有 active threads 保持可用，遗留 lifecycle 状态可收敛；
- PostgreSQL 不可用时降级模式、日志、健康状态和 Web UI 准确显示能力边界；
- `thread_not_found` 后本地会话在当前页面和刷新后均不可发送、重试、恢复或导入，但消息仍可查看且记录可删除；列表和持续状态横幅准确提示不可用原因与允许操作；
- 导入 API、OpenAPI 路径、健康能力字段、前端入口和运行时代码均已移除；
- M01/M02 API、SSE、取消和 Web UI 隔离回归继续通过。
