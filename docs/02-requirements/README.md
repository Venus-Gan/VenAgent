# 需求 (Requirements)

本目录存放产品需求文档（PRD）及相关需求分析。

## 目录结构

```
02-requirements/
├── README.md                      ← 本文件
└── PRD/                           ← 产品需求文档
    └── venagent-refactor.md       ← VenAgent 重构需求（从技术审计+SDD逆向推导）
```

## 什么是 PRD

PRD（Product Requirements Document）回答三个问题：
- **做什么**：功能范围和用户场景
- **为谁做**：目标用户和使用场景
- **为什么**：要解决的问题和预期收益

PRD 是 SDD 的前置输入——先搞清楚"要什么"，再设计"怎么实现"。

## ECC 流程位置

```
调研 → [PRD] → 架构设计(SDD) → 系统设计 → 技术文档 → 任务列表 → TDD → 审查 → 交付
         ↑
      你在这里
```

## 维护约定

- PRD 文件按功能模块或产品版本命名（如 `venagent-v2.md`）
- 废弃的 PRD 版本移动到 `archive/` 子目录
- PRD 经过评审确认后冻结，后续变更走需求变更记录
