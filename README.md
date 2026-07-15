# VenAgent — AI 智能体系统

VenAgent 是一个面向个人的 AI 智能体系统，融合了检索增强生成（RAG）、三层记忆、知识图谱、沙箱执行与可恢复执行流，支持多轮对话、知识检索、工具调用与复杂推理。系统具备高可用性、可扩展性与工程落地能力。

## 项目特性

- **多模式智能体核心**：支持纯对话、RAG 检索、单工具调用、多工具编排（ReAct）等多种模式，由 IntentPolicy 自动路由。
- **RAG 检索增强生成**：融合 Milvus 语义向量、Elasticsearch BM25 关键词、Neo4j 知识图谱，三路 RRF 融合排序，自动降级，支持文档分块与异步实体关系抽取。
- **三层记忆系统**：短期记忆（滑动窗口）、长期记忆（Embedding + TF 双层）、用户偏好（LLM + 规则），支持去重、合并、衰减、过期淘汰。
- **图增强记忆**：长期记忆叠加 Neo4j 图层，支持 FOLLOWS、SIMILAR_TO、CAUSES、BELONGS_TO 等关系，提升历史联想与推理能力。
- **工具链与可恢复执行**：内置时间、天气、搜索、RAG 检索、命令执行等工具，支持 ReAct 规划-执行-生成流程，任务快照与重试机制保障稳定性。
- **沙箱执行**：支持 Docker / Local / Mock 三种沙箱后端，资源限制（CPU/内存/PID/网络），命令白名单安全校验。
- **高可用基础设施**：PostgreSQL 持久化、Milvus/ES/Neo4j/Kafka 可选，自动优雅降级，适配多种部署环境。

---

## 整体架构图

```mermaid
graph TB
    subgraph Frontend["前端 (index.html)"]
        CHAT["对话区"]
        SIDEBAR["侧边栏<br/>知识库上传 / 近期对话"]
        CTRL["控制栏<br/>知识库开关 / 工具选择"]
    end

    subgraph Router["智能路由层"]
        R["IntentPolicy 路由"]
    end

    subgraph Core["核心能力"]
        CHAT_ENGINE["对话模式<br/>LLM + STM 历史注入"]
        RAG_ENGINE["RAG 模式<br/>Milvus + ES + Neo4j 三路检索 → RRF融合 → LLM合成"]
        TOOL_ENGINE["工具调用模式<br/>time / weather / search / exec_command"]
        REACT_ENGINE["ReAct 模式<br/>Planner → Executor → Generator"]
    end

    subgraph Memory["三层记忆"]
        STM["短期记忆<br/>滑动窗口"]
        LTM["长期记忆<br/>Embedding语义 + Neo4j图关系"]
        PREF["用户偏好<br/>LLM + 规则提取"]
    end

    subgraph Harness["稳定执行"]
        RETRY["重试机制"]
        SNAP["快照恢复"]
    end

    subgraph Sandbox["沙箱执行"]
        DOCKER["Docker 后端<br/>资源隔离 + 安全限制"]
        LOCAL["Local 后端"]
        MOCK["Mock 后端"]
    end

    subgraph Infra["基础设施 (全部可选, 优雅降级)"]
        PG["PostgreSQL<br/>偏好/LTM/RAG Chunk持久化"]
        MIL["Milvus<br/>语义向量近邻搜索"]
        ES["Elasticsearch<br/>BM25全文检索"]
        NEO["Neo4j<br/>知识图谱 + 图增强记忆"]
        KAFKA["Kafka<br/>事件流"]
    end

    CHAT --> R
    CTRL --> R

    R -->|纯对话| CHAT_ENGINE
    R -->|知识检索| RAG_ENGINE
    R -->|单工具| TOOL_ENGINE
    R -->|多工具编排| REACT_ENGINE

    CHAT_ENGINE --> Memory
    RAG_ENGINE --> Memory
    TOOL_ENGINE --> Memory
    REACT_ENGINE --> Memory
    REACT_ENGINE --> Harness

    TOOL_ENGINE --> Sandbox
    REACT_ENGINE --> Sandbox
    Sandbox --> DOCKER
    Sandbox --> LOCAL
    Sandbox --> MOCK

    RETRY --> SNAP
    SNAP --> PG

    STM -.->|多轮历史| CHAT_ENGINE
    LTM -.->|跨会话恢复| CHAT_ENGINE
    PREF -.->|个性化上下文| CHAT_ENGINE

    LTM --> PG
    LTM --> NEO
    PREF --> PG
    RAG_ENGINE --> MIL
    RAG_ENGINE --> ES
    RAG_ENGINE --> NEO
    CHAT_ENGINE --> KAFKA

    SIDEBAR -->|上传文档| RAG_ENGINE
```

---

## 核心流程时序图

```mermaid
sequenceDiagram
    actor User
    participant FE as 前端
    participant Router as 智能路由
    participant LLM as LLM API
    participant Planner as Planner LLM
    participant Executor as Executor
    participant Tool as Tool / RAG / Sandbox
    participant Generator as Generator LLM
    participant Memory as 三层记忆
    participant DB as PostgreSQL

    User->>FE: 输入消息 + 选择工具
    FE->>Router: POST /api/chat {message, tools}

    alt 纯对话 (无工具)
        Router->>Memory: 加载 STM 历史 + LTM + 偏好
        Memory-->>Router: 上下文消息列表
        Router->>LLM: Chat(systemPrompt + 历史 + 当前消息)
        LLM-->>Router: 自然语言回答
        Router->>Memory: 异步提取偏好 + 存储长期记忆

    else 工具编排 (ReAct)
        Router->>Planner: 分析query + 工具列表 → 执行计划
        Planner-->>Router: [{tool, params, reason}, ...]

        loop 按计划逐步执行
            Router->>Executor: 执行 tool(params)
            Executor->>Tool: 调用具体工具
            Tool-->>Executor: 观察结果
            Executor-->>Router: 步骤结果 (思考 → 动作 → 观察)
            Router->>DB: 保存快照
        end

        Router->>Generator: 合成所有观察 → 最终答案
        Generator-->>Router: 自然语言回答
        Router->>Memory: 异步存储长期记忆 + 提取偏好
    end

    Router-->>FE: {answer, steps, memories}
    FE-->>User: 渲染回答 + 思考过程
```

---

## RAG 三路混合检索流程图

```mermaid
sequenceDiagram
    actor User
    participant RAG as RAG Engine
    participant EMB as Embedding API
    participant MIL as Milvus
    participant ES as Elasticsearch
    participant NEO as Neo4j
    participant PG as PostgreSQL
    participant LLM as LLM API

    User->>RAG: 查询: "量子计算的应用领域"
    RAG->>EMB: Embed(query)
    EMB-->>RAG: query向量 [0.12, -0.34, ...]

    par 三路并行检索
        RAG->>MIL: MilvusSearch(query向量, topK)
        MIL-->>RAG: 语义结果 [{pg_id, distance}, ...]
        RAG->>ES: BM25Search(query, topK)
        ES-->>RAG: 关键词结果 [{pg_id, score}, ...]
        RAG->>NEO: GraphSearch(实体, maxHops=2)
        NEO-->>RAG: 图谱结果 [{pg_id, weight}, ...]
    end

    RAG->>RAG: RRF融合排序<br/>score = Σ(1/(k+rank_i)) × weight_i<br/>语义0.7 + BM25权重 + 图0.3

    RAG->>PG: LoadRAGChunksByIDs(top_pg_ids)
    PG-->>RAG: [{id, content}, ...]

    RAG->>LLM: Chat(系统提示 + 检索上下文 + 用户问题)
    LLM-->>RAG: 基于知识的回答

    RAG-->>User: 回答 + 引用来源
```

---

## 技术实现亮点

- **RAG 检索增强**：
    - 支持三路混合检索（Milvus 语义向量、ES BM25 关键词、Neo4j 知识图谱），RRF 融合排序。
    - 文本分块采用窗口重叠，提升召回覆盖率。
    - 检索模式自动切换，单路故障自动降级，支持企业级高可用。

- **三层记忆系统**：
    - 短期记忆：滑动窗口保存最近 N 轮对话。
    - 长期记忆：Embedding + TF 双层，支持去重、合并、衰减、过期淘汰。
    - 偏好记忆：LLM + 规则自动提取用户偏好，持久化跨会话恢复。

- **图增强记忆**：
    - 记忆写入时自动建立时序（FOLLOWS）、相似（SIMILAR_TO）等关系。
    - 支持图扩展召回，发现间接关联历史记忆。
    - 合并淘汰时保护高中心度节点，防止核心知识丢失。

- **智能体与工具链**：
    - 路由优先级：ReAct 复合推理 > 单工具 > RAG 检索 > 纯对话。
    - 工具链支持自定义扩展，RAG 检索作为知识库工具无缝集成。
    - ReAct 规划-执行-生成流程，任务快照与重试机制保障稳定性。

- **沙箱执行**：
    - 支持 Docker（资源隔离 + 安全限制）、Local（直接执行）、Mock（测试）三种后端。
    - 命令长度限制、白名单校验、资源配额（CPU/内存/PID/网络/只读文件系统）。

- **工程与基础设施**：
    - PostgreSQL 持久化所有关键数据。
    - Milvus/ES/Neo4j/Kafka 可选，自动降级，适配多种部署环境。
    - 前后端解耦，支持多端接入。

---

## 快速开始

### 本地运行

```bash
# 1. 安装依赖
pip install -r final/requirements.txt

# 2. 启动基础设施（需要 Docker）
cd final
docker-compose up -d

# 3. 配置 LLM API Key
# 编辑 final/config/config.yaml，填入 llm.api_key 和 embedding.api_key

# 4. 启动应用
cd final && python main.py

# 5. 访问 http://localhost:8090
```

> 所有基础设施（Milvus/PG/ES/Kafka/Neo4j）均为可选，连接失败自动降级为内存模式，不影响启动。

### 配置

编辑 `final/config/config.yaml`，填入 API Key：

- `llm.api_key` — OpenAI 兼容对话模型 API Key（DeepSeek / 火山方舟等）
- `embedding.api_key` — Embedding 模型 API Key

---

## 目录结构

```
final/
├── config/                   配置加载（YAML → Python 数据类）
│   ├── config.py
│   └── config.yaml
├── internal/
│   ├── agent/                智能体核心与调度（ReAct + Harness + 路由）
│   ├── agentteam/            多 Agent 协作（预设合约 + 注册表）
│   ├── document/             文档管理（解析 + 版本化 + 入库）
│   ├── graph/                知识图谱（Neo4j 实体关系抽取 + 图检索 + 任务图）
│   ├── handler/              HTTP API 路由处理 + SSE 流式
│   ├── infra/                基础设施连接（Milvus / PG / ES / Kafka）
│   ├── llm/                  LLM/Embedding 客户端（OpenAI 兼容 + Mock 降级）
│   ├── memory/               三层记忆系统（短期 / 长期 / 用户偏好 + 图增强）
│   ├── platform/             各平台客户端薄封装（Milvus / PG / ES / Neo4j / Kafka）
│   ├── promptctx/            Prompt 上下文装配系统
│   ├── rag/                  RAG 引擎（三路混合检索 + RRF 融合 + 查询改写 + 重排序）
│   ├── repo/                 各领域持久化仓储
│   ├── sandbox/              沙箱执行（Docker / Local / Mock + 安全校验）
│   └── tools/                工具定义与调用（time / weather / search / exec_command / MCP）
├── frontend/                 单文件前端 HTML
├── tests/                    ~50 个单元测试文件
├── main.py                   入口
├── requirements.txt          Python 依赖
└── docker-compose.yml        基础设施编排
```

---

## 重构状态

当前项目基于 Python + FastAPI 实现，后续计划引入 LangChain/LangGraph。目前处于 **Phase 1** 重构阶段，正在对核心模块进行边界抽取与架构标准化。

- ✅ 已完成：IntentPolicy 策略层、MCP 工具边界抽出、agentteam 合约定义
- 🔄 进行中：边界实现加固、兼容路径清理
- 📋 计划中（Phase 2）：将自研图执行引擎迁移到 LangGraph StateGraph（`agent/langgraph/` 已包含过渡实现）

设计文档见 `docs/SDD/`。

---

## License

MIT

## 致谢

本项目受 AI 智能体、RAG、知识图谱、记忆增强等前沿研究启发，欢迎交流与合作。
