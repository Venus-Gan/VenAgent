# VenAgent 文档索引

本目录按照 **ECC 开发工作流** 的完整产物链路组织，从上到下对应从需求到交付的全过程。

## 目录导航

| 目录 | 对应阶段 | 回答的问题 | 关键产物 |
|------|---------|-----------|---------|
| [01-research/](./01-research/) | 调研 | 现状如何？有哪些选择？ | 技术审计、技术选型评估 |
| [02-requirements/](./02-requirements/) | 需求 | 做什么？为谁做？ | PRD（产品需求文档） |
| [03-design/](./03-design/) | 设计 | 怎么做？架构长什么样？ | SDD（软件设计文档）、ADR（架构决策记录）、API 契约 |
| [04-planning/](./04-planning/) | 计划 | 怎么拆？先做什么？ | 路线图、任务卡 |
| [05-execution/](./05-execution/) | 执行 | 实际怎么做的？结果如何？ | Sprint 计划、TDD 报告、审查记录、回顾 |
| [06-delivery/](./06-delivery/) | 交付 | 交付了什么？ | 变更日志、发布说明 |

## ECC 工作流与文档映射

```
调研 ──→ PRD ──→ SDD ──→ 任务卡 ──→ TDD ──→ 审查 ──→ 交付
 │         │        │         │         │        │        │
 │         │        │         │         │        │        └── 06-delivery/
 │         │        │         │         │        └── 05-execution/ (审查记录)
 │         │        │         │         └── 05-execution/ (TDD 报告)
 │         │        │         └── 04-planning/ (任务卡)
 │         │        └── 03-design/ (SDD + ADR)
 │         └── 02-requirements/ (PRD)
 └── 01-research/
```

## 快速入口

| 我想… | 先看 |
|-------|------|
| 了解项目整体目标架构 | [03-design/venagent-refactor-target-architecture.md](./03-design/venagent-refactor-target-architecture.md) |
| 查看重构后的目录层次与迁移映射 | [03-design/venagent-target-directory-structure.md](./03-design/venagent-target-directory-structure.md) |
| 了解重构的背景和当前差距 | [01-research/technical-audit.md](./01-research/technical-audit.md) |
| 了解重构阶段与门禁 | [04-planning/roadmap.md](./04-planning/roadmap.md) |
| 查看最终需求矩阵、依赖和待决策项 | [04-planning/requirements-traceability.md](./04-planning/requirements-traceability.md) |
| 查看全量重构任务清单 | [04-planning/venagent-refactor-task-list.md](./04-planning/venagent-refactor-task-list.md) |
| 查看某个 Sprint 的执行记录 | [05-execution/](./05-execution/) |
| 查看关键架构决策 | [03-design/ADR/](./03-design/ADR/) |

## 维护约定

- **稳定资产**（01～03）随 Phase 演进更新，旧版本归档到各目录的 `archive/` 子目录
- **半稳定资产**（04）随项目进展持续更新任务状态
- **过程资产**（05）按时序追加，不修改历史记录
- **交付资产**（06）按版本号递增，不做覆盖
- 文件命名统一使用英文 slug（小写 + 连字符），便于跨平台访问
- ADR 只追加不覆盖，编号递增
