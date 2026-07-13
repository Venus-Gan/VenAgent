# promptctx 与 Skill 方案

## 定位
| 项目 | 约定 |
|---|---|
| promptctx | 上下文装配层，负责把已有事实和策略渲染成 prompt 前缀 |
| Skill | 操作型上下文，负责提供方法、约束和工作流提示 |
| 不负责 | 直接执行 skill、调度 skill、编排 skill |

## promptctx 结构
| 层 | 职责 |
|---|---|
| Schema | 定义 chat/tool/react/rag 等模式的槽位模板 |
| Source | 从 profile、recall、planner、taskmem、toolstate、skill 等来源取材料 |
| Assembler | 并发装配、预算裁剪、失败降级 |
| Render | 输出给模型的 prompt 前缀 |

## 待收口说明
- `PresetAgent` 的角色定义和可发现信息，后续应由 `promptctx` / `.team/config.json` 提供，而不是长期硬编码在 `agentteam` registry 中。
- 当前 `agentteam/catalog.py` 仅作为过渡静态目录，后续要迁入可配置目录层。

## Skill 集成
| 层 | 职责 |
|---|---|
| SkillManifest | skill 的元数据定义 |
| SkillRegistry | 注册可用 skill |
| SkillCatalog | 供 LLM / planner 读取的精简目录 |
| SkillResolver | 结合命令、自然语言、模式、上下文选择 skill |
| SkillInvoker | 决定走上下文注入还是工作流执行 |
| SkillSource | 让 skill 成为 promptctx 的一种 source |

## skill 的两种形态
| 形态 | 作用 | 归属 |
|---|---|---|
| Context Skill | 加入方法、风格、安全边界、输出规范 | promptctx |
| Execution Skill | 触发子图或子代理工作流 | agentteam / LangGraph |

## 唤起方式
| 方式 | 例子 | 说明 |
|---|---|---|
| 命令唤起 | `skill: security-review` | 显式、可控，适合调试 |
| 自然语言唤起 | “按重构流程整理” | 由 resolver 或 planner 识别 |
| LLM 自主发现 | 在 system prompt 中注入 skill 目录摘要 | 让模型知道自己能用哪些 skill |

## 运行边界
| 组件 | 负责 | 不负责 |
|---|---|---|
| promptctx | 看见 skill 并装配 skill 上下文 | skill 调度和执行 |
| SkillResolver | 决定是否唤起 skill | 具体执行 |
| agentteam | 执行型 skill 或 skill-backed 子代理 | 上下文拼装 |
| LangGraph | 决定什么时候进入 skill 分支 | skill 内容本身 |

## 验收标准
- 用户可以命令唤起 skill
- 用户可以自然语言唤起 skill
- LLM 可以感知可用 skill
- skill 不只会加载，还能真正参与对话执行
