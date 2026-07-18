# 设计 (Design)

本目录是文档体系中内容最丰富的部分，包含三个子模块：

| 设计资产 | 回答的问题 | 生命周期 |
|--------|-----------|---------|
| [VenAgent 重构目标架构](./venagent-refactor-target-architecture.md) | 当前系统目标边界与组件如何协作？ | 随重构 Phase 演进更新 |
| [VenAgent 目标目录层次](./venagent-target-directory-structure.md) | 代码最终放在哪里、目录之间如何依赖？ | 随迁移边界演进更新 |
| [ADR/](./ADR/) | 当初为什么这么决策？有哪些备选方案？ | 只追加，不覆盖 |
| [api/](./api/) | 对外接口的契约是什么？ | 与 API 实现同步更新 |

## SDD（软件设计文档）

当前重构的总体 SDD 为：[VenAgent 重构目标架构](./venagent-refactor-target-architecture.md)，目标代码布局见：[VenAgent 目标目录层次与迁移边界](./venagent-target-directory-structure.md)。后续若单一 Phase 的设计规模需要拆分，再在 `SDD/phase-N/` 下追加专题文档；历史版本移动到 `archive/`，不与当前事实混用。

旧 `docs/SDD/Phase1/` 已确认不再作为历史设计基线保留；当前目标架构、目录设计和路线图是后续实施的唯一规划依据。

## ADR（架构决策记录）

ADR 记录关键架构决策的**背景、选项、结论和后果**。与 SDD 不同，ADR 是历史账本——一旦记录就不再修改，即使后来推翻了，也只追加新的 ADR 并交叉引用，而不覆盖旧的。

格式参考：[ADR/README.md](./ADR/README.md)

## API 契约

对外接口的定义（OpenAPI spec、接口文档等），保持与代码实现同步。

## 维护约定

- 当前总体 SDD 随重构 Phase 演进更新；拆分后的 Phase 专题设计在新 Phase 启动时追加，旧版归档到 `archive/`
- ADR 按 `NNN-短标题.md` 格式编号递增，只追加
- API 文档随代码变更同步更新
