# 模块研究与能力路由

## 目标

VenAgent SHALL 为后续模块提供统一、可审计的研究 intake，使模块在进入 Comet Native Shape 前，能够获得与当前 Python/LangGraph 项目相符的工程约束、既有实现检索结论和必要的 AGI-saber 行为事实。

## 生命周期边界

- Comet Native SHALL 继续是 VenAgent 项目变更唯一的 Shape、Build、Verify、Archive 生命周期。
- 创建或选择 Native change 后，模块 SHALL 在 Shape 完整定稿前完成 intake；intake 的结论 SHALL 被摘要写入该 change 的 Shape 产物。
- Intake SHALL 不创建独立的项目阶段、approval、状态文件或并行工作流。
- Intake 结论不得替代用户对模块完整契约的明确确认。

## 基础 intake

每个模块 SHALL：

1. 应用 ECC common 的通用代码质量、可维护性和错误处理约束。
2. 对 Python 实现应用 ECC Python 规则。
3. 按 `search-first` 的可用性预检、仓库检索、相关注册表/官方资料/MCP/技能检索和 Adopt/Extend/Compose/Build 决定记录研究结论。
4. 记录不可用的检索渠道，不得把未检索写成“未找到”。

项目不 SHALL 在模块路由矩阵中复制 ECC 规则正文；矩阵只引用其角色和触发条件。

## AGI-saber 行为对照

- 路由器 SHALL 仅在矩阵为当前模块声明了对照主题时要求查阅 AGI-saber。
- 对照 SHALL 覆盖相关的用户可见行为、接口语义、依赖、测试和已知风险。
- 对照 SHALL 先读取矩阵声明的优先路径；直接调用、被调用接口、共享数据模型、配置或相关测试不足时，可以扩大到最小必要范围，并在 Shape 中记录原因和实际范围。
- AGI-saber 的 Go 实现、数据库表结构和内部架构不 SHALL 自动成为 VenAgent 的实现方案。
- 没有对应主题的模块 SHALL 明确记录无需旧项目对照。

## 模块路由器

项目 SHALL 提供 `.agents/skills/venagent-module-router/SKILL.md` 及一份独立的 M04--M09 矩阵。对一个模块请求，路由器 SHALL 输出：

- 固定基础 intake；
- 与模块相关的专项能力；
- 是否需要 AGI-saber 对照及确切主题；
- 必须带入 Shape 的研究结论；
- 与前端有关的用户状态检查点和前端前置条件。
- AGI-saber 的优先路径、实际扩展范围与理由。
- 目录是否触发 `product-capability`，以及最小目录增量与明确不创建项。

路由器不 SHALL 直接实现产品功能或改变 Comet phase。

## 前端基础迁移顺序

- 项目 SHALL 把 Vue 3、TypeScript、Vite、Pinia 和 Vue Router 作为前端基础迁移的技术基线。
- 前端源代码 SHALL 位于仓库根 `web/`，与 `venagent/` Python 包保持独立边界。
- 开发期 SHALL 由 Vite 代理 API 和健康检查请求；初期生产构建产物 SHALL 由 FastAPI 托管，以保持同源访问和单一部署单元。
- 当前单文件聊天页面的迁移 SHALL 通过独立 `frontend-foundation` Native change 执行，不得作为 M04 的附带重构。
- `frontend-foundation` SHALL 在不添加身份或所有权功能的前提下，保留现有的会话创建/删除、SSE 流式、取消、重试、本地记录、持久化可用性或降级说明、旧会话导入等行为，并提供浏览器验证。
- `frontend-foundation` 归档 SHALL 是 M04 进入 Build 的前置条件。M04 及之后的模块 SHALL 各自在对应前端模块中实现自己的最小用户体验。

## search-first 接入

- 路由说明 SHALL 直接引用当前 Codex 已安装的 `search-first`：`D:\AITools\CodeX\skills\search-first\SKILL.md`。
- 项目不 SHALL 为使用该 Skill 重复安装 ECC，也不 SHALL 回退到临时 marketplace 缓存。
- 该路径不可读时，模块 SHALL 报告阻塞；不得把未执行的 search-first 写成已经完成。

## 验收

- M04 的路由应包含基础 intake、身份/授权/API 安全专项能力及 AGI-saber 的健康检查、降级、身份隔离等行为主题，并声明 `frontend-foundation` 为进入 Build 前置条件。
- M08 的路由应包含基础 intake、文档解析/RAG 专项能力；无需自动选择前端框架。
- 对矩阵未声明旧项目对应主题的请求，路由应明确返回无需 AGI-saber 对照。
- `AGENTS.md`、路由器和矩阵不得把外部能力描述为与 Native 并行的工作流，且不应含临时或机器专属绝对路径。
