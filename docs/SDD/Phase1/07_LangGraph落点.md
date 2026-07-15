# Phase1.LangGraph落点

## 目的
把原项目中最适合交给 LangGraph 收口的逻辑单独拎出来，减少主流程里的手写分支、线程编排和隐式状态。

---

## 总览
| 落点 | 原始问题 | LangGraph 收益 |
|---|---|---|
| 请求级状态 | 状态分散在多个对象里 | 用一个显式 `State` 贯穿单次任务生命周期 |
| 路由判断 | `if/else` 分支越来越多 | 用 conditional edges 代替手写分支 |
| Planner | 计划和执行耦合 | Planner 只产出结构化计划，执行交给 runtime |
| 并行执行 | 线程、Event、join 手写控制 | 用 `Send` / 子图表达 fan-out / join |
| 子代理流水线 | 子代理执行仍然手写调度 | 用 subgraph / agentteam 承接 |
| 失败重试与恢复 | 恢复链分散 | 用 checkpoint / interrupt 统一恢复态 |
| 记忆写入 | 后置副作用触发点散 | 作为固定后置节点或子图处理 |
| 状态聚合 | Response 和 Result 重复维护 | 用 reducer / 汇总节点显式合并 |

### 1. 请求级状态：用 `State` 收口
| 适合收口的内容 | 说明 |
|---|---|
| 当前 query / message | 单轮输入 |
| 路由结果 | 下一跳决策 |
| Planner 输出 | 结构化计划 |
| 已执行节点与中间结果 | 运行过程痕迹 |
| tool 调用记录 | 工具使用历史 |
| 任务是否中断 | 中断标志 |
| 最终 response | 最终输出 |

### 2. 路由判断：用 conditional edges 替代手写分支
| 适合替换的逻辑 | 说明 |
|---|---|
| `need_tool` | 工具分支 |
| `need_rag` | 检索分支 |
| `need_react` | ReAct 分支 |
| `detect_tool` | 工具识别 |

### 3. Planner：用 planner node 产出结构化计划
| 项目 | 说明 |
|---|---|
| 保留逻辑 | `llm_plan_graph`, `rule_plan_nodes`, `llm_plan_steps` |
| 当前问题 | 计划和执行仍通过自定义结构耦合 |
| LangGraph 收益 | 计划先生成，再交由 runtime 执行，可记录可回放 |

### 4. 并行执行：用 `Send` / 子图替代手写线程编排
| 当前实现 | 问题 |
|---|---|
| `GraphRuntime._execute_group` | 并发控制分散 |
| `GraphRuntime._race_group` | 竞速逻辑难维护 |
| 拓扑层级并行 | 依赖关系不够显式 |
| race group 竞速 | 成功/失败路径混杂 |

### 5. 子代理流水线：用 subgraphs / agentteam 统一承接
| 适合替换的逻辑 | 说明 |
|---|---|
| `NodeType.SUBAGENT` | 子代理节点 |
| `GraphRuntime._execute_subagent_node` | 手写调度 |
| `register_builtin_subagents` | 固定 agent 注册 |

### 6. 失败重试与恢复：用 checkpoint / interrupt 替代自研恢复链
| 当前问题 | LangGraph 收益 |
|---|---|
| 启动恢复、执行快照、自定义重试分散 | 图执行态统一保存 |
| 业务态和执行态混在一起 | 中断后可从 checkpoint 恢复 |
| 恢复链难以审计 | 恢复点更清晰 |

### 7. 记忆写入：用 post-node / side-effect node 承接
| 保留逻辑 | 建议收口方式 |
|---|---|
| `async_update_memory` | 固定后置节点 |
| `extract_memory_from_reply` | 后置处理 |
| `maybe_consolidate_memory` | 子图或 side-effect node |

### 8. 状态聚合：用 reducer / 汇总节点替代手工汇总
| 当前对象 | 问题 |
|---|---|
| `Response` | 拼装逻辑散 |
| `GraphResult` | 汇总规则重复 |
| `TaskGraph` | 状态字段多且易漏更 |

### 9. promptctx + Skill 集成：让 Skill 成为上下文来源之一
| 项目 | 约定 |
|---|---|
| `promptctx` | 上下文装配层 |
| `Skill` | 操作型上下文来源 |
| 不负责 | Skill 执行、调度、编排 |

### 10. Skill 的调用与发现边界
| 能力 | 做法 |
|---|---|
| 命令唤起 | 显式指定 skill |
| 自然语言唤起 | Resolver / Planner 识别 |
| LLM 自主发现 | 注入精简 SkillCatalog |

### 简短结论
LangGraph 最适合收口的是：
- 路由
- 状态
- 并行
- 子代理
- 恢复
- 后置副作用

而最该保留为 VenAgent 核心资产的是：
- Planner 生成任务图的逻辑
- 任务图的业务语义
- RAG / memory / document 的底层实现
