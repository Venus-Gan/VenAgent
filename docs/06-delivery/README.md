# 交付 (Delivery)

本目录存放面向外部的交付产物。

## 目录结构

```
06-delivery/
├── README.md           ← 本文件
├── changelog.md        ← 变更日志（按版本记录所有面向用户的变化）
└── release-notes/      ← 发布说明（每个版本的正式发布公告）
    ├── v0.1.0.md
    └── v0.2.0.md
```

## changelog.md vs release-notes/

| | changelog.md | release-notes/ |
|------|-------------|----------------|
| **粒度** | 每条变更一行 | 版本级别的总结 |
| **读者** | 开发者 | 用户 / 团队 |
| **格式** | Keep a Changelog 格式 | 叙事性公告 |
| **更新** | 持续追加 | 每次发布写一篇 |

## ECC 流程位置

```
审查 → [交付]
         ↑
      你在这里
```

## 维护约定

- `changelog.md` 采用 [Keep a Changelog](https://keepachangelog.com/) 格式（Added / Changed / Fixed / Removed）
- `release-notes/` 按版本号命名（`v0.1.0.md`、`v0.2.0.md`）
- 发布说明包含：新功能概述、升级注意事项、已知问题
