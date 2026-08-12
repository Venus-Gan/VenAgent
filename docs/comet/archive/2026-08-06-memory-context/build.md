# M05 memory-context Build 产物

## 实现结果

- 在 `venagent/memory/` 建立 M05 领域边界：操作级 `MemoryAuthorization`、完整 turn 窗口、稳定事实资格策略、生命周期、来源治理、确定性命令和 G1 图。
- run 路径只从有效 `ExecutionAuthorization` 派生 memory read/write 授权；命令路径只从活动 session、owner、tenant 和当前 authorization epoch 派生，不创建或伪造 `AgentRun`。
- durable authenticated user 默认启用长期记忆；durable guest 与 temporary identity 均不能开启或写入跨会话记忆。关闭后仅当前用户输入进入 run 上下文，管理命令仍可使用。
- 自动事实入口仅接受原始用户消息或显式标记的授权工具结果；assistant 文本与短期派生内容没有写入入口。首版保守抽取姓名、所在地、职业、项目及受策略保护的特殊类别，偏好、秘密、完整支付数据和第三方特殊类别在写入前拒绝。
- PostgreSQL schema 升级为 v7，除 owner 私有设置、来源、事实、确认 token 与版本化 G1 边外，新增可重建短期摘要和持久化后台任务；temporary runtime 使用行为等价但禁止长期写入的内存 adapter。
- `ADD/UPDATE/NOOP`、多来源保留、最后来源撤销、精确删除、整库删除、`superseded/deleted/expired/quarantine` 状态和内容净化均由应用用例与权威事务管理。
- `/memory` 命令在现有 run HTTP 入口前确定性分流，返回纯文本结果；Vue store 识别命令响应后不添加消息、不启动 run/SSE。
- `/memory list [cursor]` 固定 20 条，cursor 使用 HMAC 与 owner 绑定；`forget` 只接受精确活动 ID；多事实来源撤销和 `delete-all` 使用 5 分钟、owner 绑定、单次使用且重校验影响集合的确认 token。
- G1 注册表版本为 `m05-g1-v1`：`FOLLOWS` 仅连接同 owner/tenant/source timeline 的相邻活动事实，`SIMILAR_TO` 使用规范化 pair 和冻结阈值；重建只失活旧边，不删除审计事实。一跳邻居只能扩大候选池，仍需重新通过严格相关性门槛。
- M05-S 生成带 owner/conversation、消息 ID 范围、策略版本、来源状态 hash 和删除代次的可重建摘要；摘要失败或超时只回退最近完整 turn，近期明确纠正会压制冲突的旧 turn。
- 自动提取改为回答发布后只入持久队列，后台任务使用 `source_ref + policy version + operation` 幂等键，并在每次重试前重校验 owner epoch、开关、来源、conversation 生命周期和删除代次。重试有界退避，耗尽后只保留安全错误码，可受控重放。
- 权威事实与派生投影分离：事实先以 `index_pending` 提交，G1 投影成功后转为 `ready`；投影失败不伪造完整召回，后台恢复后按同一事实版本收敛。
- `delete-all` 在权威事务内关闭记忆、递增删除代次并进入 `purge_pending`，使事实、边和摘要立即不可用；异步 purge 清除摘要、派生边、无引用来源和旧任务内容，完成前拒绝重新启用。
- 模糊同槽位候选进入默认 30 天且可配置的 quarantine，不参与命令、召回或图；后续单一合格来源可触发重评，超期内容被净化。
- 每个请求冻结授权、owner/tenant、删除代次和 provider 状态快照；短期摘要与长期事实使用独立可配置 deadline。启动报告、运行时状态转移和 `/health` 使用同一状态源，状态日志只在真实转移时输出。
- `evals/memory/` 提供 runner、metrics 与四类版本化资产，并分别报告存储准确率、Recall/MRR/NDCG/HitRate、重复率、冲突处理、误记忆率、上下文精度和隔离失败率。

## 安全复核

- provider 每次操作都复核 owner lifecycle、tenant scope、action class 和 authorization epoch，缺失或陈旧授权 fail closed。
- 召回端对 adapter 返回结果再次执行 owner/tenant、活动状态、有效期、来源、index 状态、关系词表和注册表版本过滤；底层错误或跨 owner 结果不会进入上下文。
- source reference 冲突必须匹配既有 owner、tenant 和 source kind，防止跨 owner 复用来源 ID。
- 删除或最后来源失效会在同一事务中停止召回、失活活动边，并净化 subject、slot、fact 和 source links；tombstone 不保留事实正文。
- 确认 token 仅以 SHA-256 digest 存储，绑定 owner、operation、target、影响集合和有效期；状态漂移、过期、重放或跨 owner 使用均不执行操作。
- HTTP 错误与启动状态不输出事实正文、凭据、连接串或内部异常。

## Build 验证

- `python -m ruff check venagent tests evals`：通过。
- `python -m ruff format --check venagent tests evals`：80 files already formatted。
- `python -m compileall -q venagent tests evals`：通过。
- `python -m pytest -q`：154 passed，包含 10 项真实 PostgreSQL 集成测试。
- `npm.cmd run build`（`web/`）：`vue-tsc -b` 与 Vite production build 通过。
- `tests/test_persistence.py`：10 passed；覆盖 v7 重建、异步提取任务跨重启与幂等收敛、确认 token 跨重启、delete-all purge，以及既有 checkpoint、FastAPI、并发/取消/fencing。
- 新增聚焦测试覆盖摘要重建/后续纠正冲突压制/超时降级、quarantine 重评、提交失败和 TTL、后台重试耗尽/恢复、删除代次竞争、`index_pending` 恢复、provider 快照、权威读取失败、跨 owner 二次过滤、未知图关系和动态 health。
- `mypy`、`bandit`、`pip-audit` 与 `pylint`：当前虚拟环境未安装，未运行，未宣称通过。
- 真实 PostgreSQL 集成：`venagent-postgres-1` healthy，全部相关测试通过。

## Verify 重点

- 复核命令响应不会产生 `ConversationMessage`、`AgentRun` 或模型调用，确认 token 在 PostgreSQL 多连接场景下保持单次使用与状态漂移保护。
- 执行 G0 数据集并记录 Store、Recall、Context Assembly 和 G1 指标；安全硬门槛包括跨 owner/tenant 泄漏、deleted/superseded 注入、禁存内容写入和错误成功率均为零。
