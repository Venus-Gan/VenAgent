# 计划 (Planning)

本目录存放从设计到执行的过渡产物：路线图和任务卡。

## 路线图 (roadmap.md)

当前路线图：[VenAgent 重构路线图](./roadmap.md)。配套全量 backlog 见 [VenAgent 重构任务清单](./venagent-refactor-task-list.md)，最终需求追踪、遗漏、依赖和需用户决策事项见 [重构最终需求追踪矩阵与决策清单](./requirements-traceability.md)。任务涉及目录迁移时，以 [VenAgent 目标目录层次与迁移边界](../03-design/venagent-target-directory-structure.md) 为准。

宏观时间线，按 Phase 组织，标注各阶段的：
- 目标与范围
- 关键里程碑
- 依赖关系
- 当前状态

## 任务卡 (tasks/)

可执行的工作单元，一张卡片对应一个独立的、可验证的工作项。每张任务卡包含：

```markdown
# 任务：提取 IntentPolicy 决策层

- **关联设计**：[VenAgent 重构目标架构](../03-design/venagent-refactor-target-architecture.md)
- **优先级**：P0
- **预估工时**：2d
- **状态**：待开始 / 进行中 / 已完成
- **前置依赖**：无

## 验收标准
- [ ] IntentPolicy 能从 UnifiedAgent._prepare() 中独立出来
- [ ] 路由决策结果结构化、可审计
- [ ] 现有测试全部通过

## TDD 计划
- 先写什么测试：xxx
- 预期覆盖的边界：xxx
```

## 与 SDD 的关系

- 一篇 SDD 文档通常对应多张任务卡
- 任务卡引用来源 SDD 文档
- 任务卡的状态变更不影响 SDD

## ECC 流程位置

```
SDD → [任务卡] → TDD → 审查 → 交付
        ↑
     你在这里
```

## 维护约定

- 任务卡目录按 Phase 组织（`phase-1/`、`phase-2/`…）
- 卡片文件名按优先级 + 序号命名（如 `P0-01-extract-intent-policy.md`）
- 完成后不删除，标记状态为"已完成"并归档
