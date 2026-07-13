# bootstrap 与 config 方案

## 配置分工
| 来源 | 职责 | 是否提交 |
|---|---|---|
| `config.yaml` | 非敏感默认值、功能开关、结构化参数 | 是 |
| `config.local.yaml` | 本机临时覆盖、调试参数、路径覆盖 | 否 |
| `.env` | 密钥与私有运行时变量 | 否 |

---

## 配置分组
| 分组 | 内容 |
|---|---|
| `runtime` | env、server.port、log.level、cors、feature flags |
| `providers` | llm、embedding |
| `datastores` | postgres、milvus、elasticsearch、neo4j、kafka |
| `agent` | maxRetries、retryDelayMs、stepTimeoutMs、maxParallel、raceTimeoutMs、enableRacing |
| `rag` | chunkSize、chunkOverlap、topK、rrfConstantK、semanticWeight、enableHybridSearch、rewrite、rerank |
| `memory` | shortTermMaxTurns、longTermTopK、consolidation |
| `mcp` | fetch、未来其他 MCP server |
| `skills` | autoLoad、defaultSkills、skillCatalogLimit、skillDirs |
| `prompt` | globalBudget、modeSchemas、slotBudgets |
| `sandbox` | enabled、backend、image、timeout、资源限制、allowlist |
| `security` | maxCommandLength、allowlistMode、allowlist |
| `paths` | projectRoot、dataDir、cacheDir、frontendDir |

---

## 代码现状与目标差异
| 主题 | 代码现状 | Phase 1 目标 |
|---|---|---|
| 配置加载 | `default_config()` 目前优先 `config.local.yaml`，再 `config.yaml`，没有 `.env` 合并 | 由 bootstrap 统一合并 `.env`、环境变量和本机覆盖 |
| 搜索配置 | 仍有 `search_api_key` / `search_api_url` | 改成 `fetch MCP`，删掉 Tavily 配置位 |
| 配置来源 | 主要是 YAML | YAML + `.env` + env vars + 启动参数 |
| 装配层 | 目前配置和初始化逻辑部分散落在 `main.py` / `config.py` | 统一收口到 bootstrap 阶段 |

---

## 加载顺序
| 顺序 | 步骤 |
|---|---|
| 1 | 代码默认值 |
| 2 | `config.yaml` |
| 3 | `config.local.yaml` |
| 4 | `.env` |
| 5 | 进程环境变量 |
| 6 | 启动参数覆盖 |
| 7 | 校验和派生值计算 |
| 8 | 初始化外部依赖 |

> 注：上面是 Phase 1 目标顺序，不是当前实现现状。当前代码仍偏向 YAML-only 读取。

---

## bootstrap 分层
| 阶段 | 职责 |
|---|---|
| ConfigBootstrap | 加载配置、合并覆盖、校验字段、产出 AppConfig |
| InfraBootstrap | 初始化 PostgreSQL / Milvus / ES / Neo4j / Kafka，并处理降级 |
| ToolBootstrap | 初始化 MCP tool adapters，挂载 fetch MCP、rag、memory、document、exec_command |
| PromptBootstrap | 构建 promptctx，装配 IntentPolicy / execution_profile / recall / taskmem / toolstate / skill |
| SkillBootstrap | 扫描 skill、构建 SkillRegistry、生成 SkillCatalog |
| AgentBootstrap | 初始化 agentteam、LangGraph graphs、RuntimeGovernance |
| WebBootstrap | 挂载 HTTP 路由，不碰核心装配逻辑 |

---

## 失败策略
| 场景 | 策略 |
|---|---|
| 配置加载失败 | 启动失败并给出明确错误 |
| 单个基础设施失败 | 按能力降级 |
| MCP / skill / graph 初始化失败 | 记录错误并按 feature flag 决定是否继续 |
| HTTP 路由挂载失败 | 启动失败 |

---

## 收口原则
- `config.yaml` 只管默认结构化配置
- `.env` 只管秘密
- `config.local.yaml` 只管本机覆盖
- 启动入口先加载 `.env`，再构建配置对象
- `config.py` 负责统一校验和字段映射

---

## 对 Phase 1 的补充要求
| 需要补的点 | 原因 |
|---|---|
| 明确区分“当前实现”与“目标加载顺序” | 避免后续实现误以为 env 已经接上 |
| 配置加载与启动装配分层 | 方便把 bootstrap 拆成可测试单元 |
| Tavily 配置位清理 | 这是已决定的方向 |

---

## 验收标准
- 配置来源和加载优先级可解释
- bootstrap 每一层职责单一
- 当前实现与目标实现的差异清楚写在计划里
