# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-105108d7b18db682741ecadddeb6e678d6447107ae6e4a8b98ccd7d9475b8560",
    "evidence_refs": [
      "AGENTS.md"
    ]
  },
  {
    "acceptance_id": "acceptance-7ce5afcc36f45abc59e17bff6dca28fd2a62732dfbf4cc6d5c9af3c05caf2d49",
    "evidence_refs": [
      "AGENTS.md"
    ]
  },
  {
    "acceptance_id": "acceptance-9dc1f66fd7ecbeebd554000f7c23629ed5f961719ef667a9bb439a94a6ec9de3",
    "evidence_refs": [
      "AGENTS.md"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- 已人工复核 `AGENTS.md` 的“代码编写 Prompt 路由”段落。
- 已运行 `git diff --check -- AGENTS.md`，未发现空白错误。
- 已确认该段落保留 Comet Native 生命周期、项目原生测试、架构边界和高风险安全复核。
- 已确认外部静态工具被表述为“已安装且与风险相关时的补充证据”，而非默认门禁。

# Skipped checks

- 本 change 只调整项目治理说明，未修改运行时代码、依赖或测试，因此未运行后端测试。
- 未运行 Ruff、mypy、Bandit、pip-audit 或 AgentShield；更新后的规则不将这些工具作为默认门槛。

# Spec consistency

更新后的规则将 ECC 限定为技术检索、技术选型、实现规范和针对性审查，且不创建额外生命周期阶段。风险驱动的安全边界复核和项目原生测试仍被保留。

# Known limitations and risks

`AGENTS.md` 被 Git 忽略，因此不在本次 implementation scope 的 Git 快照中。用户已明确接受该限制；该文件在当前工作区生效，但其变更不由本次 archive 的 scope 追踪。

# Conclusion

ECC 治理已收敛为轻量使用方式；未安装的外部静态工具不再自动构成普通代码变更的阻塞条件。
