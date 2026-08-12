# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-8ba27c7386ceea9d4175c4a1d62ea18d66740d4feefa674b2afc83d2fcf38e32",
    "evidence_refs": [],
    "skipped_reason": "AGENTS.md 按用户决定继续被 Git 忽略；本机文本检查已确认 bundled runtime 命令存在，但无法绑定到 Comet implementation scope。"
  },
  {
    "acceptance_id": "acceptance-a16d129767c59896530e6a368a0319bc5048cdfcc86c1cdb9dd5c9064782e7d2",
    "evidence_refs": [],
    "skipped_reason": "AGENTS.md 按用户决定继续被 Git 忽略；本机检查已确认 /comet 与 resume probe 约束仍存在，但无法绑定到 Comet implementation scope。"
  },
  {
    "acceptance_id": "acceptance-f00bc29b941f1a915bee125918d6c4c31f07f361bd5aa8adcc8bdc83b490fa48",
    "evidence_refs": [],
    "skipped_reason": "AGENTS.md 按用户决定继续被 Git 忽略；本机文本检查已确认 Native Skill 与 runtime 路径存在，但无法绑定到 Comet implementation scope。"
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `rg` 检查固定 Native Skill、runtime、router 与直接命令：通过，匹配 `AGENTS.md` 第 23、27、28、31、36 行。
- PowerShell 精确行检查 managed resume 起止标记与 `comet.resume_probe.v2`：通过，各有且仅有一个管理块边界。
- `git check-ignore -v AGENTS.md`：通过，确认 `.gitignore:21` 继续忽略该文件。
- `git diff --check -- .gitignore`：通过。
- `comet native check document-comet-native-entry`：通过；scope 为空，扫描 0 个文件，receipt 为 `runtime/evidence/check-receipts/1cc54a3fdd881887900d0369e39e13cf632fa1805fe670eb8ba9ac8380daae0d.json`。

# Skipped checks

- 未把 `AGENTS.md` 纳入 Git 或 Comet implementation scope；这是用户明确选择的本机专用行为。
- 未运行项目测试；本 change 仅修改被忽略的本机说明文件，不涉及运行时代码。

# Spec consistency

本机 `AGENTS.md` 已记录固定 Native 入口，同时保留 `/comet` 路由、active change 恢复探针、selection 与阶段边界。没有长期 capability spec 变化。

# Known limitations and risks

`AGENTS.md` 不进入版本历史，其他克隆或工作区不会获得本次说明；Comet scoped check 的通过仅证明空 implementation scope 没有文本问题，不能证明被忽略文件内容。

# Conclusion

在用户明确接受的本机专用与不可版本化限制下，本 change 的本机验证通过，可以归档。
