# Outcome

修复自然语言记忆被管理命令短路的问题。用户以普通中文表达“请记住……”或“忘记……”时，系统必须创建正常对话 run、保存用户与 assistant 消息并返回自然语言回答；记忆提取模型从完整用户原文一次拆分结构化候选，统一策略只判断一次，真实写入结果在显式记忆意图的最终回答生成前可用，避免虚假确认。

# Scope

- 只有 `/memory ...` 斜杠管理命令继续走确定性短路响应；自然语言记忆意图进入正常对话链路。
- 显式“记住”意图在同一 run 内调用现有结构化 extractor、统一评估候选并完成权威写入，再把保存、部分保存、拒绝或不可用结果作为受信任上下文交给聊天模型生成最终回答。
- 普通非显式事实陈述保持回答发布后的异步提取；两类入口复用同一套 extractor、候选契约、统一 eligibility decision 与 writer。
- 删除提取前对整条消息的普通资格拒绝，以及 writer 对完整原文的重复资格判断。模型负责拆分；确定性代码一次校验 schema/source span，并一次性评估全部候选。
- 整条原文包含秘密、完整支付数据或提示注入等硬风险时，统一评估可以拒绝全部候选；否则保存 accepted，丢弃 rejected，允许部分成功。
- 自然语言“忘记 X”保留唯一强匹配、歧义和零匹配安全语义，但结果通过正常 assistant 回复呈现，不以记忆 notice 替代聊天。
- 更新 Python/API/前端及真实浏览器回归测试，使自然语言记忆与 `/memory` 管理命令的不同响应契约可复核。

# Non-goals

- 本 change 不新增 `preferred_name`，不处理“以后叫我星野”等称呼偏好语义。
- 不改变用户偏好、人格化指令、健康/财务/法律、第三方、秘密和支付数据的既有持久化资格结论。
- 不新增专用记忆页面、记忆面板、工具调用框架、数据库表、图关系或 embedding provider。
- 不改变 `/memory status|list|show|update|forget|revoke-source|disable|enable|delete-all` 的管理语义。

# Acceptance examples

- 已认证用户发送“请记住，我叫青岚”时，API 返回正常 run，页面显示用户消息和 assistant 回复；事实权威写入成功后，assistant 可以明确说明已记住。刷新并新建 conversation 后询问“我叫什么”能够召回“青岚”。
- 用户发送“请记住，我叫林舟，我喜欢乌龙茶”时，extractor 一次拆分候选，统一策略保存姓名并拒绝既有契约不允许持久化的偏好；assistant 根据真实 partial outcome 说明哪些已保存、哪些未保存。
- 显式记忆写入被关闭、拒绝或权威存储不可用时，普通对话仍形成 run 与 assistant 消息，assistant 不得声称已保存，并根据净化后的真实结果说明未保存。
- 用户发送不以 `/memory` 开头的“忘记我住在杭州”时，仍形成正常 run；唯一强匹配才删除，多匹配或零匹配不得误删，assistant 根据真实结果回答。
- `/memory status` 仍返回 `kind=memory_command`，不创建 message、run 或模型调用。
- 普通陈述“我叫林舟，我喜欢乌龙茶”正常获得模型回复；回答发布后 extractor 有机会拆分，姓名候选不会仅因同句包含偏好而在 extractor 之前整句丢弃。

# Constraints and invariants

- 记忆写入和删除仍要求当前 owner/tenant、scope/action、authorization epoch 与 durable identity 全部有效；关闭、删除 generation、来源和生命周期围栏不变。
- extractor 输出是不受信任的候选建议。严格 JSON schema、字段集合、数量/长度、source span 与原文一致性校验不计作第二次业务资格判断，任何无效输出不得写入。
- eligibility decision 对一次 extractor 输出只执行一次，并产出 accepted、rejected 与可选 source-level hard rejection；writer 不重新解释完整原文。
- 显式记忆 outcome 只包含净化后的 slot/value/fact 状态和 reason code，不把异常、凭据、连接串或内部提示暴露给聊天模型与前端。
- assistant 自由文本、摘要和最终 Prompt 仍不能成为长期事实来源。
- HTTP router 保持薄层，记忆事实与编排逻辑留在 `venagent/memory/` 与 agent runtime，不迁入 `interfaces/http/` 或 `infra/`。

# Decisions

- 用户已确认：LLM 负责对完整原文拆分候选，全部候选随后统一判断一次；不保留提取前普通资格判断和 writer 重复判断。
- 用户已确认：自然语言记忆必须同时完成正常对话，不能用记忆系统提示替代 LLM 回复。
- 用户已确认：显式记忆只有在真实结果可用后才允许 assistant 说已记住；普通非显式自动提取可继续异步。
- 用户已确认：本 change 暂不引入 `preferred_name`。
- 模块：M05 memory-system。
- 基础 intake：已读取 `ecc-rules-pack-common`、`ecc-rules-pack-python` 与 `search-first`；本变更不需要新增第三方依赖。
- 专项能力：沿用 M05 的存储、隐私与安全边界；不启动独立工作流。
- search-first：检索渠道为当前仓库、现有测试和 AGI-saber 指定路径；结论为 Extend，扩展现有 extractor/outcome/run 组合，不引入新库或新框架。
- AGI-saber：对照 `internal/application/chat/mem_writer.go`、`mem_stack_test.go`、`ctx_prompt.go` 与记忆架构文档；旧项目证明用户原文可由 LLM 拆分后逐项检查和写入，但其 Go 实现、偏好持久化、KV 结构和多重 inspection 不迁移。
- 目录：复用 `venagent/memory/`、`venagent/agent/`、`interfaces/http/routes/`、`web/src/modules/chat/` 与既有测试；不触发 product-capability，不新增 package 或 Vue module。
- 前端：自然语言显式记忆展示正常发送、生成、assistant 回复与失败/降级结果；只有斜杠命令继续使用 notice-only 表面。

# Open questions

无。用户已对上述共享理解作出明确确认。

# Verification expectations

- pytest 覆盖：自然语言显式记忆创建 run、提取/统一判断/真实 outcome、部分成功、关闭/拒绝/存储失败、自然语言忘记、普通混合陈述异步提取，以及 `/memory` 命令无 run 不回归。
- 现有记忆、API、agent loop、配置、包边界与 owner 隔离测试通过；Ruff 与 Python compileall 通过。
- Vue TypeScript 检查与生产构建通过；前端单元/E2E 覆盖 memory command 与自然对话响应差异。
- PostgreSQL、Neo4j、真实 extractor/embedding 配置可用时，启动真实环境并用浏览器验证自然语言记名、刷新、新 conversation 召回、部分成功和失败降级；不可用项必须如实记录。
