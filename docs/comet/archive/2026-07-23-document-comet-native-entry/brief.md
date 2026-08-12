# Outcome

在根目录 `AGENTS.md` 明确记录 VenAgent 当前固定的 Comet Native Skill 与 bundled runtime 位置，使后续执行者无需扫描仓库或重复调用 workflow router 来猜测 Native 永久入口。

# Scope

- 在现有“项目工作流”章节补充 Comet Native 固定入口、runtime、命令参考和 router 的仓库相对路径。
- 说明 PATH 中没有 `comet` CLI 时，Native 命令直接使用 bundled runtime。
- 说明普通 VenAgent Native 工作可以直接加载固定 Skill；只有显式 `/comet` 或 managed resume probe 要求解析入口时才使用 router。

# Non-goals

- 不修改 Comet 管理的 `<comet-ambient-resume>` 块。
- 不修改 `.comet/config.yaml`、Skill、runtime、hook 或任何项目实现。
- 不绕过 active change 恢复探针、selection、Shape/Build/Verify/Archive 阶段或 Guard。

# Acceptance examples

- 后续执行者只读 `AGENTS.md` 即可定位 `.agents/skills/comet-native/SKILL.md` 与 `.agents/skills/comet-native/scripts/comet-native-runtime.mjs`。
- PATH 缺少 `comet` 时，执行者可直接构造 `node .agents/skills/comet-native/scripts/comet-native-runtime.mjs <command> ...`，无需先扫描或猜测 runtime。
- 用户明确调用 `/comet` 或恢复探针返回其他入口要求时，仍遵循受管理的路由契约。

# Constraints and invariants

- 只编辑 `AGENTS.md` managed block 之外的说明文字。
- 路径使用仓库相对形式，保持项目移动后可用。
- 新说明不得与 Comet Skill 或 managed resume contract 冲突。
- 保留 `.gitignore` 对 `AGENTS.md` 的忽略规则；该说明作为本机项目规则使用，不承诺进入 Git 版本历史。

# Decisions

- 用户明确要求把 Comet 具体位置写入 agent 规则，减少每次重复路由。
- 实际文件名采用仓库已有的根目录 `AGENTS.md`，不另建重复的 `agent.md`。
- 当前 `.comet/config.yaml` 唯一启用 `native`；固定入口说明以此仓库事实为依据。
- 用户选择保留 `AGENTS.md` 的忽略规则，并明确接受该文件无法进入 Git implementation scope、只能进行本机验证的限制。

# Open questions

- 无阻塞问题。

# Verification expectations

- 使用文本搜索证明 Skill、runtime、router 与命令参考路径均已记录。
- 确认 managed resume block 内容未被修改。
- 对可跟踪范围运行 `git diff --check`，并在验证报告中明确记录 `AGENTS.md` 被忽略、无法由 Git scope 或 Comet scoped text check 完整覆盖。
