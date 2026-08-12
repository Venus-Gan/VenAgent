# Outcome

将 VenAgent 的 ECC 使用方式收敛为技术检索、代码可读性、边界与目录层次的轻量辅助，不把 ECC 的完整静态扫描或独立流程设为默认门禁。

# Scope

- 修改 `AGENTS.md` 的“代码编写 Prompt 路由”段落。
- 保留 Comet Native 作为唯一项目生命周期状态机。
- 保留现有架构边界、风险驱动安全检查和项目原生测试要求。
- 将 Ruff、mypy、Bandit、pip-audit、AgentShield 等外部工具改为“已安装且与变更相关时可补充运行”的证据来源。

# Non-goals

- 不安装、配置或强制 CI 使用新的静态检查工具。
- 不删除 `search-first` 在模块技术选型中的研究职责。
- 不修改后端代码、测试、依赖或既有 Comet 归档。

# Acceptance examples

- 普通 Python 变更遵守清晰命名、边界验证、显式错误处理、适度抽象、PEP 8、类型标注与现有架构边界，但不会因未安装外部扫描器而失败。
- Verify 仍运行按风险选择的项目原生测试，并如实记录实际结果、跳过项和剩余风险。
- 身份、MCP、命令执行、文件、凭据、外部网络等高风险变更仍需安全边界复核；扫描工具仅在可用且有价值时补充。

# Constraints and invariants

- Comet 不被 ECC 流程替代，也不创建额外 Plan、TDD、Review 或发布阶段。
- 不把未运行的可选静态工具描述为通过，或把其缺席自动认定为代码缺陷。
- 项目明确的架构不变量优先于通用 ECC 规则。

# Decisions

- ECC 的主要定位是技术检索、技术选型辅助、实现规范与轻量审查，而非引入完整的重型开发流程。
- 用户于 2026-07-25 确认上述轻量治理范围。

# Open questions

无。

# Verification expectations

- 复核更新后的 `AGENTS.md` 明确区分实现规范、项目原生验证、风险驱动安全检查与可选工具。
- 确认规则不再要求因未安装 ECC 外部工具而阻塞普通代码变更。
