# ADR-0004: 会话与恢复契约

`thread_id=run_id` 仅是持久化适配器映射，不是业务身份。恢复（resume）时重新核验授权与工具版本，版本不兼容标记 `incompatible`；用户重试 = 新 run 新 checkpoint 链，不做历史 checkpoint 分支或时间旅行。快照只记录不自动恢复（AGI-saber 反例修正：任务快照不等于数据库恢复方案）。

来源：Wayfinder 票 `取舍原则复核`、discussions/agent-runtime-context-decisions（已并入重建后 docs）。
