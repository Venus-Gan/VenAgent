---
wayfinder: ticket
id: docs-rebuild
title: docs 重建（备份清空 + CONTEXT.md/ADR/matt 文档）与 AGENTS.md/CLAUDE.md 改造
labels: [wayfinder:task]
blocked_by: []
status: resolved
claimed_by: captain
resolved_comment: 用户四批 14 项逐块拍板后结案（真实人交互完成）。执行：.backup/ 备份 1521 文件并清空旧 docs → 新建 CONTEXT.md + docs/adr/ 7 条 + docs/roadmap.md + docs/reference/agi-saber-design-reference.md（重写）→ AGENTS.md 精简重写（writing-for-agents）→ README 目录树段以新目录树定稿改写 → 删除 CLAUDE.md/.claude/.agents comet 技能/.comet（保留 venagent-module-router）。docs/wayfinder/ 原地保留。

## Question

使 `docs/` 成为唯一权威文档，并改造智能体入口规则：
1. **旧 docs 整体打包备份 → 清空**（保留 `docs/wayfinder/`——map/tickets 属于新文档一部分，不得删；`docs/documentation-language.md` 先评估再处置）。
2. **按 Wayfinder 规则重建新文档**：CONTEXT.md（术语表，domain-modeling）→ docs/adr/（难反转决策，取自已关闭票 `取舍原则复核` + 后续票：repo 镜像去留、路线 M06→M08→M07、thread_id=run_id 仅映射、执行权威归 M06、**两层工具限制取消**（每轮绑 tools、M06 内稳定错误拒绝）、恢复重核授权/版本不兼容→incompatible 等）→ `目录结构梳理定稿` 产物 + `剩余功能规划` 产物。
3. **CLAUDE.md 连同 claude code 相关文件删除**（先盘点仓库 `./claude*` / `.claude/`；CLAUDE.md 引用的 docs/03-design/* 已不存在=死引用，删除顺带消除）。
4. **AGENTS.md 改造**（writing-for-agents）：去掉 Comet/ECC 相关内容（含 `<comet-ambient-resume>` 托管块、「项目工作流」Comet Native 章节、代码编写 Prompt 路由的 ECC 段），**只保留 langchain/langgraph 相关内容并带路径**（保留/更新「LangChain 与 LangGraph 技术索引」表 + Codex 能力路径），加 matt-pocock-skills（wayfinder/grilling/prototype/research/domain-modeling）指引 + 中文回复要求。
5. 全部完成后确认并清理临时内容。

## Context

用户 Q2d 原话要义：「CLAUDE.md 连同 claude code 相关文件删除；AGENTS.md 改造=去 Comet+ECC 相关内容（决定使用 matt=matt-pocock-skills），只留 langchain/langgraph 相关内容并带路径以便找到并调用相关 skill；docs 不能全面相信、要带批判眼光看；最终目标=清空 docs 生成 matt 文档、以后只使用 matt 文档」。任务目标步骤 2：旧 docs 打包备份→清空→严格按 Wayfinder 生成新文档→专业客观重审旧功能实现与目标→docs 成为唯一、权威文档依据。现状（2025 盘点）：docs/ 顶层仅 documentation-language.md + 3 目录：comet/（1542 项=archive/ 历史 change 归档（brief/spec/audit/roadmap/verification/runtime 证据 json）+runtime/transactions/（事务+staged spec+backups）+specs/（当前 spec：real-llm-adapter、llm-runtime-configuration、configuration-management、conversation-context 等））、discussions/（4 篇：agent-runtime-context-decisions、agi-saber-design-reference、m06-decisions-draft、m07-decisions-draft）、wayfinder/（tracker 本体保留）。docs/03-design/* 不存在（glob 报目录缺失）→ CLAUDE.md 死引用佐证。仓库根：.agents/skills/（comet/comet-native/comet-any 三技能+venagent-module-router）、.claude/（skills 三副本+rules/comet-workflow-guard.md）、.comet/config.yaml；AGENTS.md 现含 comet-ambient-resume 托管块 + Comet Native 项目工作流 + ECC 路由 + LL/LG 技术索引表（保留核心）。

## Resolution

**RESOLVED（2025 结案）**。用户逐块拍板四批 14 项后结案；备份与清空动作已执行（**先备份再动**）；AGENTS.md 修改用 writing-for-agents 规范。

**P1 备份**：仓库内 `.backup/`（gitignore 新增条目）目录复制 docs/comet（1542 项）+ docs/discussions（4 篇）+ docs/documentation-language.md → 验证文件数一致 → 清空这三处；docs/wayfinder/ 原地保留不动。
**P2 旧内容处置**：documentation-language.md 归档不迁入；comet/specs 全部随备份归档；discussions 4 篇**重写为 matt 文档**：决策类内容提炼入 ADR（thread_id=run_id 仅映射、执行权威归 M06 等），agi-saber-design-reference **重写**为 `docs/reference/agi-saber-design-reference.md`（行为参考非迁移模板），m06/m07-decisions-draft 结论已入 remaining-plan 票不再单列。
**P3 新 docs 顶层结构**（确认草案）：仓库根 `CONTEXT.md`（概述+术语表+导航，domain-modeling 规范）+ `docs/adr/`（初始 7 条：repo 单层化与降级语义 / 新目录树与文件归位 / 执行权威归 M06+工具限制语义 / 会话与恢复契约 / 编排正交分层 / RAG 三路 RRF / Selector 隐性分发）+ `docs/roadmap.md`（remaining-plan 正文独立落位）+ `docs/reference/` + `docs/wayfinder/`（tracker 保留）。
**P4 AGENTS.md 改造**（writing-for-agents）：新结构=中文回复要求 + LL/LG 技术索引表（带路径）+ matt skills 指引（wayfinder/grilling/prototype/research/domain-modeling/writing-for-agents）+ 新 docs 导航 + 安全边界精简；删除 comet-ambient-resume 托管块 / Comet Native 工作流 / 模块路由 / ECC 路由 / Codex 能力表。
**P5 删除范围**：CLAUDE.md + `.claude/` + `.agents/`（comet 三技能）+ `.comet/` 删除；**保留 `.agents/skills/venagent-module-router`**（未来模块对齐研究用）；三者均在 .gitignore，纯本地清理。
**P6 README**：目录树段（307-486）改写为新目录树（源=新目录树-draft.md 定稿）；去 temporary 段；其余段保留并修过时处。