---
wayfinder: ticket
id: final-duties
title: 通读 final/ 产出每文件职责表
labels: [wayfinder:research]
blocked_by: []
status: resolved
claimed_by: captain
---

## Question

`final/`（99 个 .py / 15048 行，AGI-saber 的 Python 移植）里**每个文件承担了什么职责**：文件职责边界、哪些文件是高内聚的正面例子、哪些职责切分值得借鉴。产出物 = `docs/wayfinder/assets/final-职责表.md`（asset 链接），作为 `目录结构梳理定稿` 票的输入。

## Context

用户：「参考 /final 只提炼通用的每文件职责边界，不全面照搬；看 final 一个文件承担哪些作用」。已知结构：`final/internal/{agent(agent.py 1166 + planner.py 294 + graph_runtime.py 353 + memory_writer.py 379 + langgraph/{builder,runtime,state,nodes} + policy/intent_policy 323 + restore 145 + router 62 + subagents 54 + cancel 106 + init_sandbox 97 + status 68 + runtime_governance 93), agentteam(presets/{doc,research,review,writer}+registry+contracts), document(library 75 + parser 166), graph(kgstore 286 + task_graph 134 + extractor 143 + types 62), handler(handler 640), infra(infra 598), llm(llm 369), memory(memory 993 + graph_memory 400 + mem_stack 104 + preference 99), platform(es/kafka/milvus/neo4j/postgres), promptctx(12 文件/1273 行), rag(hybrid 408 + rag 285 + reranker 98 + rewriter 186 + splitter 116), repo(8 文件单层 1101 行, 无 temporary), sandbox(docker 134 + executor 106 + factory 23 + local 113 + types 94 + validator 125), tools(exec_command 91 + mcp_catalog 58 + tavily 79 + tools 359)} + main.py 162 + config.py 401`。对比：venagent 当前 155 py / 24522 行；repo 29 文件双镜像；promptctx 11 文件 533 行（source_recall.py 5 行空壳）。final 的 promptctx 是「简单骨架+实 source」，venagent 是「骨架重的投影框架」——用户喜欢前者（转写方向=把 venagent 真数据装进 final 式 source，丢 ProjectionInputCollector/manifest 框架）。

## Resolution

**RESOLVED**（research 子代理 a65f646e 报告已回落）：产出 `docs/wayfinder/assets/final-职责表.md`（216 行，覆盖 final/ 全部 99 个 .py，程序化核对 99/99 无缺失；未改源码、未动 git）。要点：
- **正面粒度例**：internal/platform（一外部系统一薄封装 + is_real()/close() 降级契约）、internal/sandbox（types→validator→docker/local→factory→executor 五层分离+审计）、internal/promptctx（schema 驱动、一槽位一 source 文件、Protocol 依赖）、internal/agentteam/presets（4 preset 结构对称、契约与注册表分离）、internal/document（domain library 与 parser 分离、PDF 多后端降级）、internal/agent/langgraph（自含运行时 state/builder/runtime/nodes 分文件）、internal/rag（管线阶段一对一文件、set_*() 注入可换组件）、internal/repo（一领域对象一仓储）。
- **负面例**：internal/agent/agent.py（1166 行门面粗，内联 document 工具/RAG/记忆/快照杂务）、internal/handler/handler.py（640 行一文件塞请求模型+全部路由+SSE worker）、internal/repo/ragchunk.py（468 行横切 PG/ES/Milvus 三存储且塞检索/转换）、internal/memory/memory.py（993 行纵向堆叠，Preference 为重复别名）。
- **附注**：final/ 非完全自洽——main.py 引 `apps.api.compat`、platform/postgres.py 引 `venagent.adapters.postgres.schema`，寄生仓库根 src/ 新树。
→ 由 `目录结构梳理定稿` 消费（正面粒度建议＝一外部系统一文件 / 一槽位一 source / 一领域对象一 repo；新目录树据此定文件粒度）。