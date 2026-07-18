# Phase 0 / Sprint 01 计划

## 目标

建立 VenAgent 的安全、行为和设计决策基线，为后续 Phase 1 实现提供可审计的入口。

## 范围

- 完成关键 ADR 的首次落账；
- 扫描当前 refs 与 Git 历史中的凭据命中；
- 清理 tracked 配置与 Compose 中的默认凭据；
- 确认 ignored local 配置路径；
- 检查测试入口、compileall 和可用覆盖率工具；
- 准备 HTTP/SSE/OpenAPI 与核心行为 characterization tests 的任务边界，明确 legacy 伪流式仅作 Phase 0 基线；真流式接口设计和实现属于 Phase 3。

## 明确不做

- 不添加 LangGraph、MCP 或 checkpoint 生产依赖；
- 不启动 Docker Compose 或外部基础设施；
- 不重写 Git 历史、不撤销外部凭据、不推送或创建 PR；
- 不进入 Phase 1 的新目录、Bootstrap 或运行时迁移实现。

## 当前阻塞

- legacy characterization、OpenAPI、当前性能、coverage 基线和共享行为 fixtures 已完成；真流式实现与性能测量不属于 Phase 0。

## 验收

- ADR-001/003/004/007/011/012/013 已存在且被规划引用；
- 当前 tracked 配置不含可直接使用的默认凭据；
- `python -m compileall -q final` 通过；
- 测试和安全门禁结果真实记录，不以工具缺失冒充通过。
