# Phase1.agentteam合约

## 目的
定义 `agentteam` 作为 VenAgent 的子 agent 组织层，保证后续可以：
- 使用预制子 agent
- 扩展自定义子 agent
- 在不改主编排逻辑的前提下增加能力

---

## 设计定位

`agentteam` 不是工具层，也不是 RAG 核心层。

它负责的是：
- 子 agent 注册
- 子 agent 配置
- 子 agent 选择
- 子 agent 生命周期管理
- 预制 agent 与自定义 agent 的统一入口

---

## 核心原则

### 1. 配置驱动
agent 的定义尽量通过配置和注册信息完成，不把逻辑写死在主流程里。

### 2. 预制优先
原 RAG 的四个固定 agent 优先迁为预制 agent，保证迁移连续性。

### 3. 可扩展
后续新增 agent 不需要改 `LangGraph` 主入口，只需要注册到 `agentteam`。

### 4. 不侵入底层
`agentteam` 不持有 RAG / memory 的实现细节，只消费 MCP 工具和统一契约。

---

## 合约内容

### A. Agent 定义
每个 agent 至少需要这些信息：
- `name`
- `role`
- `purpose`
- `input_schema`
- `output_schema`
- `tool_permissions`
- `memory_policy`
- `retrieval_policy`
- `prompt_template`

### B. Agent 运行上下文
每次运行至少携带：
- `task_id`
- `session_id`
- `user_intent`
- `conversation_state`
- `available_tools`
- `policy_flags`

### C. Agent 输出
输出需要统一为结构化结果，至少包括：
- `status`
- `result`
- `notes`
- `follow_up`
- `used_tools`

---

## 预制 agent

### 1. `research`
场景：
- 搜集资料
- 做信息归纳
- 生成初步结论

### 2. `doc_qa`
场景：
- 文档问答
- 上下文检索
- 证据回溯

### 3. `synthesis`
场景：
- 多来源融合
- 结果整理
- 统一口径输出

### 4. `ops`
场景：
- 辅助执行
- 工具协调
- 任务型操作

---

## 自定义扩展

### 扩展方式
新的子 agent 通过如下路径接入：
- 新建 agent 定义
- 注册到 `agentteam/registry`
- 配置权限与上下文策略
- 挂接到 LangGraph 某个节点或子图

### 扩展约束
- 不允许直接绕过 MCP 调底层能力
- 不允许在自定义 agent 中复制核心检索逻辑
- 不允许把流程控制塞回 RAG 核心层

---

## 与 RAG 的关系

### 旧模式
RAG 里固定写死若干 agent，调用路径耦合在一起。

### 新模式
RAG 保留底层能力，agent 归 `agentteam` 统一管理。

### 结果
- RAG 专注于检索和证据
- agentteam 专注于任务拆分和角色协作
- Graph 专注于流程调度

---

## 与 MCP 的关系

### agentteam 调 MCP
`agentteam` 通过 MCP 调用：
- RAG 工具
- memory 工具
- document 工具
- 其他外部工具

### 不做的事
`agentteam` 不直接实现这些能力本身。

---

## 目录建议

```text
agentteam/
  contracts.py
  registry.py
  runtime.py
  presets/
    research.py
    doc_qa.py
    synthesis.py
    ops.py
  custom/
  prompts/
```

---

## 验收标准

当以下条件满足时，`agentteam` 合约就算完成：
- 预制 agent 有明确职责
- 自定义 agent 有稳定接入方式
- 统一输入输出结构已经定义
- `agentteam` 不依赖底层实现细节
- 后续新增 agent 不需要改主编排逻辑

