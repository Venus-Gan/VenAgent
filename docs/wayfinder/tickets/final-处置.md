---
wayfinder: ticket
id: final-removal
title: final/ 处置（新规范确认后删除）
labels: [wayfinder:task]
blocked_by: []
status: resolved
claimed_by: captain
resolved_comment: 用户两问拍板（活参考处置 = 整删+提炼 hybrid 降级参考；执行时机 = 拍板即执行）。已执行：备份 .backup/final/（435 文件核对一致）→ 删除 final/（NTFS ACL 需 danger-full-access，与 docs-rebuild 先例一致）→ README 488-515 final/ 标注段移除 → 提炼 assets/final-rag-降级参考.md（ADR-0006 活引用改指）。map.md Decisions so far 已同步。
---

## Question

`final/`（99 py / 15048 行）在 `目录结构梳理定稿` 确认新目录/文件代码规范后删除。删除条件：new-directory-tree 已关闭且其决策写明「final/ 职责已提炼完毕、无保留必要」；删除前再扫一遍 final/ 尚未迁移到新文档的参考点（如 promptctx 12 文件精髓已在 `通读-final-产出每文件职责表` 记录）。resolve=删除完成并记录；同时移除 README 458-484 行对 final/ 的「保留为旧项目实现与功能参考」标注。

## Context

用户 Q2e：「参考 final 目录结构与单文件职责，看一个文件承担哪些作用；确认后续实现的目录、文件代码规范后可以删除 final/」。final/ 是历史实现不是运行时（README 已标注）。final/ 曾是被验证的可运行旧版（含 handler 组合根），但当前 venagent 包才是运行事实源。

**前置查证（2025-07，只读）**：
- `目录结构梳理定稿` 已关闭（new-directory-tree resolved），其产物 `assets/新目录树-draft.md` v1.0 对 final/ 仅指路「final/ 目录处置 → final-removal 票」，无保留要求；设计原则 §0 明确「从 final-职责表 216 行提炼，非照搬」→ **职责提炼完毕确认**（final-职责表覆盖 final/ 全部 99 py，程序化核对无缺失）。
- **运行时零引用**：venagent/ 与 tests/ 无任何 `from final` / `import final`（grep 全仓仅 final/tests/test_phase2_orchestration_architecture.py 内部 2 处自引用）。
- **无孤儿树**：final/ 寄生的仓库根 `src/` 树（main.py→apps.api.compat、platform/postgres.py→venagent.adapters.postgres.schema）不存在——其「自洽入口」引用本就是断的。
- **git 状态**：final/ 已跟踪 181 文件（git ls-files），工作树干净（无未提交改动）；`final/config/config.local.yaml` 已被 gitignore（随删无妨）；`.backup/` 已 ignore（可作删除前备份位）。
- **活参考仅 2 处**：ADR-0006（docs/adr/0006-rag-three-way-rrf.md:「逐路降级参照 final/internal/rag/hybrid.py」）与 remaining-plan 票（历史记录）——M08 实现时的降级模式参考；`新目录树-draft.md:55` M07 留位 source_planner 对应 final source_planner（职责已入 final-职责表）。
- 文档引用：README.md:488-504 final/ 标注段（待删）；map.md/assets 各历史引用为 tracker 历史快照（保留不动）。

## Resolution（RESOLVED，2025-07 用户两问拍板后执行）

### 决策（F1-F2）

- **F1 活参考处置**：整目录删除 final/；删除前把 `final/internal/rag/hybrid.py` 的降级模式提炼为 `docs/wayfinder/assets/final-rag-降级参考.md`（asset，M08 实现参考，ADR-0006 引用改指该 asset）；M07 source_planner 参考由 final-职责表覆盖。
- **F2 执行时机**：拍板即执行（与 docs-rebuild 删除 1521 文件先例一致）。

### 执行记录（全部完成）

1. **提炼**：`assets/final-rag-降级参考.md` 已写（hybrid.py 408 行全文读毕后提炼）：HybridStore 模式判定（hybrid/semantic/keyword/unavailable，每次 search 重新判定）、RRF 公式（score(d)=Σ weightᵢ/(k+rankᵢ(d))，sem=cfg.semantic_weight、kw=1-sem、kg=1.0，k 默认 60——注释宣称归一但实现不归一，已标注）、逐路降级链（三路全败→[]；仅 KG→kg_only；Milvus 挂→keyword；ES 挂→semantic）、fetch_k=max(top_k*2,10)、_fetch_* 统一 try/except→_PathHits(ok=False)、候选池 top_k×(4|2) 下限 10、_finalize rerank/截断、search_multi 多查询并行融合、入库扇出（PG→ES→Milvus→KG 后台 best-effort）、对 M08 启示（capability registry 可观测降级 ≠ 静默 warning）。
2. **备份**：`final/` 全量复制至 `.backup/final/`，src=435 = dst=435 文件核对一致（git 已跟踪 181 + 未跟踪 __pycache__/.coverage/.pytest_cache 等；`.backup/` 已被 gitignore）。
3. **删除**：`final/` 目录删除成功（Remove-Item -Recurse，NTFS ACL owner=CodexSandboxOffline，普通权限拒绝后 danger-full-access 一次通过；Test-Path=False 验证）。
4. **README**：488-515 行 final/ 标注段（含「~50 个单元测试文件」过时行）整体移除，依赖方向段直接衔接 License。
5. **ADR-0006**：`docs/adr/0006-rag-three-way-rrf.md:3` 活引用「参照 final/internal/rag/hybrid.py」改指 `docs/wayfinder/assets/final-rag-降级参考.md`（注明 final/ 已删除、git 历史可恢复）。

### 验证（删除后）

- `Test-Path final` = False；`git status --short -- final` 应显示 181 文件 deleted（未提交，工作树变更）。
- 全仓 grep `from final|import final`：venagent/ 与 tests/ 零命中（删除前已核）；remaining-plan 票与 map.md 中的历史引用为 tracker 记录，保留不动。
- 活参考：ADR-0006 已改指 asset；README 无 final/ 残留段。

### 遗留说明

- final/ 完整代码（99 py/15048 行 + 其余 336 文件）可在 git 历史或 `.backup/final/` 恢复；最终删除状态由用户后续提交时确认。
- tests-restructure 票执行阶段 4 的「README tests/ 说明修正」现针对根树 tests/（原「~50 个单元测试文件」行已随 final/ 段删除，README 根树需补 tests/ 说明）。