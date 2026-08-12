# Outcome

修复 Web 在刷新、重新选择会话或成功发送后的详情重载中丢失本机失败、取消和 partial 消息的问题。服务端 committed turns 继续作为成功历史的权威事实源，浏览器则保留未提交的可见结果，并按 `client_message_id` 收敛两者。

# Scope

- 在现有 `web/src/modules/chat` 中实现服务端 committed turns 与本机消息的确定性归并。
- 让同一次发送的 user/assistant 消息共享 `clientMessageId`，并兼容已保存的旧缓存结构。
- 把页面重载后不可能继续运行的 `sending|streaming` 状态转换为明确的连接中断状态。
- 修正显式重试，使其复用原消息位置与 `client_message_id`，成功后只显示一组 committed 消息。
- 扩展现有 Playwright mock 与浏览器用例，覆盖刷新、取消、partial、顺序、幂等收敛、旧缓存和身份隔离。

# Non-goals

- 不修改 FastAPI 路由、HTTP/SSE 协议、错误码、数据库 schema、业务 turn、JWT、Cookie、owner 生命周期或 LangGraph checkpoint。
- 不把失败、取消、partial 或断线运行上传到服务端，不提供跨设备同步、运行恢复或自动重发。
- 不新增前端状态管理、数据归并或测试依赖，不创建新的 Vue feature module、共享 package 或路由。
- 不改变注销、切换账号、匿名登录后本机历史和 `local_only` 的现有隐私边界。

# Acceptance examples

- 流收到 partial token 后以 `error` 结束；刷新页面后，用户输入、partial 文本和失败标记仍按原位置可见，服务端详情仍不包含该半轮。
- 流收到 partial token 后以 `cancelled` 结束；刷新页面后仍显示 partial 文本和“已取消”。
- 浏览器在 `sending|streaming` 尚未形成终态时刷新；恢复后不得继续显示“发送中/生成中”，而应显示连接已中断并允许用户重试。
- 浏览器本地误保留失败状态，但服务端已经存在相同 `client_message_id` 的 committed turn；详情重载后只显示服务端成功轮次，不显示重复失败记录。
- 本机失败 A 后又成功发送 B；详情重载后顺序仍为 A、B，不把 A 简单追加到末尾。
- 用户重试失败消息并成功；原位置收敛为唯一成功 user/assistant 对，不累积旧失败助手消息或重复 committed turn。
- 现有 v1 legacy 与 v2 浏览器缓存继续可读取；账号失败缓存不泄露给注销后的 guest 或切换后的其他账号，跨浏览器仍只恢复 committed history。

# Constraints and invariants

- `conversation_turns` 和线程详情只返回完整 committed user/assistant 对；失败、取消、断开和 partial 不得写入服务端业务历史或 checkpoint。
- 相同 `client_message_id` 的服务端 committed turn 胜过本机未完成状态；服务端未出现该 ID 时，本机状态不得因普通详情刷新、网络失败、取消、429、409 或 503 被删除。
- 归并必须保留当前浏览器已知消息顺序，并使用服务端 turn sequence 安排新增 committed turns；不得用“服务端消息 + 全部本机失败消息”的尾部追加实现。
- 页面重载不能宣称旧运行仍 active，也不能把未收到权威终态的运行伪装成 completed 或 cancelled。
- Vue 继续使用文本插值显示本地与服务端内容，不引入 HTML 注入面；JWT access token 仍只在内存，refresh token 边界不变。
- 工作区已有大量用户重构改动；实现只处理当前 change 的聚焦文件，不整理或回退其他变化。

模块 intake：

- 模块：M04 ownership-lifecycle 的前端持久记录缺陷修复。
- 基础 intake：已读取 `ecc-rules-pack-common`、`ecc-rules-pack-python` 与 `search-first`；本 change 不修改 Python，Python 规则只用于确认不扩展后端范围。
- 专项能力：`api-design` 用于确认 API 契约不变；`security-review` 用于确认 owner 缓存隔离与文本渲染边界；`frontend-patterns` 与 `e2e-testing` 用于 Pinia 状态归并和浏览器回归。
- search-first：仓库检索、npm 工具链可用；`gh` 不可用；本任务不增加依赖，未查询外部 registry。结论为 Extend，复用现有 Pinia store、`client_message_id`、localStorage 和 Playwright mock。
- AGI-saber：对照身份、本机会话、SSE 失败和取消行为。优先读取 `internal/domain/auth`、`internal/application/auth`、`internal/usercontext`、`internal/infrastructure/persistence/userrepo`；为核对实际前端失败保留行为，最小扩展到 `web/src/stores/{auth,chat,sessions}.js` 与 `web/src/composables/useSSE.js`。旧项目没有权威服务端历史归并，故只采用“本机保留可见失败结果”的产品行为，不采用其 JWT localStorage、同步回退或本地会话架构。
- 目录：现有相关目录为 `web/src/modules/chat` 与 `web/tests/e2e`；不触发 `product-capability`，不新增 package、module、route 或共享层。
- 前端：用户发送、停止、刷新、重试；正常态显示 committed turn，失败/取消/连接中断保留本机文本，历史读取失败保持现有只读降级，无权/身份切换继续按 owner 隔离。

# Decisions

- 用户已批准本 change 的修复计划与验收边界。
- 归并以本机消息顺序作为可见骨架，以服务端 sequence 补齐和替换 committed turns；相同 `client_message_id` 只形成一个可见发送结果。
- user 与 assistant 都携带同一 `clientMessageId`；旧 assistant 缺少该字段时，只在明确相邻 user/assistant 对中推断，不跨用户消息猜测。
- 明确收到 `failed|cancelled` 的状态原样保留；重载遗留的 `sending|streaming` 统一转成 `interrupted`，对应用户消息可显式重试。
- 重试继续使用原 `client_message_id`，并复用对应本机 user/assistant 位置；服务端幂等重放或新提交成功后由 committed turn 取代本机状态。
- 本机未完成记录只在当前浏览器和当前身份缓存内存在；注销或切换账号继续清除前一账号缓存，匿名登录后的既有 guest 对话继续按已确认规则转为 `local_only`。
- canonical `conversation-context`、`streaming-run-lifecycle` 与 `conversation-persistence` 已完整规定目标行为，本 change 不修改长期规格。

# Open questions

无。用户已确认全部用户可见结果，剩余选择均为不改变契约的实现细节。

# Verification expectations

- 先新增能够复现当前覆盖缺陷的 Playwright 用例并确认在旧实现上失败，再实现最小归并逻辑使其通过。
- 运行 `npm.cmd run build` 与 `npm.cmd run test:e2e`，记录总数、失败和跳过项。
- 运行项目完整 pytest 回归，证明未改动的服务端提交、取消、owner 和 checkpoint 契约没有回归；PostgreSQL 未启动时如有既有集成测试跳过，必须如实记录。
- 启动项目 PostgreSQL 与应用，使用真实浏览器验证失败/partial 刷新、取消刷新、重试成功和消息顺序；验收完成后报告服务与容器状态。
- 运行 Comet 有界文本检查并记录 receipt；针对本 change 执行前端状态、身份隔离、XSS 文本渲染和无秘密变更复核。
