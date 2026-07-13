# Phase1.主agent与运行入口

## 定位
`UnifiedAgent` 是当前 AGI-saber 的主 agent，也是 `main.py` 启动链路里最核心的执行入口。

它不是单纯的子 agent，也不是普通工具封装，而是把路由、记忆、RAG、工具、子代理、快照、取消、PromptContext 和文档链路串起来的系统中枢。

---

## 当前入口链路
| 层级 | 代码位置 | 作用 |
|---|---|---|
| 进程入口 | `final/main.py` | 加载配置、初始化基础设施、构建 `UnifiedAgent`、挂载 HTTP 路由、启动服务 |
| 主 agent | `final/internal/agent/agent.py` | 模式路由、主循环、工具调用、ReAct、记忆收口、快照 |
| 请求路由 | `final/internal/agent/router.py` | `chat / tool / rag / react` 的启发式分派 |
| 图执行 | `final/internal/agent/graph_runtime.py` | 拓扑执行、竞速、重试、取消 |
| 启动恢复 | `final/internal/agent/restore.py` | 长期记忆、聊天记录、RAG chunks、知识图谱挂载 |
| 状态视图 | `final/internal/agent/status.py` | 对外状态聚合 |

---

## UnifiedAgent 当前职责
| 职责 | 当前实现 | Phase 1 目标模块 |
|---|---|---|
| 模式路由 | `_prepare()` + `router.py` | `IntentPolicy` |
| 聊天回答 | `_chat_response()` / `_chat_response_stream()` | `ConversationRuntime` |
| RAG 回答 | `_run_rag_query()` | `RagRuntime` |
| 单工具调用 | `_run_tool_from_set()` | `ToolExecutionBridge` |
| ReAct 任务图 | `_run_react_with_tools()` | `GraphRuntime` + `WorkflowSpec` |
| promptctx 装配 | `_build_prompt_context()` | `PromptContextService` |
| 记忆写入 | `memory_writer.py` + `_finalize()` | `MemoryPipeline` |
| 快照 | `save_snapshot()` / `_save_agent_snapshot()` | `RuntimeGovernance` |
| 取消 | `CancelRegistry` | `RuntimeGovernance` |
| 子代理 | `subagents.py` | `AgentTeam` |
| 文档读写 | `write_document()` / `read_document()` / `ingest_document()` | `DocumentService` |
| 知识图谱挂载 | `restore.py:init_knowledge_graph()` | `KnowledgeGraph` |

---

## 请求生命周期
| 阶段 | 代码路径 | 做了什么 |
|---|---|---|
| prepare | `_prepare()` | 写 STM、写聊天记录、抽取偏好/记忆、决定 mode、构建 promptctx |
| dispatch | `_dispatch_mode()` | 分发到 chat / rag / tool / react |
| finalize | `_finalize()` | 写 assistant 回复、异步记忆抽取、合并、事件发布、计数与快照 |

---

## 现在最像“主 agent”的地方
### 1. 不是 `agentteam`
`agentteam` 负责子 agent 的组织、注册和扩展，不负责主请求链路。

### 2. 不是 `graph_runtime`
`graph_runtime` 只执行任务图，不负责整轮请求的输入准备、上下文装配和收尾。

### 3. 不是 `main.py`
`main.py` 只负责进程级装配和启动，不负责请求级语义。

所以 `UnifiedAgent` 现在承担的是“主 agent + 运行时协调器”的双重角色。

---

## 关键耦合点
| 耦合点 | 当前表现 | 计划中的处理方向 |
|---|---|---|
| 模式路由 | 关键词启发式 + 显式参数 | 抽成独立 `IntentPolicy` |
| 状态管理 | STM/LTM/Preference/TaskMem/ToolState 分散持有 | 收口到显式运行状态对象 |
| 后置副作用 | 记忆抽取、合并、快照散在 finalize | 收口到后置 pipeline |
| 文档工具 | 直接挂在主 agent 上 | 收口到 `DocumentService` 或 MCP tool |
| 知识图谱 | 通过恢复阶段挂载 | 独立 `KnowledgeGraph` 初始化阶段 |

---

## 目前必须保留的行为
- `chat / rag / tool / react` 四种模式都要继续可用
- `process_with_options()` 和 `process_stream_with_options()` 的语义要稳定
- `Response` 的结构不能突然变形
- 取消、快照、异步记忆写入不能丢
- 文档库、RAG、知识图谱、沙箱都必须在主入口里可挂载

---

## 对 Phase 1 的补充要求
| 需要补的点 | 原因 |
|---|---|
| 主 agent 单独成文 | 否则容易在 LangGraph / agentteam 里找不到入口 |
| `IntentPolicy` 单独成文 | 方便把意图到运行模板的选择独立出来 |
| 主入口和主循环拆开 | 方便后续做真正的分层重构 |
| request lifecycle 独立 | 方便把状态、路由、收尾各自替换 |
| 运行时副作用独立 | 避免把记忆、快照、事件发布继续揉在一起 |

---

## 验收标准
- 一眼能找到主 agent 和主入口
- 一眼能找到运行策略层
- 能清楚区分主 agent、图执行器、子 agent 的边界
- 后续重构时可以把 `UnifiedAgent` 逐步拆成多个稳定模块
