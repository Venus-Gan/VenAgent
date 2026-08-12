# Outcome

使 README 中的当前运行时文件树与仓库实际结构一致，并让每个一级能力目录及基础设施子目录表达清晰、互不混用的职责。

# Scope

- 仅更新 README 的“目录结构”代码树及其紧随的运行时职责说明。
- 补充当前已存在但未在树中表达的配置、安全、可观测性、HTTP 接口与 Vue 前端路径。
- 更正 `agent/` 的说明，使其不再声明仓库中不存在的 `worker`。

# Non-goals

- 不移动、重命名、新增或删除任何运行时代码、目录或配置。
- 不修改 `final/` 旧项目参考树、README 的其他主题、测试或运行行为。
- 不改变 PostgreSQL 连接池、adapter 装配或 feature-first 架构。

# Acceptance examples

- README 的当前运行时树包含 `venagent/infra/config/`、`venagent/infra/security/`、`venagent/observability.py` 和根 `web/`，且路径在仓库中实际存在。
- `agent/` 说明只列出实际职责，不再出现 `worker`。
- 树后说明明确 `infra/memory/postgresql/` 与 `infra/platform/postgresql/` 是按 feature port 分类的 adapter，并共享 platform runtime 所有的资源。

# Constraints and invariants

- 文档正文使用中文；技术名词、路径和文件名保持原样。
- 文件树只描述当前渐进式运行时；`final/` 继续明确为旧实现与功能参考。
- 仅修改 `README.md` 的目录结构区域及本 change 的 Comet 产物。

# Decisions

- 用户已默认批准本 change 的 Shape、Build 与 Verify，不需要再次询问。
- 采用 feature-first 描述：业务能力目录与 `infra/` adapter 目录分层表达，不混用业务用例和基础设施职责。

# Open questions

无。

# Verification expectations

- 对照 `rg --files venagent web` 检查树中新增路径与真实文件一致。
- 运行针对 README 目录结构块的文本断言，确认关键路径、职责说明和 `worker` 修正。
