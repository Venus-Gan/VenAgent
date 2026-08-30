# ADR-0007: Selector 隐性意图分发

编排层第一步意图判断由 Selector 节点完成，隐性分发三支：ReAct / RAG / 直接回答。意图判断 = 快速规则 + 模型判断组合（参考 AGI-saber 未显式选择时用规则判断天气/时间/搜索/知识库）。无前端开关、无手动模式选择、无独立记忆分支——记忆保持每次 run 自动注入（recall → promptctx → ContextBlock），"明确回忆"档位留记忆模块内。

动机：前端模式开关与手动选模式导致路由脆弱（SuperMew 参考项目的 prompt 约束路由是其 TODO）。

来源：Wayfinder 票 `剩余功能规划` Q7（resolved）。
