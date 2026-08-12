# Outcome

为 VenAgent 增加一套在 Comet Native Build 阶段实际编写代码时触发的 ECC prompt 路由。它必须将 Python 编码规范、测试和审查要求作为实现标准，而不是仅列为可选 Skill 名称。

# Scope

- 在 `AGENTS.md` 中增加代码编写 prompt 路由，明确它属于 Comet Native 的 Build/Verify 内部执行配方，不创建并行生命周期。
- 固化 `ecc-feature-dev` 为新功能、缺陷修复和实质性重构的代码编写入口；其代码库探索、现有实现优先、设计约束、实现和质量复核必须服从已批准的 Comet Shape，不额外要求用户批准。
- 固化 `ecc-rules-pack-common` 与 `ecc-rules-pack-python` 为 VenAgent Python 代码变更的严格实现规则来源，并列出适用于本项目的 Python、FastAPI、测试、安全和代码质量规则。
- 按变更类型定义 `ecc-python-review`、`ecc-fastapi-review`、`ecc-code-review`、`ecc-security-scan` 的使用时机、最低检查要求和不可用时的诚实降级规则。

# Non-goals

- 不复制 ECC prompts、rules 或 agents 到 VenAgent 仓库，也不安装另一份 ECC。
- 不把 prompts 作为脱离 Comet Native 的 Plan、TDD、Review 或发布工作流。
- 不强制每次微小文档或格式改动都运行完整测试、覆盖率或安全扫描。
- 不将 AGI-saber 的 Go 代码纳入 VenAgent Python 编写规范。

# Acceptance examples

- 在修改 `.py` 文件前，执行者能从项目规则得知必须应用 Python/common rule packs，并遵守类型标注、PEP 8、Ruff/格式化、边界验证、显式错误处理和资源管理要求。
- 新功能、缺陷修复或实质重构在 Build 中使用 `ecc-feature-dev` 作为实现配方；它只补充当前 Shape，不能绕过已批准的需求、范围或阶段边界。
- 每次 Python 代码变更在 Verify 前使用 `ecc-python-review` 的检查项；修改 FastAPI 表面时额外使用 `ecc-fastapi-review`；任何代码变更使用 `ecc-code-review` 的通用正确性和质量检查。
- 新增或修改行为时运行对应的 pytest 测试；身份、授权、MCP、命令执行、文件、凭据或外部网络变更额外执行安全检查。
- 本机 prompt、agent、格式器或扫描器不可用时，执行者在主会话作等价检查，并在 Verify 中如实记录可用性、跳过项及风险，不将未运行的检查表述为通过。

# Constraints and invariants

- Comet Native 仍是唯一的生命周期状态机；prompt 只在 Shape 已批准后帮助执行 Build 或 Verify。
- 所有 Python 代码变更遵守 `ecc-rules-pack-python` 覆盖的 common/Python 规则；语言规则与项目明确架构不变量冲突时，以项目不变量为准。
- 当前项目的 Python 业务边界仍为：业务用例不依赖具体 adapter，`infra/` 不承载 feature use case，`interfaces/http/` 不承载业务事实。
- 测试范围按风险和变更范围选择；重点覆盖行为、失败路径和隔离边界，不以全仓覆盖率作为硬门槛。
- FastAPI 专项要求仅在 app/router/HTTP schema/依赖注入/中间件/异常处理等表面改变时触发。

# Decisions

- 已确认：VenAgent 是 Python 项目；Python 编写规范是代码实现标准的一部分，不应仅作为可参考 Skill。
- 已确认：代码编写路由优先采用本机 ECC prompts 与其 rule packs，而不是仅依赖 Skill 名称。
- 已确认：测试由项目原生 pytest 与 Comet Verify 的风险判断驱动；不单列 `ecc-tool-run-tests`，也不把覆盖率 prompt 或全仓 80% 作为硬门槛。
- 推荐：`ecc-feature-dev` 是代码编写主入口；`ecc-rules-pack-common` 与 `ecc-rules-pack-python` 是 Python Build 的规则基线；审查与安全 prompts 按变更类型追加。
- 推荐：对当前未暴露为原生工具的 ECC agent/prompt，按 prompt 的可复核检查项在主会话执行等价步骤；不虚构已调用的 agent。

# Open questions

- 无。用户已确认精简路由：Python rule packs、`ecc-feature-dev`、按变更类型追加审查/安全 prompts，以及由 Comet Verify 驱动的项目原生 pytest。

# Verification expectations

- 检查 `AGENTS.md` 的代码编写路由与既有 Comet 生命周期、固定 intake、模块路由和安全边界不冲突。
- 对规则中的所有 prompt 路径执行本机存在性检查，并验证 Python/FastAPI prompt 与 rule pack 引用准确。
- 对 Markdown 和变更范围运行文本一致性及空白检查；本 change 不修改运行时代码，不运行产品测试。
