# AGI-saber 设计思路总结

> 来源：语雀「AGI-Core」知识库 → 主打项目 → AGI-saber → **面试🚀计划** 子树（共 21 篇文档，含分组父节点）。
> 知识库地址：https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber
> 本文为该子树全部文档的归纳整理，供 VenAgent 重构参考。生成日期：2026-08-29。

---

## 一、项目定位与整体架构

AGI-saber 是一个**面向个人与企业的办公智能体系统**，融合 RAG、三层记忆、知识图谱、沙箱执行与可恢复执行流，支持多轮对话、知识检索、工具调用与复杂推理。

**多阶段智能体核心**：支持四种智能体模式并自动路由，优先级为：

```
ReAct 复合推理 > 单工具调用 > RAG 检索 > 纯对话
```

**工程分层**（RAG 模块文档中明确）：

- HTTP 接口层
- 应用层（application/chat）：Agent 编排、路由决策、工具注册
- 领域层（domain）：RAG、记忆等核心逻辑（如 `internal/domain/rag`）
- 基础设施层（infrastructure）：Milvus / ES / Neo4j / PG / Kafka 等适配

**高可用哲学**：PostgreSQL 是唯一的"事实真相源（source of truth）"，Milvus / ES / Neo4j 都只是它的派生索引，丢了可从 PG 重建；所有基础设施均为可选，连接失败自动降级为内存模式，不影响启动。PG 不可用时 RAG 直接 `mode=unavailable`——没有事实源就玩不下去。

**沙箱执行**：Docker / Local / Mock 三种后端，资源限制（CPU / 内存 / PID / 网络 / 只读文件系统）+ 命令白名单校验。

---

## 二、RAG 检索设计

### 2.1 RAG 解决什么问题

- 大模型知识过时：参数在训练时固化，公司内部文档、最新代码、实时数据模型都不知道。
- RAG 可以动态检索最新知识，**不需要重新训练**（微调成本大、效果像开盲盒）。

### 2.2 数据摄入（Ingest）

**Markdown 清洗的六条固定规则**（核心目标："保留对检索有价值的信息，去掉会污染 embedding 的噪声"）：

1. 删除无意义 Markdown 噪声（不具备语义价值、污染向量表示）
2. 保留标题层级结构（标题层级本身就是语义结构，不 flatten 成纯文本）
3. 保留代码块（技术知识库里的函数名 / API 名 / 错误码是高价值信号）
4. 保留列表结构（列表本身表示语义关系）
5. 表格结构规范化（避免表格塌陷成乱码、embedding 丢失字段关系）
6. 去重 Deduplication（避免 retrieval 重复召回、context 冗余污染）

**PDF 处理流程**：

- 通过 Content-Type + 扩展名双信号识别 PDF
- 解析优先级：pdfplumber（Python）→ pdftotext（PATH）→ Go fallback（ledongthuc/pdf）
- 文本归一化：统一换行、去空字节和软连字符、修复断行连字符（如 `RE-\nWARDS`）、合并重复空格、压缩空行
- 可提取文本太少时返回 `needs_ocr: true`，避免把扫描版 PDF 当有效知识入库
- **Engine.Loaded 由实际成功索引数量决定**——解析成功但索引失败不会误报 RAG 已加载

### 2.3 切片策略（small-to-big 父子块）

| 策略 | 要点 |
|---|---|
| Header-aware Chunking | 优先按标题层级切分，topic 集中、precision 高 |
| Recursive Split | 超长 section 按 段落→句号→逗号→空格→字符 **语义强度递归降级** |
| Code-aware Chunking | 成对 ``` 代码块作为**原子单元**，再长也不切 |
| Small-overlap | 仅保留少量 overlap，避免重复召回与 embedding 冗余 |
| Neighbor Expansion | 命中后自动补充前后 chunk，恢复章节连续语义 |
| Parent-Child Chunking | 子块（~200 字符）用于检索，父块（~800 字符）用于生成 |

- 父块 = 子块的 4 倍（经验折中值），overlap 同比例加倍。
- **为什么不硬切**：把"市内 200 元跨省 500 元"从中间撕开，LLM 会以为补贴只到市内——这是硬切的语义破坏。
- **为什么父块不向量化**：800 字讲三件事，向量是三件事的"语义平均"，问 A 时命中不准；200 字子块只讲 A，向量集中指向 A。**小块精准命中 + 大块给上下文**（LlamaIndex 2023 年提出的 small-to-big 技巧）。
- 物理实现：PG 每条子块行里直接存父块原文（parentContent），检索后纯内存替换，无额外 IO。

### 2.4 混合检索：三路互补

| 检索方式 | 强项 | 弱项 |
|---|---|---|
| 语义（Milvus Dense） | 同义词、模糊语义、自然语言问题 | 专有名词、API 名、版本号、错误码 |
| 关键词（ES BM25） | 精确匹配、ID、专有名词 | 同义词、口语化问题 |
| 知识图谱（Neo4j KG） | 实体关系、多跳推理、间接相关 | 抽取错就拉胯 |

- Dense 的致命问题：关键词不敏感（4o mini / 128k / 特定版本号可能丢）、容易语义漂移。
- BM25 的致命问题：不懂语义，用户不会用文档原词提问。
- "单路检索是偏科生，三路混合检索是全科生——每种方式的短板都被其他方式补齐。"

### 2.5 查询链路（Query Pipeline）

RAG 模块五大组件（`internal/domain/rag/`）：

| 组件 | 文件 | 一句话职责 | 类比 |
|---|---|---|---|
| Engine | rag.go | 对外暴露 Ingest / QueryWithHistory，编排全流程 | 餐厅大堂经理 |
| Splitter | splitter.go | 把长文档切成父块 + 子块（递归 + 代码块保护） | 把书撕成便利贴 |
| HybridStore | hybrid.go | 三路混合检索 + 一级 RRF + 二级 RRF + 模式降级 | 投票合议庭 |
| Rewriter | rewriter.go | 改写用户问题成 N 条等价 query（消歧 + 多样化） | 把口语翻译成书面问题 |
| Reranker | reranker.go | LLM listwise 给候选段落打 0-10 分精排 | 评委二次复评 |

完整查询链路（以"上面讲的微服务怎么实现的？"这种省略 + 指代问题为例）：

1. **Rewriter 改写**：拼最近 6 轮历史摘要，LLM 输出 N 条自包含 query；**始终保留原查询**（LLM 改写可能跑偏，原查询保底召回，safety net 思维）；解析失败一律 fallback 到 `[原查询]`。
2. **三路检索**：每条 query 单独跑 Milvus + ES + KG 三路。
3. **一级 RRF（路间融合）**：`score(d) = Σᵢ wᵢ / (k + rankᵢ(d))`，k=60 平滑常数；关键性质是**只看排名不看分数**（各路分数量纲不同，排名天然可比）。
4. **二级 RRF（query 间合并）**：N 条 query 的结果再 RRF 一次——被多条 query 同时命中的 chunk 自然排前。
5. **LLM listwise 精排**：一次把所有候选给 LLM 统一打 0-10 分（不是 pointwise，listwise 分数尺度一致）；**RRF 分作 tiebreaker**（LLM 整数分易打平，RRF 是连续值几乎不打平）；LLM 漏打分的条目给兜底分 -1 而不是丢弃。候选池 = 4×topK 宽召回——rerank 能"精排"但不能"召新"。
6. **small-to-big 父块回填**：命中子块 → 从 PG 查出父块喂 LLM。
7. **拼提示词合成**：system prompt 明确要求"仅根据上下文回答，不编造"（防幻觉最后一道闸）；askQuery 用改写后的独立化版本；`generateFn == nil` 时直接返回检索原文（优雅降级）。

**写入链路（Ingest 7 步）**：父块切分 → 子块切分 → 每个子块 embed → 写 PG（老底，行内存父块原文）→ 写 ES（逐条，失败只打 log 不阻断）→ 批量写 Milvus（单条 RPC 开销大，批量 ~10 倍提速）→ **异步写 Neo4j**（建图要调 LLM 抽实体关系，单文档 5-30 秒，同步会 HTTP 超时；用 `goSafe` 包 recover 防 goroutine panic 拖崩主进程；传给建图的是含真实 PGID 的 indexed 数据，三路 RRF 融合要靠 pg_id 对齐 KG 节点与 PG 行）。

**docHash 幂等设计**：每次 Ingest 先算 docHash——作用 1：同一文档重复上传去重；作用 2：`Engine.Delete(docHash)` 一次删净 PG / ES / Milvus / Neo4j 四处。

### 2.6 为什么需要知识图谱

- 向量检索回答"哪些内容**相似**"，BM25 回答"哪些关键词**匹配**"，知识图谱回答"这些知识之间是什么**关系**"。
- 向量的本质缺陷：只能回答"哪个 Chunk 最像这个问题"，无法推导 Multi-Hop 关系。
- RAG 最终会发展成 Memory：长期记忆若全存向量只是孤立文本，图谱化后可沿图扩散（Graph Recall 思路）。
- GraphRAG 的正确定位：**关键词召回 + 向量召回负责找知识；知识图谱负责扩展知识**——不是替代而是叠加。单跳事实查询根本不需要图谱；多跳推理、企业知识库（组织架构 / 系统依赖）、Agent Memory 才是图谱价值区。
- 记忆写入时自动建时序（FOLLOWS）、相似（SIMILAR_TO，Cosine ≥ 阈值）等关系；合并淘汰时**保护高中心度节点**，防止核心知识丢失。

---

## 三、RAG 评测体系

### 3.1 分层评测思想

RAG 最容易坏的地方不是 LLM，而是 **Recall 不够**。不分层评测就根本无法优化——不知道是 retrieval、rerank、prompt 还是 LLM 的锅。**所有 RAG 只需要测两层：检索层 + 生成层。**

### 3.2 检索层指标

- 构建黄金评测集（golden set）：`question + ground_truth（正确 chunk id）`。
- **Recall@K**（最核心）：正确 chunk 出现在 Top-K 的比例；低则改进 query 改写、不同记忆走不同索引。
- **MRR**（排序质量）：正确答案排第 n 名得 1/n，取平均；低则调 rerank 系数、时间衰减权重。
- **NDCG**（整体排序质量，支持多相关文档：1 question 对应 5 chunk）。
- **HitRate@k**（是否命中）。

### 3.3 真实评测数据（项目实测）

- 语料：爬取 1250 篇掘金文档 → 10035 chunk（删除 35 个测试 chunk 后 10000 个真实 chunk 分别存入 ES 和 Milvus）；黄金评测集 50 条。
- 五家 embedding 模型对比（阿里 text-embedding-v4 / 百度 ernie-embedding-v3 / 字节 doubao-embedding-large / 腾讯 hunyuan-embedding / 华为 pangu-embedding）：

| 模型 | Dense Recall@5 | BM25 Recall@5 | Hybrid Recall@5 | Hybrid MRR | Hybrid+RRF NDCG@10 |
|---|---|---|---|---|---|
| Doubao-Embedding-Large | 0.75 | 0.64 | **0.86** | **0.74** | **0.83** |
| Qwen text-embedding-v4 | 0.72 | 0.64 | 0.84 | 0.72 | 0.81 |
| ERNIE-Embedding-V3 | 0.70 | 0.64 | 0.82 | 0.70 | 0.79 |
| Hunyuan Embedding | 0.66 | 0.64 | 0.80 | 0.68 | 0.77 |
| Pangu Embedding | 0.64 | 0.64 | 0.78 | 0.66 | 0.75 |

- 结论：**字节豆包 embedding 最适配掘金技术文章知识库**（纯向量召回阿里千问最好，但混合检索豆包更优）；BM25 各家相同（不经 embedding）；Hybrid 全面优于单路。
- 生成层用 **RAGAS** 框架测五个厂商对话模型：Doubao-Seed-2.0-lite 最优（Faithfulness 0.91 / Answer Relevancy 0.88 / Context Precision 0.84 / Context Recall 0.86），Pangu-π 最弱（0.75 / 0.83 / 0.79 / 0.81）。
- 核心方法论：**用真实数据说话做技术选型**，而非拍脑袋。

---

## 四、工具调用（Using Tool）

### 4.1 两种 Function Calling 风格

- 原生 function calling：API 层提供 tools 字段，稳定但协议绑死、表达能力受限。
- **自实现 JSON 风格（本项目选择）**：把 tools 描述拼进 prompt，让 LLM 吐 JSON，自己解析。优点：换 LLM 不用改协议、能塞 `depends_on` / `race_group` 这种原生协议没有的字段；缺点：吃 prompt token、需要大量 fallback。

### 4.2 基础抽象

- **Tool = "名片 + 按钮"**：Name + Description + Parameters 给 LLM 看，Execute 函数指针永远在本地（`json:"-"` 不序列化给 LLM）。
- `params` 用 `map[string]interface{}` 而非强类型 struct——工具种类无穷多，动态参数表换来"加一个工具不用改框架"。
- **toolRegistry 并发安全**：RWMutex 包 map，提供 `snapshot()` 读时浅拷贝——调用方拿快照后解锁无锁遍历，避免 ReAct 长循环挡住 MCP 工具动态注册（"读时拷贝、写时上锁"模式）。

### 4.3 路由决策

- 路径 A：前端显式勾选工具（最准确，直接走 react）。
- 路径 B：关键词启发式（自动）。**为什么用关键词不用 LLM 路由**：路由是入口，要快、便宜、确定；LLM 路由多一次 API 调用 + 1-2 秒延迟，关键词错了大不了走错路径，错路径里还有降级。
- RAG 是"既不是明显工具需求、也不是复合任务"时才单独走的模式——复合任务里 Planner 会自动把 rag_search 排进图。

### 4.4 单工具模式

规则选工具（关键词）→ 工具执行 → 1 次 LLM 综合。整体只调 1 次 LLM，延迟低；代价是工具选择规则化，只适合明确的单步任务。

### 4.5 ReAct 模式（核心）

五步流程：**Planner LLM（决定调谁）→ TaskGraph（拓扑排序 + 校验）→ GraphRuntime（分层并行调度）→ 竞速执行 → Generator LLM（讲人话）**。

**Planner 输出不稳定的 6 道防线**（回答"LLM 输出不可靠怎么处理"的标准范式）：

1. Prompt 工程：枚举可选值、给示例、约束"只输出 JSON"
2. 输出清洗：剥 ```json 包裹、剥特殊 token
3. 三档 schema 解析：理想格式 → 旧格式 → 原生 function calling 格式
4. 白名单过滤：编造的不存在工具直接丢
5. 整体降级：解析全失败 → 走纯关键词规则 rulePlanNodes
6. 图层兜底：DAG 有环 → 清空依赖降级全并行

**竞速执行（First-success-wins，ReAct 模式的杀器）**：同 `RaceGroup` 的节点（如 rag_search 和 search_web 同属 "search" 组）并发跑，谁先返回非错误结果就 cancel 另一个，失败的标记 StatusSkipped。好处：本地命中优先、rag 失败时 web 兜底、失败方立刻取消省 LLM 调用费。

**为什么要 2 次 LLM 调用**：Planner 强调结构化输出，Generator 强调自然语言——"决策"和"表达"分离让两次 prompt 各自最优（ReAct 论文 Reason + Act 的核心模式）。

### 4.6 RAG 作为 Tool 的 5 个特殊点

1. **注册位置不在 builtin**：Execute 闭包捕获了 RAG Engine 实例，builtin 是 infrastructure 层纯静态工具拿不到实例，必须在 application 层注册。
2. **Loaded 状态前置检查**：空库时调 RAG 没意义浪费 LLM 调用，返回 error 让 LLM 自动改用其他工具。
3. **丢弃 results 只回 answer**：SearchResult 里的 chunk_id、相似度分是调试信息，塞进 prompt 会污染上下文；命中详情通过 event bus 推前端 SSE。**双通道输出**：LLM 通道精简自然语言、前端通道详细结构化。
4. **RaceGroup="search" 与 search_web 竞速**（见上）。
5. **自反性（Self-improving RAG 闭环）**：`write_document(ingest_to_rag=true)` 让 LLM 能往 RAG 里写——用户问 A → rag_search 查不到 → search_web 查到 → LLM 整理成报告 → 写回 RAG → 下次命中。Agent 对自己的知识库做 CRUD。

---

## 五、ReAct 处理与任务 DAG

### 5.1 从串行链式到动态图

- **串行链式 ReAct**：思考 → 调工具 → 看结果 → 再推理，单链路串行。实现简单，但一个节点慢全部阻塞，复杂任务容易爆 context。
- **动态图 ReAct**：把任务拆成节点（推理 / 工具调用 / 数据处理），依赖关系组成 DAG；拓扑排序管理执行顺序，**入度为 0 即可执行**，互相无依赖的步骤并行跑。
- 核心升级：ReAct 从"链式调用"升级成**"可调度、可并行、可恢复的任务图 Runtime"**。
- 业界演进趋势（OpenAI Deep Research、LangGraph、AutoGen、Temporal Agent Runtime）都在走向图 Runtime 调度，而不是继续做 Prompt chaining。

### 5.2 本项目的独到之处（对比 LangGraph）

| 维度 | LangGraph | 本项目 |
|---|---|---|
| 图结构 | 编译时写死，运行时不变 | **运行时由 LLM 动态产出**（同一问题可能产生完全不同的图） |
| 并行 | 手动 conditional edge / Send | Kahn 算法分层，同层自动并行 |
| 竞速 | 无 | RaceGroup First-success-wins |
| 调度语义 | 状态机逐步推进 | 分层批量推进，wall-clock = sum(各层最长节点) |

- 运行时 DAG 的好处：Agent 真正"会规划"；工具集变化时 Planner 自动适配；"研究 X 写报告"自动生成 research → writer → review 链。
- 代价：需要降级路径（LLM 解析失败 → 规则 → 全并行）；图结构每次不同，调试更难。
- 三个核心抽象：**Node**（执行单元，超出常规 DAG 的字段：RaceGroup + AgentName/Goal，节点可以是子 Agent 不只是工具）、**TaskGraph**（邻接表 + 入度表 + 拓扑层缓存）、**GraphRuntime**（拓扑分层 + 信号量并发 + 竞速执行）。

### 5.3 从 Static DAG 到 Plan-and-ReAct

- 原来的 mode="react" 实际是 **Static DAG Plan-and-Execute**：Planner 一次性输出全图、Executor 按拓扑分层执行、Generator 一次性合成，中间没有 LLM 决策介入——与 ReAct 论文（Reasoning 与 Acting 交替循环）语义相反。
- 改造：Executor 循环里插入 **Replanner 决策点**，LLM 能基于 observations 追加节点，实现真正的 Reasoning + Acting 交替。
- Replanner 与 Planner 的差异（不是换模型，是输入与判断规则不同）：

| 维度 | Planner | Replanner |
|---|---|---|
| 输入 | Query + Tool 列表 | + 当前图快照 + 观察结果 |
| 触发时机 | 请求开始 | 每层执行完 / 节点失败 |
| 输出语义 | 全图 | 增量节点（可为空，最多 3 个） |
| 判断规则 | 选出需要的工具标依赖 | 观察够不够？不够再补；不重复已有节点 |

- `TaskGraph.AddNodes` 入度处理关键点：新节点依赖**已完成**的节点时入度不加，下一轮 ReadyNodes 立即返回它——"追加立即执行"的机制来源。

---

## 六、记忆系统

> 立场："未来最牛逼的 agent 技术部分绝对是围绕记忆系统去建设的。"

### 6.1 设计哲学：Mem0 思想 + Viking 思想

两个流派的本质区别：**Mem0 是"记忆检索"（Memory Middleware / Memory SDK），Viking 是"上下文编排"（Memory-Native AI Runtime）**。

| 对比 | Mem0 | Viking |
|---|---|---|
| 核心定位 | 独立记忆层（外挂） | Agent Runtime 内置记忆 |
| 思想 | Memory as Service | Memory as Context Infrastructure |
| 重点 | Memory Retrieval | Context Orchestration |
| 优点 | 开源、通用、易接入 | 工程化强、系统统一 |
| 缺点 | 偏外挂，记忆只是检索不是 Runtime State | 耦合重、改造成本高 |

**Mem0 核心思想**："不要存聊天记录，而是存事实"——从对话中蒸馏记忆（Fact-based Memory）；ADD-only 不覆盖旧记忆（记忆是时间态的）；Multi-Signal Retrieval 联合召回；Async Memory Write 写入不阻塞响应。

**项目路线**（业界最合理路线）：用 Mem0 思想解决**怎么存**（fact extraction / dedup / entity graph / semantic retrieval），用 Viking 思想解决**怎么组织上下文**（runtime state / planner state / task memory / tool state / context assembly）。

未来方向判断：Memory 不再是数据库问题，而是 **Context Engineering** 问题——谁能用更少 token 注入更准上下文、保持长期一致性、管理 runtime state，谁就更强。

### 6.2 五种记忆形态（不同数据不同表、不同生命周期）

1. **ShortTerm 短期对话窗口**：固定滑动窗口，超 MaxTurns × 2 条丢弃最早记录。
2. **Preference 结构化偏好**：**双通道写入**——规则路（同步、零延迟，保证"我叫张三"下一轮立即能答）+ LLM 路（异步、准确，覆盖长尾）；单 LLM 路有延迟空窗，单规则路覆盖率窄。
3. **LongTerm 长期语义记忆**：Importance 是召回二级信号（`s = sim*0.7 + Importance*0.3`，随时间衰减）；Category 是装配过滤维度（让"用户身份"不被"昨天的菜谱"挤掉）；SlotHint 是槽位归属建议。
4. **GraphMemory 图增强层**：Neo4j 节点 `(:Memory)`；边类型 FOLLOWS（时序相邻）、SIMILAR_TO（写入时 Cosine ≥ simThresh 自动建）；1-hop 图扩展召回 + 图中心度保护（入度 ≥3 的节点免于淘汰）。
5. **TaskMemBuffer 任务步骤环形缓冲**：生命周期与 ReAct 任务绑定（新任务 Reset，步骤后 Push）。独立出来的原因：任务步骤观察（"调了 weather_api 返回 22℃"）和长期记忆（"用户偏好咖啡"）生命周期完全不同，混存会"任务结束后步骤观察污染长期召回"。

### 6.3 写入链路

**长期记忆写入总则**：用户消息或 assistant 回复 → 异步交给 LLM 抽 k-v → 抽到才拼短句 embed → 去重后同时写内存 / 图 / PG 三层。**原始输入永远不直接进长期记忆，抽不出 k-v 就等于什么都没发生。**

- **写入即分类**（双通道分类管线）：规则层先行，LLM 兜底返回 `{category, tags, slot_hint}`，失败回落 general。必须分类的原因：没有分类，"用户姓名"和"上次讨论的菜谱"按相似度竞争 Top-K，问"做菜"时姓名信息就被排到 K 之外；有分类，身份信息走纯枚举（FilterByCategory）不算相似度，两路互不干扰。
- **写入去重（隐式合并）**：双重去重——哈希硬去重 + 向量化软去重（与长期记忆表相似度 > 0.92 的放弃存入）。去重不是"丢弃"而是"加固"——多次提到的事实自然 Importance 累积；类别升级遵循"具体战胜泛化"。写入期就去重，避免依赖 Consolidate 的 O(n²) 后处理。
- **异步建图**：linkSimilarEdges 扫最近 50 条记忆建 SIMILAR_TO 边。异步防 Neo4j 阻塞主链路；限 50 避免全表扫描（时序相邻的记忆相似性最高）。

### 6.4 召回链路

三种召回策略对应三类槽位：

| 槽位 | 召回方式 | 设计意图 |
|---|---|---|
| Profile | 按 Category 枚举，不算相似度 | 你的名字不会因为这轮问题不相关就被排到 TopK 之外 |
| Recall | 向量 + TF 兜底 + 1-hop 图扩展 | 图扩展是"主动联想"，发现间接关联但不直接相似的历史 |
| TaskMem | ring buffer 取最近 K | 任务内步骤记忆 |

- 综合分公式：`s = sim*0.7 + importance*0.3`——相似度是主信号，重要性是次信号；不让 Importance 主导是避免老旧高 importance 永远霸榜。
- **SlotFilter 声明式过滤**：MaxAgeHours 是年龄硬过滤（按 CreatedAt 截断），Importance 衰减是软信号，两者互补；召回时刷新 LastAccessed——访问触达即"重新激活"，间接保护活跃记忆。
- 1-hop 图扩展条目固定打 Score = 0.45——能进 prompt 但不会压过强相关命中。

### 6.5 合并链路（Consolidate 四阶段管线）

触发器：**计数触发而非定时**（低活跃期不空转、高活跃期及时清理），异步执行不阻塞用户响应。

1. **Phase 1 指数衰减**：按 CreatedAt 计算而非"上次衰减时间"（幂等，重复跑不累积错误）；`0.995^days` 日衰减系数（30 天 ≈ 86%，100 天 ≈ 61%）；Δ ≥ 0.01 才写 PG（控制写放大）。
2. **Phase 2 去重 + 合并**（双阈值分流）：Importance 高的为 base，Importance 取 max，Content 子串取长否则拼接，Embedding 按 Importance 加权平均，LastAccessed 刷新。**合并不调 LLM**：确定性、低延迟、可单测；LLM 改写大规模下成本爆炸（代价是长期会累积"用户偏好咖啡；用户喜欢拿铁"，可演进为 LLM rewriter）。
3. **Phase 3 双门槛过期淘汰**：必须同时 `days > TTLDays(30) AND Importance < MinImportance(0.3)` 才删——"老但仍重要"被永久保留，TTL 不是单方面"到期就删"。

### 6.6 上下文组装（promptctx 包）

职责：每轮 LLM 推理之前，按当前 Mode 编排出"喂给模型的 System Prompt 前缀"。**拒绝字符串之间拼接。**

- **六种 SlotKind 槽位**：Constraints（安全约束）/ Profile / Planner / TaskMem / ToolState / Recall。
- **RuntimeContextSchema**：Mode 与槽位编排表——chat 用 Constraints+Profile+Recall；tool 加 ToolState（必填）；react 全部必填；未知 Mode 自动 fallback 到 chat。
- **ContextSource**：槽位数据提供者，一个 source 可支持多个 SlotKind（如 GraphMemory 同时填 Profile/Recall）；各 source 独立可测，goroutine 并发装配。
- **双层 Budget 控制**：单槽位 budget 由 source 自治超额自动截断；全局 budget 默认 2400 字符，超限按优先级裁剪——**Constraints 优先级 0 永不丢失**。
- memPrefix 每轮 ReAct 开始前装配一次、冻结复用；循环内的更新"延迟一轮"生效，属于跨轮次短期工作记忆。
- 与普通字符串拼接的对比收益：避免上下文污染（最大收益）、**恢复 Agent 状态而不是恢复聊天记录**、token 利用率更高、长任务能力更强、不同记忆有不同生命周期。

---

## 七、记忆系统评测（五层体系）

| 层 | 测什么 | 指标 | 低了怎么改 |
|---|---|---|---|
| Store | 该不该存 | Memory Precision = tp/(tp+fp) | 改抽取标准 |
| Recall | 能不能记起来 | 复用 RAG 检索指标（recall@k / mrr） | query 改写、分索引、调 rerank 与衰减权重 |
| Consolidation | 记忆熵增（会不会越来越乱） | 重复率（相似度 >90% 聚类）+ Shannon Entropy（topic 分布） | 改合并/淘汰策略 |
| Context Assembly | 上下文组装是否合理（本质 prompt 调优） | Context Precision | 改装配策略 |
| Graph Expansion | 记忆关联是否合理 | Edge Precision | 改建边规则 |

- Store 层的"该不该记"判断标准：是否长期稳定 / 是否影响未来任务 / 是否属于用户偏好·目标·技能 / 是否有长期学习价值。
- Consolidation 用**时间轴模拟（Time-based Simulation）**：脚本模拟每天存 10 轮、存 100 天共 1000 轮，最后对剩余记忆向量化聚类算重复率、对 topic 分布算熵；好系统 topic 集中熵稳定，坏系统 topic 无限扩散熵持续升高。观察两条曲线：Memory Size Curve 与 Retrieval Quality Curve。

---

## 八、Harness 工程（容错执行 Runtime）

定位：**不是简单 retry，而是有状态、可恢复、可追踪、可编排的执行系统**。

开场白："LLM Agent 本质上是一个长链路 IO 系统，每一步（LLM 调用 / Tool / MCP / Web Search / RAG Retrieval）都是不稳定 IO。"Harness 解决 7 个问题：

1. **超时**：分层超时（LLM 30s / Web Search 10s / DB 3s / Sandbox 60s），避免短任务被长任务拖死；超时后走状态流转而不是进程直接挂。
2. **抖动（响应时间不稳定）**：自适应恢复——按错误日志分类处理：网络波动可重试；参数错误、权限错误、模型输出格式错误等逻辑问题不重试，直接终止或重新规划，避免任务卡死。**软失败**：单个工具终止不能导致整个流程失败，尽量跑完让 Generator 给出最终结果并告知哪个工具失败。
3. **工具失败**：Tool Isolation（每个工具独立执行上下文，失败不影响 Runtime）；统一 Tool Result Schema（不让工具返回自由文本，结构化 Result 让 Planner 能决策 retry / fallback / skip）。
4. **Agent 中断 + 长任务恢复**：每执行一步把状态快照存 Redis（执行进度、任务规划状态、已成功的工具结果、用户 query 变量）；恢复时从快照继续，不让大模型从头重推（长链路全重来成本高且上下文漂移）。事件记录机制：生命周期关键动作（planner / 工具调用 / 快照保存的 start→running→done）**只追加、不修改**，崩溃后可重放排查。
5. **上下文丢失**：动态上下文组装（按当前任务挑选运行状态 / 任务规划 / 相关历史 / 最近工具结果 / 短期记忆）；记忆分层（原始对话 / 长期记忆 / 运行时记忆）；旧上下文压缩（摘要、语义合并）。
6. **多步骤一致性**：显式状态机（start → running → done/fail，状态变化可追踪可恢复，不隐藏在代码流程里）；幂等性设计（每次工具调用生成唯一调用编号，恢复后重放不会重复触发已成功的操作）。

核心认知（原文总结）："Agent 最大的问题并不是模型和 prompt，而是**如何让一个不稳定的认知系统在真实生产环境里可靠运行**。所以我开始把 Agent 当成一个**分布式、有状态、可恢复的 Runtime 系统**去设计。"

---

## 九、子 Agent 与本地文档库

- 内置 4 个子 Agent：**research_agent**（检索与证据收集，输出结构化研究摘要）→ **writer_agent**（整理为 Markdown 报告）→ **review_agent**（检查结构 / 事实一致性 / 证据缺口 / 风险可信度）→ **doc_agent**（文档落库，尝试同步写入 RAG，审查内容写 metadata）。
- 图节点支持两种类型：`tool` 与 `sub_agent`（新增字段 type / agent_name / goal）；上游结果带 executor 名称，doc_agent 能识别哪份是正文哪份是审查意见。
- **确定性子 Agent 路由**：对"研究 / 调研 / 总结 / 报告 / 文档 / 方案 / 分析"关键词走确定性子 Agent 路由，避免研究类任务被误规划成单个搜索工具。
- 本地文档库领域模型：`documents`（稳定文档实体）+ `document_versions`（版本，content_md / summary / metadata）。
- 存储策略：PG 可用写库，不可用降级写本地 `.data/documents`（无 PG 也能测文档库和前端查看）。
- 新增工具：write_document / list_documents / read_document / ingest_document——Agent 可主动写入、读取和重新入库文档。
- RAG chunk 记录来源元数据（document_id / version_id / section），检索结果可反向追踪到完整文档和版本。
- 前端：本地文档库区域 + 独立文档查看器（点文档不再把内容追加进聊天）。

---

## 十、贯穿全局的设计思想（提炼）

1. **优雅降级无处不在**：PG 是 source of truth、其余全是可降级的派生索引；单路检索故障自动降级；LLM 输出解析 6 道防线层层兜底；generateFn 为 nil 直接返回原文；ES 写失败只打 log 不阻断。没有单点依赖，组件坏了系统照样跑。
2. **小块检索、大块生成**（small-to-big）：检索用精准小粒度，喂 LLM 用完整上下文，两层各取所长。
3. **并行与竞速**：拓扑分层让无依赖节点自动并行；RaceGroup 竞速 First-success-wins 兼顾延迟、质量兜底与成本。
4. **决策与表达分离**：Planner（结构化）与 Generator（自然语言）两次调用各自最优。
5. **存事实不存记录**：记忆是蒸馏出来的事实（Mem0），原始输入永远不直接进长期记忆；上下文组装恢复的是"Agent 状态"而非"聊天记录"（Viking）。
6. **不同数据不同生命周期**：五种记忆形态分表分策略；任务步骤记忆与长期记忆严格隔离防污染。
7. **评测驱动选型**：embedding 模型、生成模型、检索方式全部用真实数据（1250 文档 / 10000 chunk / 50 条黄金集 / RAGAS）跑分决定，不拍脑袋。
8. **Agent = 分布式 Runtime**：把 Agent 当分布式、有状态、可恢复的系统设计（快照、事件溯源、幂等、显式状态机），而不是 prompt 链条。
9. **Context Engineering 是核心竞争力**：未来拼的不是模型，而是用更少 token 注入更准上下文、保持长期一致性的能力。

---

## 附：来源文档清单（面试🚀计划子树）

| 文档 | 链接 |
|---|---|
| 面试🚀计划（总纲） | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/sgf4kv8ya93kb7ah |
| 架构总览 | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/ywv5hhdu3tnzimhc |
| RAG | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/gbkmp56a6ki3z383 |
| PDF 处理流程说明 | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/hhr0liyp3tqmkokx |
| RAG 问题检验 | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/nbuxu8n7inw3wpnf |
| RAG模块详细讲解 | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/xneuz8npio5a9nw5 |
| 怎么评测RAG效果 | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/gqkcyldld0c7afly |
| AGI项目的真实RAG评测 | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/kg90qoh7vm8o79bg |
| 为什么rag需要知识图谱 | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/dfwih2ge2rp3ynp9 |
| Using Tool | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/kztaldw0d8n4ef3k |
| Saber工具调用全流程 | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/pwceramosngpwuww |
| ReAct处理 | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/wd641plhk7615sz0 |
| 从 Static DAG 到 Plan-and-ReAct | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/ltm0t3337f5k0glu |
| 任务 DAG 设计 | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/lrfvxx45p6qm1g9p |
| 动态图ReAct和串行链式ReAct | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/rdbcbr1vy2oaenr6 |
| 记忆系统（会话管理）！！！ | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/wrf2f1sgen39slzh |
| 记忆系统详细介绍 | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/qwsuulxsongrhiak |
| 如何组织记忆上下文 | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/sng79ezhasg971re |
| 怎么评测记忆系统 | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/lwvzhyiowohhg2z0 |
| mem0 🆚 viking | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/uy509v64cse72mgk |
| Harness工程 | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/eem938c7rw31md15 |
| 子 Agent 与本地文档库模块 | https://www.yuque.com/yuqueyonghu-ng3vtk/agi-saber/ld9xgiguusbeam2g |

> 注：AGI-saber 分组下另有「简历写法」「问答汇总」「项目面经」「快速入口」等文档（含竞速机制、系统提示词、记忆一致性等问答），不在本次总结范围内，需要时可再补。
