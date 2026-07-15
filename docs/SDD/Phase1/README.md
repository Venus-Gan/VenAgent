# Phase1 文档集

## 阅读顺序
| 顺序 | 文档 | 适用场景 |
|---|---|---|
| 00 | [00_重构总览.md](./00_重构总览.md) | 先看全局目标、边界和拆分导航 |
| 01 | [01_模块映射.md](./01_模块映射.md) | 看现有能力如何归类到 Core / MCP / Graph / AgentTeam |
| 02 | [02_MCP封装草案.md](./02_MCP封装草案.md) | 看 RAG、Memory、文档、外部工具的 MCP 契约 |
| 03 | [03_agentteam合约.md](./03_agentteam合约.md) | 看子 agent 组织层、预制 agent 和扩展方式 |
| 04 | [04_promptctx与Skill.md](./04_promptctx与Skill.md) | 看 promptctx 如何收口 Skill，以及 Skill 如何被唤起 |
| 05 | [05_RuntimeGovernance.md](./05_RuntimeGovernance.md) | 看恢复、快照、取消、状态如何统一治理 |
| 06 | [06_bootstrap与config.md](./06_bootstrap与config.md) | 看配置分组、加载顺序和 bootstrap 装配链 |
| 07 | [07_LangGraph落点.md](./07_LangGraph落点.md) | 看哪些原始逻辑适合交给 LangGraph 收口 |
| 08 | [08_核心特色与边界.md](./08_核心特色与边界.md) | 看项目特色如何保留，以及哪些不能被 MCP 吞掉 |
| 09 | [09_实施路线与风险.md](./09_实施路线与风险.md) | 看迁移步骤、预制子 agent、风险控制和交付标准 |

## 代码补充
| 顺序 | 文档 | 适用场景 |
|---|---|---|
| 10 | [10_运行策略层.md](./10_运行策略层.md) | 看意图如何进入 IntentPolicy，以及 profile 如何选择 |
| 11 | [11_主agent与运行入口.md](./11_主agent与运行入口.md) | 看 `main.py`、`UnifiedAgent` 和主编排入口怎么收口 |
| 12 | [12_工具系统与执行器.md](./12_工具系统与执行器.md) | 看工具注册、搜索链路、文档工具和沙箱边界 |

## 说明
- 快速主线建议先读 `00 -> 01 -> 02 -> 03 -> 04 -> 05 -> 06 -> 07 -> 08 -> 09`。
- 如果要对照当前代码实现，再补读 `10 -> 11 -> 12`。
- `00_重构总览.md` 保留全局判断，其余文件负责把细节切开。
- 如果后续继续拆分，可继续按 `13_`, `14_` 递增编号。
## 下一阶段
- Phase2 文档在 [../Phase2/README.md](../Phase2/README.md)
- 它把 Phase1 的边界和契约转成施工流水线
