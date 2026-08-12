# Outcome

将 VenAgent 的后续路线从 M04--M18 的细粒度候选清单，重整为保持“由简至繁”顺序、但每项代表完整产品域的紧凑模块路线。路线必须吸收对 AGI-saber 当前实现的重新审计结论，并与 VenAgent 已完成的 M01--M03 和实际 Python/Vue 架构一致。

# Scope

- 重写 `refactor-roadmap` 的候选模块目录、依赖关系和当前治理状态。
- 重写 VenAgent 模块能力路由矩阵，使基础 intake、专项能力、AGI-saber 对照主题和最小前端检查点对应新模块。
- 仅在编号或相邻模块引用因此失真时，同步更新相邻的 canonical 规格或项目规则。
- 在路线变更中记录 AGI-saber 审计的可采用能力、明确排除项和不能迁移的安全风险。

# Non-goals

- 不实现身份、长期记忆、Neo4j、RAG、工具、MCP、沙箱或子 Agent。
- 不改动 M01--M03 已归档的运行时行为、数据库 schema 或前端聊天契约。
- 不把 AGI-saber 的 Go 包结构、运行期 DDL、表结构、自制 TaskGraph 或不安全图查询迁移到 VenAgent。
- 不恢复已 drop 的 M03A conversation-library。
- 不在本 change 选择具体向量库、图数据库、Embedding provider 或 Mem0 等依赖。

# Acceptance examples

- 路线在 M03 后只保留六个完整产品域模块，并说明各自的产品边界与前置依赖。
- 用户选择不做的画像与偏好不再作为独立未来模块或 UI 路由出现。
- 长期事实、图记忆、生命周期治理和记忆 UI 被归入一个完整记忆系统模块，而不是编号相邻的碎片模块。
- 工具循环、任务计划、可靠恢复、并行和子 Agent 被归入一个完整 Agent 编排模块；其受控工具与最小沙箱由前置的 tool-execution 模块提供。
- 每个新模块有一条路由矩阵记录，明确 AGI-saber 只作行为/风险参考，且不把已发现的跨用户图召回风险带入 VenAgent。
- 每个新模块同时定义后端能力拥有者与前端用户表面；实现该模块时交付最小用户入口和可验证状态，而不是把前端或目录整理延期到平台治理。拥有者不等于预先冻结的目录路径。
- 目录展示必须区分当前已实现树与未来模块的目录决策点；不得把候选路径表示成已承诺或已存在的目录。

# Constraints and invariants

- 模块仍逐个审计、选择、Shape、批准、Build、Verify、Archive；紧凑路线不构成批量实现授权。
- M04 的 `owner_id`、身份、授权和数据删除边界仍是任何用户关联持久数据的前置条件。
- 官方 LangGraph checkpointer 继续只保存 graph state；长期可查询记忆使用 VenAgent 自有领域模型和存储。
- 每个模块仍交付最小 UI/API、安全、测试和可观测性；这些不是最后统一补的欠账。
- 当前前端继续以 `web/src/modules/` 和 `modules/chat/` 为已实现边界；未来模块可扩展既有表面或在 Shape 中按实际用户工作流建立新 feature surface。
- Python 保持 feature-first 的依赖方向：业务用例不依赖具体 adapter，`infra/` 不承载 feature use case，`interfaces/http/` 不承载业务事实。具体 package 路径仅在模块 Shape 后依据现有内聚性、真实复用和依赖方向决定；不得为路线预建空目录、抽象层或 `shared/`。

# Decisions

- 已确认：M01 conversation-context、M02 streaming-run-lifecycle、M03 conversation-persistence 保持完成状态和既有编号。
- 已确认：保持“由简至繁”的路线原则，减少把同一产品域拆成多个连续模块的做法。
- 已确认：用户画像与用户偏好不属于当前目标；M05 user-preferences 不保留为独立模块。
- 已确认：沙箱前置为 Agent 获得真实外部能力前的最小可扩展受控执行框架；后续工具只在同一产品域内按明确授权扩展对应策略与 adapter。
- 已确认：AGI-saber 对照先读取模块路由指定的优先路径；若直接调用、被调用接口、共享数据模型、配置或相关测试表明信息不足，可以按证据扩展查阅范围，并记录扩展原因与实际范围。
- 已确认：前端与目录结构随对应产品模块推进，不另设全局前端或目录重构模块。M06 的能力名为 `tool-execution`，M08 的能力名为 `rag`；这些名称不预先约束 Python 或 Vue 的实际目录路径。沙箱的策略与 adapter 边界将在 M06 Shape 中依据实际工具契约确定。
- 已确认：当模块 Shape 发现需要新增、合并或迁移 Python package、Vue module、共享表面或路由时，调用 ECC `product-capability`，先固化能力约束与最小目录增量；它不是每次模块的固定步骤，也不替代 Comet Native 生命周期。
- 已确认：用户批准 M04 ownership-lifecycle、M05 memory-system、M06 tool-execution、M07 agent-orchestration、M08 rag、M09 platform-governance 的完整模块边界、顺序、前端/目录演进规则和 AGI-saber 对照规则；M06 的最小沙箱先于 M07 首次模型→工具→模型循环。
- 已确认：AGI-saber 是 Go 行为参考；`ecc-rules-pack-python` 只约束 VenAgent 的 Python 实现。
- 推荐的新候选目录：M04 ownership-lifecycle；M05 memory-system；M06 tool-execution；M07 agent-orchestration；M08 rag；M09 platform-governance。

# Open questions

- 无。路线边界、模块顺序、目录演进规则及 AGI-saber 审计规则均已确认。

# Verification expectations

- 验证 canonical 路线、模块路由和所有受影响相邻规格对新编号的引用一致，不保留已废弃的 M05--M18 子模块名称作为当前路线。
- 对照 `venagent/`、`web/`、`pyproject.toml` 和 AGI-saber 源码，确认路线没有把尚未实现的能力描述成当前能力，也没有引入旧项目的跨用户图记忆缺陷。
- 对 Markdown/链接/路线编号运行文本一致性检查；本 change 不运行产品功能测试，因为不改变运行时代码。
