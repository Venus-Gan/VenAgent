# Outcome

为 VenAgent 建立可审计的模块研究与能力路由约定：每个后续模块在 Comet Native Shape 前都能一致地应用通用工程规则、Python 规则和 search-first 研究，并仅在该模块确有旧项目行为可对照时，定向查阅 AGI-saber。

# Scope

- 在 `AGENTS.md` 中记录 Comet 生命周期与模块 intake 的边界、必经输入和前端基线。
- 新增项目内 `venagent-module-router` 参考 Skill 及其 M04--M18 路由矩阵。
- 将已安装的 Codex `search-first` 路径写入路由说明，避免重复安装 ECC 或引用临时 marketplace 缓存。
- 更新项目技术能力索引，显式纳入 ECC common/Python 规则与 AGI-saber 的触发条件。
- 固化前端基础迁移的技术基线和顺序：`skill-orchestration` 归档后先完成独立 `frontend-foundation` change，再进入 M04。

# Non-goals

- 不在本 change 中创建 `web/` 工程、迁移现有页面或修改 FastAPI 的静态资源托管。
- 不实现 M04 或任何后续产品模块。
- 不复制 AGI-saber 源码、表结构或 Go 实现。
- 不把 search-first、ECC 规则或路由器变成与 Comet Native 并行的阶段或状态机。

# Acceptance examples

- 当用户启动 M04 时，路由器给出：通用 ECC 规则、Python 规则、search-first、M04 的安全/API 专项能力，以及需要核对的 AGI-saber 行为主题；不会要求复制其实现。
- 当用户启动 M11 时，路由器给出文档处理和 RAG 相关能力；不会自动选择前端框架。
- 当旧项目没有对应能力时，路由器明确返回“不需要 AGI-saber 对照”，而非机械扫描旧项目。
- 路由规则要求在 Shape 前留下简洁的研究结论（可用性、检索范围、Adopt/Extend/Compose/Build 决定），但 Comet Native 仍是唯一的 Shape、Build、Verify、Archive 状态机。
- M04 的路由显示其前置条件为已归档的 `frontend-foundation`：后者先以 Vue 3、TypeScript、Vite、Pinia 和 Vue Router 等价迁移现有单页聊天体验；M04 本身只增加身份与所有权体验。

# Constraints and invariants

- Comet Native 是唯一项目变更生命周期；不得新增独立 Plan、TDD 或 Review 状态机。
- `search-first` 是 Shape 前的研究输入，不替代用户对完整模块契约的确认。
- ECC common 与 Python 规则是适用于当前 Python 项目的基础约束；它们不应被逐模块重复复制到路由矩阵。
- AGI-saber 仅提供功能、行为和风险事实；VenAgent 的架构、数据模型和实现保持独立。
- 每个模块仍须定义所需的最小 UI/API/测试/安全/可观测性体验。
- 前端源码 SHALL 独立于 Python 包置于仓库根 `web/`；开发期使用 Vite 代理，初期生产构建产物由 FastAPI 托管，以保持同源和单一部署单元。
- `frontend-foundation` SHALL 先保持现有聊天体验等价，不得搭载 M04 身份或所有权功能。

# Decisions

- 采用“Comet Native 选定 change 后、Shape 前完成 intake”的组织方式：先载入基础规则，再执行 search-first，按路由矩阵决定是否查阅 AGI-saber，最后将结论写入 Shape 产物。
- 模块路由采用项目内 Skill 加独立参考矩阵；`AGENTS.md` 只保留长期不变量与入口说明。
- `search-first` 直接引用已安装的 Codex Skill 路径 `D:\AITools\CodeX\skills\search-first\SKILL.md`；不重复安装 ECC，也不把临时 marketplace 缓存当作项目依赖来源。
- 采用 Vue 3 + TypeScript + Vite + Pinia + Vue Router 作为前端基础迁移的技术基线；源码独立、初期部署不独立。
- 在本 change 归档后创建独立 `frontend-foundation` change，完成现有聊天 UI 的等价迁移及浏览器验证；该 change 归档后才允许 M04 进入 Build。

# Open questions

- 已确认：本 change 落地项目内模块路由器、M04--M18 矩阵、ECC common/Python/search-first intake 规则、按需 AGI-saber 行为对照，以及前端基础迁移的技术基线和 `frontend-foundation → M04` 前置顺序；本 change 本身不迁移前端或实现 M04。

# Verification expectations

- 检查 `AGENTS.md`、路由 Skill 与参考矩阵的交叉链接和 M04--M18 覆盖完整性。
- 验证 `D:\AITools\CodeX\skills\search-first\SKILL.md` 可读；路径失效时报告阻塞而不以临时缓存替代。
- 用 M04、M11 和一个无旧项目对应能力的假设请求进行文档级路由验收，并验证 M04 的 `frontend-foundation` 前置条件及前端基线说明。
