# Outcome

对当前 VenAgent 后端运行时代码进行只读 ECC 合规审计，给出可复核、按严重程度排序且带文件行号的修改建议。

# Scope

- 审计 `venagent/`、根目录 `tests/`、`pyproject.toml` 与运行配置中影响当前后端的内容。
- 依据项目规定的 ECC common/Python、Python review、code review、FastAPI review 与 security scan 检查项执行。
- 记录实际执行的静态检查和测试结果。

# Non-goals

- 不修改业务代码、测试、依赖或运行配置。
- 不审计 `final/`，它在 README 中被定义为旧项目功能参考而非当前运行时。
- 不将工作树中用户未提交的迁移文件归因于本次审计。

# Acceptance examples

- 审计结果至少覆盖 Python 代码质量、FastAPI 边界、输入/输出安全和测试可运行性。
- 每项实际问题包含严重度、项目相对路径、精确行号、影响与具体修复方向。
- 没有证据的问题不作为审计 finding 输出。

# Constraints and invariants

- 审计过程仅执行只读命令，保留现有脏工作树中的全部用户改动。
- 当前运行时边界以 `pyproject.toml` 的 `venagent*` 包及 README 的启动命令为准。
- 不在证据或报告中记录任何凭据、连接串或敏感环境变量。

# Decisions

- 当前目标为 `venagent/`，而非 `final/` 旧项目参考目录。
- 输出为审计发现与建议，不自动修复。
- 用户于 2026-07-25 确认上述只读审计范围与不自动修复的约束。

# Open questions

无。

# Verification expectations

- 读取适用的 ECC 规则源文件，并复核相关运行时代码与测试。
- 在可用时运行 `ruff`、Python 测试及安全扫描；不可用的检查如实记录为跳过。
