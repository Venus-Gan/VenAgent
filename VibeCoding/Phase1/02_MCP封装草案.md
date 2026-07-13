# Phase1.MCP封装草案

## 目的
把 VenAgent 的核心底层能力，统一包装为可被 `LangGraph` 和 `agentteam` 调用的 MCP tool。

这份草案只定义边界和契约，不改底层实现。

---

## 设计目标

### 1. 保留核心实现
时间、天气、搜索、命令执行、文档相关能力都保留在内部。RAG 和 memory 也保留在内部。

### 2. 对外统一接口
所有上层调用只面对 MCP tool，不直接调用内部类或函数。

### 3. 便于扩展
后续如果替换检索后端、记忆后端、解析引擎，只要保持 MCP 契约不变即可。
网页获取部分固定走 `fetch MCP`，不再依赖 Tavily 配置。

### 4. 兼容优先
MCP 契约以“尽量兼容现有代码语义”为原则，不把底层重构细节直接暴露给上层。
- 能沿用现有字段就沿用
- 需要收敛的字段放到可选参数里
- 返回值尽量保留 answer / results / metadata 这类稳定字段
- 上层只依赖 MCP 结果，不直连内部对象结构

---

## 契约原则

### 兼容优先总原则
- 尽量沿用现有业务语义
- 尽量不泄露底层类结构
- 尽量让后续 LangGraph 重构只改内部实现，不改 MCP 调用方
- 优先保持 `answer / results / metadata / status` 这类稳定输出字段

### RAG 契约表
| 项目 | 约定 |
|---|---|
| 目标 | 提供稳定的知识检索与回答接口 |
| 不暴露 | `Engine.query_with_history_stream` 等内部方法 |
| 输入必填 | `query` |
| 输入可选 | `history`, `top_k`, `rewrite`, `mode`, `trace` |
| 输出主字段 | `answer`, `results`, `sources`, `metadata` |
| 可选输出 | `events` |
| 兼容原则 | `query` 语义不变，`history` 仅作为增强，不强制调用 |
| 重构容忍度 | 底层可改成 LangGraph 节点图，但外层契约保持稳定 |

### Memory 契约表
| 项目 | 约定 |
|---|---|
| 目标 | 提供稳定的读写召回接口，覆盖短期/长期/偏好/图记忆 |
| 不暴露 | `LongTerm`, `ShortTerm`, `GraphMemory` 的类结构 |
| 输入必填 | `scope`（读写都需要），写入时还需要 `content` |
| 输入可选 | `session_id`, `query`, `importance`, `tags`, `category`, `slot_hint`, `limit`, `include_graph` |
| 输出主字段 | `items`, `record_id`, `count`, `metadata`, `status` |
| 兼容原则 | 读接口保持“列表 + 元数据”，写接口保持“成功/失败 + 新 ID/记录数” |
| 重构容忍度 | 底层怎么切换不影响 MCP 调用方 |

### 输入输出约定
- 输入使用 JSON schema 或等价结构化参数
- 必填与可选字段明确分开
- 输出统一保留 `ok/data/error/meta` 风格时最容易被上层消费
- 如果某个 tool 还需要过程信息，优先放到 `metadata` 或 `events`

---

## 工具分组

| 组别 | 工具 | 归属 | 备注 |
|---|---|---|---|
| 基础工具适配层 | `get_time`, `get_weather`, `search_web`, `exec_command`, `document.parse`, `document.ingest` | MCP tool | `search_web` 的网页获取后端改用 `fetch MCP`；`exec_command` 走受控执行边界 |
| RAG 工具 | `rag.search`, `rag.retrieve` | Core + MCP | 保留底层检索逻辑，对外统一 schema |
| Memory 工具 | `memory.read`, `memory.write` | Core + MCP | 读写长期/短期/图记忆 |
| 沙箱与受控执行边界 | `exec_command` | Sandbox + MCP | 沙箱独立保留，不并入普通 tool 集合 |
| 外部工具 | 未来其他 MCP server | MCP tool | 统一由 MCP 暴露 |

### A. 基础工具适配层
这些能力都归入 MCP tool，但其中 `exec_command` 仍然走受控执行边界，不等于把沙箱本身封成普通工具。

#### `get_time`
场景：
- 查询当前时间

#### `get_weather`
场景：
- 查询天气

#### `search_web`
场景：
- 网页内容获取
- 由 `fetch MCP` 提供后端支持

#### `exec_command`
场景：
- 受控命令执行
- 走 sandbox 适配

#### `document.parse`
场景：
- 解析上传文档
- 提取结构化内容

#### `document.ingest`
场景：
- 文档入库
- 分块和索引

---

### B. RAG 工具

#### `rag.search`
场景：
- 语义检索
- 混合检索
- 召回候选结果

输入：
- `query`
- `top_k`
- `filters`
- `mode`

输出：
- `results`
- `score`
- `source_refs`

#### `rag.retrieve`
场景：
- 按上下文补全证据
- 召回文档片段

输入：
- `query`
- `context`
- `budget`

输出：
- `chunks`
- `citations`
- `summary`

---

### C. Memory 工具

#### `memory.read`
场景：
- 读取会话记忆
- 读取长期记忆

输入：
- `session_id`
- `scope`
- `query`

输出：
- `items`
- `metadata`

#### `memory.write`
场景：
- 写入对话记忆
- 记录长期知识

输入：
- `session_id`
- `scope`
- `content`
- `tags`

输出：
- `success`
- `record_id`

---

### D. 沙箱与受控执行边界
`exec_command` 通过 MCP 暴露，但沙箱本身仍作为独立模块保留，不并入普通 tool 集合。

#### 原则
- 工具层只看受控接口
- 沙箱负责隔离和资源限制
- 上层不直接持有执行细节

---

### E. 外部工具

这些工具都应以 MCP 方式统一暴露，避免上层直接依赖实现细节。

---

## 输入输出规范

### 输入规范
- JSON schema 明确
- 字段尽量稳定
- 必填项和可选项分开
- 不接受隐式参数

### 输出规范
建议统一输出：
- `ok`
- `data`
- `error`
- `meta`

---

## 权限边界

### 允许
- 读检索结果
- 读写记忆
- 调用标准文档解析
- 调用受控外部工具

### 受限
- 命令执行
- 文件系统敏感操作
- 未授权的数据写入

### 原则
上层 agent 只拿到最小必要权限。

---

## 迁移顺序

### 第一批
- `rag.search`
- `rag.retrieve`
- `memory.read`
- `memory.write`

### 第二批
- `document.parse`
- `document.ingest`

### 第三批
- 其他外部工具

---

## 兼容策略

### 兼容旧调用
在迁移初期，保留旧接口的适配层，避免一次性切断调用链。

### 渐进切换
先让新 graph 和新 agentteam 走 MCP，再逐步把旧路径切掉。

---

## 验收标准

当以下条件满足时，MCP 封装就算完成：
- RAG 和 memory 能通过标准 tool 调用
- 上层不再直连底层实现
- 输入输出结构统一
