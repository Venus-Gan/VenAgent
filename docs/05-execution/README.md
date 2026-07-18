# 执行记录 (Execution)

本目录存放迭代执行过程中的**所有过程记录**——这是整个文档体系中最"动态"的部分。

## 目录结构

```
05-execution/
├── README.md           ← 本文件
└── phase-1/            ← 按 Phase 组织
    ├── sprint-01/      ← 按 Sprint 组织
    │   ├── plan.md     ← Sprint 计划（本次迭代目标）
    │   ├── tdd-report.md ← TDD 执行记录（红→绿→重构 循环）
    │   ├── review.md   ← 代码审查记录
    │   └── retro.md    ← Sprint 回顾（做得好的 / 可改进的）
    ├── sprint-02/
    └── ...
```

## 各文件职责

| 文件 | 用途 | 何时写 |
|------|------|--------|
| `plan.md` | 记录本次 Sprint 要完成的任务、优先级和分工 | Sprint 开始时 |
| `tdd-report.md` | 记录 TDD 循环中的关键决策：测试先写了什么、卡在哪里、重构了哪里 | 开发过程中持续更新 |
| `review.md` | 代码审查发现的问题和修复情况 | Sprint 中后期 |
| `retro.md` | Sprint 回顾：目标达成率、经验教训、改进措施 | Sprint 结束时 |

## 迭代循环

```
Sprint 开始
  └→ plan.md（定目标）
       └→ TDD 循环（写测试→实现→重构）
            └→ review.md（审查代码）
                 └→ retro.md（回顾，产生改进项带入下一个 Sprint）
                      └→ 下一个 Sprint
```

如果 Sprint 中出现返工（审查发现 HIGH 问题需要修复），在当次 Sprint 内记录，或延到下一个 Sprint 的 plan.md 中作为遗留项。

## ECC 流程位置

```
任务卡 → [TDD] → [审查] → 交付
          ↑        ↑
       你在这里
```

## 维护约定

- 按时序追加，不修改历史 Sprint 记录（即使事后发现当时写错了，也在新 Sprint 中纠正）
- 目录按 `phase-X/sprint-NN/` 两层嵌套
- 文件名为固定名称（`plan.md` / `tdd-report.md` / `review.md` / `retro.md`），便于跨 Sprint 对比
