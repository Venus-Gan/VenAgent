# M05 memory-context 完整目标规格

## 1. 目标

VenAgent SHALL 提供当前 conversation 的短期上下文治理和跨会话长期事实记忆，并把个人图记忆拆成可独立评测的阶段。记忆只在当前操作级 `MemoryAuthorization` 允许的范围内被提取、保存和召回；所有进入模型上下文的短期摘要与长期事实都必须带有可追溯来源。run 路径的 `MemoryAuthorization` 只能由有效 `ExecutionAuthorization` 派生，命令路径只能由已认证 session、活动 owner 和当前 authorization epoch 派生。

## 2. 用户可见结果

- 用户明确表达的稳定事实可以在后续相关对话中被召回。
- 当前 conversation 在上下文预算内保留最近完整 turn；较旧内容可以通过带原始消息范围的可重建摘要继续提供必要上下文，不能以逐条截断留下不完整对话。
- 用户偏好不被持久化；临时任务约束只在当前 conversation/run 范围内有效。
- 姓名、职业、所在地、负责项目等稳定身份信息不形成独立 profile；它们在通过来源、授权、敏感信息和稳定性过滤后，作为普通长期事实自动提取，并适用相同的冲突、删除和审计规则。
- 凭据、密钥、认证令牌和完整支付数据始终禁止持久化；首版特殊类别注册表只包含健康、财务、法律，第一方相关事实只有在用户明确要求“记住”时才可持久化。
- 用户明确要求长期记住偏好或人格化指令时，系统必须说明该内容不会持久化，仅在当前 conversation/task 中临时使用；不得回复虚假的“已记住”。
- 用户消息中的非敏感第三方个人事实可以形成自动记忆候选；事实保留第三方 subject，但记忆仍归当前 owner 私有。
- 第三方健康、财务、法律事实始终禁止持久化；当前 owner 的显式“记住”请求不能覆盖该禁令。其他类别按普通事实策略处理。
- M05 第一版的记忆仅对所属 owner 私有；tenant 是授权与隔离边界，不提供团队共享记忆。
- 用户消息及明确授权的工具结果/执行产物可以形成记忆候选；assistant 自由生成文本不能直接成为记忆事实。
- 当前任务步骤观察属于 LangGraph State/checkpoint 和后续 M07，不因 AGI-saber 使用 `TaskMem` 名称而进入 M05。M05 第一版不建设跨会话 episodic memory；未来只有独立评测证明收益后才重新进入 Shape。
- 被删除、撤销授权或来源失效的记忆不会继续进入上下文。
- 记忆不可用时，普通对话可以降级为无记忆运行；身份或授权校验失败时不得读取记忆。
- 普通对话自动执行长期记忆检索，但只有相关且合格的事实才加入上下文；没有合格候选时不注入空洞或低相关记忆。
- M05 不提供专用前端记忆页面、面板、列表、来源抽屉或使用徽标；用户通过命令查看和管理记忆及来源。特殊类别、冲突或不确定事实实际影响正文时，回答仍必须说明来源或不确定性。
- M05 提供 owner 级全局记忆开关。关闭后停止自动提取、显式写入、普通召回和上下文注入，但已有数据继续保留，管理命令仍可查看或删除；重新开启后恢复使用。
- durable/authenticated owner 的记忆默认启用且不发送首次写入提示；temporary/guest 不支持开启记忆，`/memory enable` 返回稳定 unsupported 结果且不得创建进程内或临时长期记忆。用户通过 `/memory status` 主动查看开关、处理状态与不可用原因。

## 2.1 记忆分层与 M05-S

- Working Memory：单个 AgentRun 的计划、步骤、工具执行现场和恢复状态由 LangGraph State/checkpoint 持有，后续 TaskMem 能力归 M07；M05-S 不复制或接管该权威。
- Conversation Short-term Memory：以当前 owner/conversation 的 `ConversationMessage` 为唯一消息权威。M05-S 按完整 turn、相关性和 token 预算选择近期消息，对更早消息生成带 owner、conversation、消息 ID 范围和策略版本的可重建派生摘要。
- Long-term Memory：M05-L 持有跨 conversation 的稳定事实、来源、生命周期和授权状态；M05-G1 只在活动长期事实之上建立个人记忆条目图。
- 短期摘要是可丢弃派生上下文，不能覆盖或替代 `ConversationMessage`，也不能直接成为长期事实、图节点或 `source_ref`。长期候选只能追溯到原始用户消息或明确授权的工具结果/执行产物。
- 近期消息与摘要合并后由类型化 source 形成 `ContextBlock`，并进入 `promptctx/` 的纯函数 ContextProjection；M05-S 不得绕过 section/global budget、授权、来源或敏感信息边界。
- 新消息明确纠正旧内容时，短期上下文必须压制冲突的旧摘要片段，不能把相互矛盾的旧摘要与近期消息同时注入模型。
- 摘要生成失败、超时或校验不通过时，普通回答降级为只使用预算内最近完整 turn；不得注入未验证摘要，也不得仅因摘要不可用阻塞当前回答。
- conversation 删除后，该 conversation 的短期窗口和派生摘要立即不可用并进入清除流程。conversation 删除本身不等于长期记忆来源撤销；M05 只保留不含原始消息正文的来源存根用于 provenance，已合法形成的长期事实仍根据显式来源撤销、最后来源失效、TTL 和用户删除规则治理。
- 成功回答发布后，M05-S 可以把原始用户消息及明确授权来源异步提交到 M05-L 候选流程；assistant 自由文本、短期摘要和最终 Prompt 不获得长期来源资格。
- `/memory disable` 后，当前用户输入仍作为必要模型输入，但此前 conversation 历史、M05-S 派生摘要、M05-L 长期事实和 G1 图邻居均不得进入上下文；启用后可从仍保留的原始 conversation 消息重建短期摘要。

## 3. 图记忆阶段

### G0：契约与评测准备

属于 M05 Shape，不实现运行时图遍历。图模型确定为记忆条目图：节点是长期记忆，首版活动边为 `FOLLOWS/SIMILAR_TO`。`FOLLOWS` 是同一 owner、tenant、source timeline 内从早到晚的有向关系，只连接按权威来源顺序相邻的活动记忆；消息来源以 conversation 为 timeline 并使用消息 sequence，授权工具结果以其可审计 execution timeline 与事件顺序为准，顺序相同时以活动时间和 memory ID 稳定决胜。`SIMILAR_TO` 是对称关系，以排序后的两个 memory ID 形成唯一规范化 pair。G0 冻结节点身份、边方向与生成规则、source reference、有效时间、可信度、冲突/quarantine/superseded、删除、授权和关系注册表版本语义，并建立可比较的评测样本格式。

### G1：事实图与 1-hop 召回

属于 M05 第一版 Build。每个活动节点引用一条长期记忆权威事实；`FOLLOWS` 只表达同一 owner、tenant、source timeline 中按上述稳定顺序相邻的早到晚关系，不连接跨 conversation 或跨 execution timeline 的记忆；`SIMILAR_TO` 表达超过已冻结阈值的对称语义相似。端点不再活动时，活动边立即失效但保留版本化审计事实。每条边必须保留关系注册表版本、来源、owner/tenant、有效状态和可审计 ID。未注册边类型不得写入活动图。G1 只扩展 seed 的直接一跳邻居，不实现实体事实图、任意多跳、自由本体推理或无来源结论。

G1 的 settings、facts、sources、生命周期、authorization epoch、deletion generation、单调 `authority_revision` 和 durable jobs 由 PostgreSQL 权威存储；Neo4j 是 M05 唯一的持久化边存储，并以 `applied_revision` 表示已完整提交的图版本。`MemoryStore` 必须在一个 PostgreSQL 只读 `REPEATABLE READ` transaction snapshot 中返回同一 owner/tenant 的权威数据与 `authority_revision`，独立 `MemoryGraphStore` 再读取与 owner/tenant、registry version、authority/applied revision 和 generation 完全匹配的 seed 直接邻边。Neo4j 单纯落后且 PostgreSQL snapshot 仍 current 时，application 丢弃整批边并退化为普通长期事实；形成上下文块前必须复核 authorization epoch、deletion generation 与当前 `authority_revision`，任一权威值变化、不一致或不可验证时整批长期事实/G1 候选为空。Neo4j `Memory` 节点只保存 memory ID、owner/tenant 和围栏等最小图元数据，不复制事实正文、来源正文或可逆摘要。

G1 图由 application 根据 PostgreSQL 权威 facts/sources 按 owner/tenant 全量确定性重建。save、add-source、replace、forget、revoke-source、quarantine resolve、expire、disable/enable、delete-all 与 owner delete 等所有图影响 mutation 必须在同一 PostgreSQL 权威事务内递增 `authority_revision` 并插入对应 durable job。Neo4j adapter 必须在修改图前 compare-and-set owner/tenant projection state：旧 revision 拒绝、同 revision 幂等 no-op、新 revision 才能在一个写事务中停用旧活动边、upsert 当前节点壳与边并提交 `applied_revision`；失败不得暴露半套新图。PostgreSQL durable projection jobs 负责冷重建、失败重试、running lease 恢复、重启恢复与删除清理；每次 claim 具有 attempt/lease fence，过期 worker、旧 epoch/generation/revision 的任务或 worker 必须作废。长期事实 ready 与 graph ready 分离：图投影失败只暂停 G1 图增益，不阻止满足既有资格和直接相关性门槛的事实普通召回。

### 后续图能力边界

M05 不继续产品化个人记忆 2-hop 或更深遍历。个人记忆图的受限编排如未来确有需求，由 M07 在独立 Shape 和稳定子图接口上评估；文档知识图谱的 2-3 hop 检索与证据推理由 M08 `rag-evidence` 负责。推理输出必须能够回溯到输入路径和原始来源，不能把模型生成结论直接写回 M05 事实图。

## 4. Mem0/OpenViking 边界

- Mem0 可作为候选提取、更新、去重和冲突分类的实现组件，但最终事实、授权、删除和审计由 VenAgent M05 持有。
- OpenViking 可作为层级上下文和资源组织组件，但不与个人事实图双写同一条权威事实。
- LangGraph checkpoint 只保存运行恢复所需的 State，不保存跨会话图事实。

## 4.1 记忆写入与治理基线

- 采用自动候选提取，不要求用户逐条确认；候选必须经过来源资格、owner/tenant 授权、敏感信息和事实稳定性过滤。
- 合格来源限于用户消息和明确授权的工具结果/执行产物；assistant 自由生成文本以及无来源摘要不得直接写为事实。
- 记忆合并采用 `ADD/UPDATE/DELETE/NOOP` 语义，不静默覆盖已有事实。
- 用户直接纠正事实且主体、事实槽位和纠正意图能够唯一确定时，系统自动执行 `UPDATE`，将旧事实标记为 `superseded` 并保留审计关联；无法唯一判断时，新候选进入 quarantine，不能与旧事实同时作为活动事实召回。
- quarantine 候选属于非活动内部状态：不进入普通召回、图扩展、用户命令结果或上下文。后台可以基于后续合格来源重新评估；只有该冲突会实质影响当前回答且无法安全判定时才提示用户。
- quarantine 候选使用可配置短期保留，默认 30 天。保留期内新合格来源可以触发重评；超期后必须物理清除候选内容，只保留不含内容的必要审计事实。
- 冲突和过期通过 `superseded`、`quarantine`、`expired` 等生命周期状态表达；只有冲突会实质影响当前回答且无法安全判定时，才向用户暴露不确定性。
- M05 必须通过命令接口提供查看、删除、撤销和来源追踪能力，命令仅返回文本结果，不要求新增专用前端 UI。
- 普通自动提取在回答发布后异步、幂等执行；状态命令必须能区分待处理、成功和失败，且下一次调用允许暂时不可见尚未完成的候选。
- 后台自动提取在重试耗尽后不得主动发送系统或 assistant 消息；失败只以安全净化摘要供 `/memory status` 按需读取，不得包含事实内容、原始输入或秘密。显式“记住”失败仍必须立即返回明确结果。
- 用户明确要求“记住”时，系统必须等待事实持久化成功后再确认；失败时不得假称已记住，并应返回可重试的明确结果。
- 删除操作先原子地使事实及关联活动边不可召回，再异步物理清除内容；审计只能保留不含原始事实、原始消息或可逆摘要的 tombstone。
- 自然语言“忘记 X”仅在唯一强匹配时执行上述删除语义并向用户确认目标已不可召回；多条候选时必须先展示最小必要信息供用户选择，零匹配时明确报告未找到且不得产生删除 tombstone。
- 稳定长期事实不使用统一的固定 TTL；时效事实必须记录 `valid_until` 或类别 TTL，到期后立即停止召回并进入清除流程。
- 一条事实可以关联多个合格来源。删除或撤销单个来源时，只要仍有其他有效来源，事实可以继续活动；最后一个有效来源失效时，事实及关联活动边必须同步停止召回并进入清除流程。
- 图中心性只可在低 importance 压缩/清理中充当保留信号；`valid_until`、`superseded`、用户删除、授权撤销和最后有效来源失效属于强制生命周期约束，任何中心性或 importance 都不得覆盖。
- 秘密与完整支付数据的禁存规则不可被用户的“记住”请求覆盖。首版特殊类别注册表只包含健康、财务、法律；第一方相关事实必须同时满足明确记忆意图、合格来源、owner 授权和其他安全过滤，其他类别按普通事实策略处理。
- 非敏感第三方事实遵循普通自动候选流程，但 subject identity 与 owner identity 必须分离，不能创建新的 owner、共享授权或跨 owner 召回路径。
- 第三方特殊类别事实必须在候选资格阶段拒绝，不能进入 quarantine、活动事实、图节点或 embedding/index。
- M05 第一版只允许 owner 私有读写；tenant 只参与隔离与授权校验，不存在 tenant/team 共享写入、提升或召回路径。
- owner 进入 deleting/deleted 时，其开关状态、来源存根、短期摘要、长期事实、派生索引和图边必须立即不可访问并由可重试维护流程异步清理；owner 删除的安全语义高于普通 conversation 删除。
- 全局记忆开关状态属于 M05 的 owner 级后端事实。关闭状态必须使短期历史 provider、长期 memory provider 和图 provider 返回明确 disabled/empty 结果并拒绝自动或显式写入，但不得阻止 owner 使用管理命令处理已有数据；当前用户输入仍可被当前 run 使用。
- owner 级全局开关只对 durable authenticated owner 开放；temporary/guest 的 `/memory enable` 必须返回稳定 unsupported 结果，不得创建可跨 conversation 使用的进程内记忆或临时长期事实。
- 默认启用过程不得创建系统提示、assistant 消息、ConversationMessage、AgentRun 或新的记忆候选事件。
- 当前 run 的进度、步骤观察与恢复现场由 LangGraph State/checkpoint 持有。M05 第一版不建设跨会话 episodic memory；若未来评测证明需要，必须以独立名称、类别和生命周期重新进入 Shape，不能复用 TaskMem 语义。
- M05 业务代码按 `venagent/memory/` 中的短期、`long_term/`、图、召回、管理、授权、jobs 和命令职责组织；通用上下文契约与投影位于 `venagent/promptctx/`。具体 memory adapters 位于 `venagent/repo/{temporary,postgresql}/memory/` 与 `venagent/repo/neo4j/memory_graph.py`，不得向 platform 加入长期事实、图或 Mem0/OpenViking 业务逻辑。

## 4.2 检索与注入门控

- 检索分为候选召回和上下文注入两阶段。`memory/recall.py` 采用较宽松阈值并优先保证 Recall；候选经过相关性重排后，只有通过严格注入阈值、授权、生命周期与来源检查，才由 `promptctx/recall_provider.py` 转为 `ContextBlock` 并接受全局上下文预算。
- 普通自动召回、用户明确回忆和特殊类别事实可以使用不同的版本化相关性档位；明确回忆可以扩大候选范围，但不能绕过权限、禁存、删除、有效期、来源或预算硬门槛。
- G1 的 1-hop 邻居不能仅凭图相连进入上下文，仍须重新通过相关性重排和注入门槛；`FOLLOWS` 不单独证明语义相关。
- Context Assembly 先构造 M05-S 的近期完整 turn 与有效摘要，再合并通过门控的 M05-L/G1 候选；所有块参与同一预算竞争，不能让长期记忆挤掉强制的当前请求和安全规则。
- 进入上下文的每条记忆保留可供命令检查的 source reference。普通回答不强制展开全部引用或显示记忆徽标；特殊类别、存在冲突或以不确定档位召回的事实影响正文时，必须在正文标记来源或不确定性。
- 阈值必须绑定 embedding、reranker、索引与评测集版本。G0 在按 owner 和时间线切分的数据上扫描阈值，选择满足上下文 Precision、安全硬门槛和延迟预算的最低注入阈值；组件版本变化后重新校准。

## 4.3 关系注册表

- G1 注册表的首版活动边只有 `FOLLOWS/SIMILAR_TO`，但可在后续 change 中通过显式新版本受控扩展，不是永久硬编码。
- `FOLLOWS` 必须按同一 owner、tenant、source timeline 的权威来源顺序生成有向边；`SIMILAR_TO` 必须按规范化 memory pair 与已冻结相似度规则生成对称边。两者都不接受模型自由生成的边类型；未注册边类型直接拒绝写入活动图。
- 注册表版本变更必须定义新增、别名、替换、弃用和迁移行为，并能在旧数据上回放验证。改变既有关系的方向、作用域、生成规则或含义必须创建新版本并报告迁移后的召回与错误变化，不得原地改写旧边语义。
- `CAUSES/BELONGS_TO` 只作为未来候选，不得因 AGI-saber 声明了名称就视为已实现；进入活动注册表前必须有真实数据和召回收益证据。
- M08 文档知识图谱拥有独立关系体系，不复用 M05 的个人图关系注册表。

## 4.4 命令表面与模块所有权

- M05 使用现有对话输入中的稳定 `/memory` 斜杠命名空间，命令返回纯文本，不建设专用前端 UI；已确认的自然语言“忘记 X”继续可用。
- `/memory list`、`/memory show`、`/memory status`、`/memory update`、`/memory forget`、`/memory revoke-source`、`/memory disable`、`/memory enable` 和 `/memory delete-all` 由确定性命令 adapter 解析，直接调用 M05 application use case，不创建普通用户消息、AgentRun 或模型调用。命令 adapter 必须从已认证 session、活动 owner、tenant 解析和当前 authorization epoch 派生操作级 `MemoryAuthorization`，不得伪造 run 或 conversation 字段。
- `/memory disable` 关闭自动提取、显式写入、普通召回和上下文注入，但不删除数据；`status/list/show/forget/revoke-source/delete-all` 在关闭状态仍可用，`update` 必须与其他写入一样被拒绝。`/memory enable` 恢复读写与召回。显式“记住”在关闭状态必须明确失败，不能暂存后静默补写。
- `/memory disable` 还会阻止此前 conversation 历史和 M05-S 摘要进入当前 run 的上下文；它不删除原始 conversation 消息。`/memory enable` 后，短期摘要可从仍有效的消息重建。
- `/memory list` 首次调用不带参数，按活动时间倒序、memory ID 稳定决胜返回固定 20 条活动事实的稳定 ID 与短摘要；存在下一页时返回 owner 绑定、不可读且不含事实内容的 opaque cursor，以及下一条完整命令 `/memory list <cursor>`。cursor 被篡改、跨 owner 使用、格式无效或携带额外参数时返回稳定错误且不返回数据；不提供页大小参数。
- `/memory show <id>` 返回规范化事实、活动状态、有效期和 source reference。`list/show` 都不得复制完整原始消息、deleted 内容、quarantine 内容或秘密。
- `/memory forget <memory_id>` 只接受当前 owner 可管理的精确活动记忆 ID。缺失或额外参数、owner 不匹配、目标不存在或目标非活动时返回稳定错误且不执行删除；成功时先使该事实及关联活动边不可召回，再异步物理清除内容。自由文本删除只通过自然语言“忘记 X”入口执行唯一强匹配、候选选择和零匹配保护。
- `/memory update <id> <fact>` 只接受当前 owner 可管理的活动事实 ID。命令内容作为新的用户来源重新执行来源资格、授权、敏感信息、稳定性和冲突检查；成功后创建新事实版本，将旧版本标为 `superseded` 并保留审计关联。禁止修改既有事实或来源内容，记忆关闭时必须拒绝该写入。
- `/memory revoke-source <source_ref>` 撤销当前 owner 可管理的指定来源。若会影响多条活动事实，第一次调用只返回最小影响摘要和 owner 绑定、短期有效、单次使用的确认 token；确认时重新校验来源状态和影响集合后再执行。仍有其他有效来源的事实继续活动；失去最后有效来源的事实及关联边立即不可召回并进入清除流程。
- 多事实来源撤销的确认语法固定为 `/memory revoke-source <source_ref> <token>`；其他位置、缺失或额外参数必须返回确定性语法错误，不执行撤销。
- 来源撤销 token 不授予其他来源、事实读取、修改、登录或整库删除权限；过期、重放、owner 不匹配或影响集合发生安全相关漂移时必须失败并要求重新确认。
- `/memory delete-all` 第一次调用只返回 owner 绑定、5 分钟有效、单次使用的确认 token；只有同一 owner 在有效期内再次提交才执行。确认后先原子地使全部长期事实、活动边和短期派生摘要不可用，再异步物理清除内容；长期事实与边不提供恢复。
- `delete-all` 的确认语法固定为 `/memory delete-all <token>`；其他位置、缺失或额外参数必须返回确定性语法错误，不执行删除。
- `/memory delete-all` 确认后同时使当前 owner 的 M05-L/G1 长期事实、活动边和 M05-S 派生摘要立即不可用并异步清除；不删除 `ConversationMessage` 原始消息，重新启用记忆后允许从这些消息重建短期摘要。
- `delete-all` token 不授予登录、读取、单条修改或其他操作权限；过期、重放、owner 不匹配和状态漂移必须返回稳定安全错误且不删除数据。
- 命令 adapter、HTTP/chat transport 或未来 CLI 只负责协议解析、授权上下文传递、错误映射和文本呈现，不拥有记忆事实、生命周期、来源、图关系或删除语义。
- M06 后续可以按其工具注册、策略、OperationGrant、审批和审计边界，把 M05 application port 包装成 agent tool；这属于新增调用入口，不把记忆业务权威迁移到 M06。
- 只有至少两个已实现能力形成稳定复用时，后续 change 才能抽取通用命令解析/分派模块；M05 不预建共享命令 package、registry 或空 adapter。

## 4.5 预计实现表面

- `venagent/memory/` 是 M05 feature package，预计按模型、port、策略、短期、长期、图、上下文和命令职责拆分。Build intake 可以合并没有独立复杂度的文件，但不得把这些职责重新集中到单一平台 adapter。
- `venagent/repo/` 持有 PostgreSQL、Neo4j 及其他已选择的 feature adapters。M05 SHALL 提供专属 `repo/neo4j/memory_graph.py`；它与未来 M08 只共享 `platform/neo4j/` driver/runtime，不共享 label、schema、关系注册表、adapter、查询或生命周期。没有真实消费者、依赖或测试的空 adapter 禁止进入 Build。
- `venagent/repo/temporary/` 的 state、ownership、conversation/run 与 memory adapters 继续服务 temporary/test，行为与 PostgreSQL port 对齐；`platform/` 不持有这些 feature adapters。
- 预计修改现有 Agent context/runtime、composition root、conversation 输入协调、平台 migration、严格配置和 HTTP schema/route；所有 transport 保持薄层，M05 application use case 不依赖具体 adapter。
- 不新增记忆前端页面、面板或列表。现有聊天 store 只在必要时处理不持久化的 `/memory` 纯文本结果；已有展示足够时不新增 Vue 组件。
- 聚焦的 pytest 覆盖短期、长期、持久化、命令、上下文、图和安全；正式离线评测 runner、metrics 和数据集归 `evals/memory/`，不得成为运行时依赖。

## 4.6 降级与恢复契约

### 4.6.1 目标与状态

- M05 必须保证增强记忆故障不阻塞普通回答，同时保证授权、隔离、删除和生命周期约束不会因降级被绕过。
- 能力状态按 provider 或能力独立维护：`healthy`、`degraded`、`recovering`、`disabled`、`unavailable`、`purge_pending`。用户主动关闭与系统故障不能合并为同一个状态。
- `/memory status` 可以返回状态、净化后的错误摘要和同步积压；普通回答、前端页面和自动消息不显示技术降级提示。

### 4.6.2 读取路径

- Context Assembly 按“当前输入 → 最近完整 turn → 已验证摘要 → M05-L 事实 → OpenViking 扩展 → G1 一跳邻居”逐层构造。
- 摘要失败或校验不通过时只回退最近完整 turn；`ConversationMessage` 不可读时只使用当前输入并进入近似无状态模式。
- 长期事实权威存储不可读时省略 M05-L/G1；OpenViking 不可用时只有在 Build 已实现独立核心事实检索的前提下才回退，否则返回空长期记忆。
- Embedding/reranker 故障只有在该检索回退已被实际实现和评测时才可使用关键词路径；不能为了降级契约预建未选择的检索依赖。
- Neo4j 未配置时 M05-G1 为 disabled；已配置但不可用、读取失败或 `applied_revision` 落后于 snapshot `authority_revision` 时省略 G1 并标记 degraded/pending，普通长期事实继续。图返回的候选仍须重新通过权威事实状态、来源、owner/tenant、有效期、删除代次、authority/applied revision 和上下文预算过滤；请求末权威 revision 已变化时普通事实也必须整批丢弃。
- 首版不使用无法重新验证生命周期的事实内容缓存。任何 provider 读取失败只能省略对应层，不能直接放宽 `ContextProjection` 门控。

### 4.6.3 请求一致性与时限

- 每个请求绑定一次操作级 `MemoryAuthorization`、owner/tenant 作用域、删除 generation 和记忆状态快照；请求中途 provider 恢复不得混合不同快照的结果。`MemoryAuthorization` 必须携带 owner、tenant、允许的数据范围、允许的动作类别、authorization epoch、来源类型以及适用的 run/conversation/session reference；provider 执行前必须校验所需 scope/action 和当前 owner epoch，缺失或不匹配时 fail closed。
- provider 使用独立的可配置 deadline，并受总记忆上下文预算和 Agent 端到端延迟预算约束；具体数值由 Build intake 和 G0 评测冻结。
- `promptctx/assembler.py` 中的 ContextProjection 仍是确定性纯函数，只接收已经完成授权、生命周期和相关性校验的 `ContextBlock`，不承担重试、熔断或外部 I/O。

### 4.6.4 写入、重试与投影

- 自动提取在回答发布后异步执行；Mem0、OpenViking、Embedding、Neo4j 图写入或索引同步失败不得阻塞回答。
- 自动任务使用 `source_ref + policy_version + operation` 等稳定幂等键，重试采用退避和熔断；每次重试前重新校验记忆开关、owner、来源、生命周期和删除 generation。事实提取等普通任务可以在重试上限后进入 failed；projection/purge/owner-cleanup 必须持续有界退避至成功、被更高 revision/generation supersede 或明确取消，不能因固定次数耗尽而永久阻断恢复或删除。
- 重试耗尽只记录安全的后台状态，不创建系统提示、assistant 消息、`ConversationMessage`、`AgentRun` 或新的记忆候选。
- 长期事实采用“PostgreSQL 权威事实先提交、派生索引后同步”。权威事务成功即形成事实版本；Mem0/OpenViking/向量索引/Neo4j 图边是可重放投影。
- 事实检索 readiness 与 graph projection readiness 必须分离。派生图未完成时记忆版本可通过管理命令查看，并可在存在可验证直接检索路径时参与普通事实召回；`graph_pending` 只暂停 G1 图增益，不得复用事实 `index_pending` 把已合格事实整体隐藏，也不改变 `active/quarantine/superseded/deleted` 生命周期。
- 图投影 job 绑定 owner/tenant、authorization epoch、deletion generation、目标 `authority_revision` 和 registry version；job 必须与对应图影响 mutation 在同一 PostgreSQL 事务内提交。恢复重放不得重复创建事实、版本、索引或活动边，已撤销、过期、删除、关闭或旧 revision 的任务/worker 必须作废。
- projection/purge/owner-cleanup job 由 lifespan 管理的独立 memory maintenance consumer 领取，不依赖 AgentRun 调度。多进程 consumer 使用数据库 lease 与 claim fence 协调；异常必须以净化 reason code 更新健康状态并限流记录，不能静默吞掉，shutdown 必须停止领取并释放 worker/Neo4j 资源。
- TTL 到期扫描按受影响 owner/tenant 有界分批，在权威事务中同时失活事实、递增各自 `authority_revision` 并插入 projection job；不得继续直接改 PostgreSQL edge，也不得跨全部 owner 形成无界事务。

### 4.6.5 命令、关闭与删除

- 显式“记住”、`update`、`forget`、`revoke-source`、`disable`、`enable` 和 `delete-all` 只有权威事务成功后才能报告成功；权威存储不可用时返回明确失败。
- `/memory disable` 持久化失败时当前请求立即停止历史、摘要、长期事实和图注入，但必须报告全局关闭未持久化成功；不能声称已完成全局关闭。
- `/memory enable` 在 `purge_pending` 期间拒绝执行，避免旧 generation 数据重新进入上下文。
- `delete-all` 确认事务原子写入关闭状态、`purge_pending` 和递增的删除 generation；旧 generation 的长期事实、活动边和短期派生摘要立即不可召回。
- `delete-all` 随后异步清理 Mem0、OpenViking、向量索引和 Neo4j 图投影；generation 不匹配的后台任务直接作废。即使 Neo4j 暂时不可用，递增后的权威 generation 也必须立即阻止旧图召回。原始 `ConversationMessage` 不因该命令删除，清理完成后重新启用才允许重建短期摘要。

### 4.6.6 不可降级的安全边界

- owner/tenant 隔离、授权、秘密禁存、特殊类别策略、删除状态、来源撤销、`valid_until`、`superseded` 和最后有效来源状态无法确认时必须 fail closed。
- 降级不得把 assistant 自由文本、派生摘要、未授权工具输出或陈旧索引提升为长期来源。
- 不得通过中心性、importance、缓存或“最新结果优先”覆盖强制生命周期和删除约束。

### 4.6.7 启动与运行时可观测性

- M05 复用现有 `StartupReport`/`InfrastructureStatus` 启动报告，在 Neo4j driver open/受限 connectivity probe 完成后，于终端逐项显示 M05-S 短期记忆、M05-L 长期事实、提取/索引投影和 M05-G1 图能力的 `READY/DEGRADED/DISABLED/FAILED` 状态、reason code 和安全运维文案；不得在 probe 前冻结一个虚假的 graph ready 快照。
- 启动探测只执行连接、认证、schema/version 和能力检查，不调用 LLM 生成文本，不写入记忆，不读取或输出用户事实；每个可选 provider 并行探测并受有界超时约束。
- 未配置或未选择的能力是 `DISABLED`；已配置但探测失败、超时或版本不兼容时，仍能提供安全部分能力的组件是 `DEGRADED`，完全无法提供该组件能力的是 `FAILED`。只有现有 `required` 标记为真的组件失败才阻止应用启动；其他组件失败按契约降级并明确不可用能力。权威 SQL 不可用时沿用临时/无状态启动语义，并明确 M05-L 与持久化短期记忆不可用。
- 启动快照不代表任意 owner 的全局开关；owner 级 `/memory disable` 只通过 `/memory status` 返回，不进入全局基础设施日志。
- 全局 provider health 映射为 `InfrastructureStatus`，供启动终端和 `/health` 共享；`disabled/purge_pending/index_pending` 等 owner 或数据级状态只进入授权后的 `/memory status`，不得泄漏到全局健康接口。
- 运行时 provider 故障或恢复只记录限流后的状态转移日志，不按请求重复打印；provider 状态转移、启动快照和 `/health` 必须来自同一份基础设施状态源，启动报告本身仍是 lifespan 时形成的不可变快照。
- 多 worker/多进程可各自输出一次启动报告；实现必须明确进程级重复是预期行为，不能产生每请求重复日志或敏感内容。

## 5. 非目标

- 持久化用户偏好或隐式人格画像。
- 对偏好或人格化指令的显式“记住”请求作虚假持久化确认。
- 专用前端记忆页面、面板、列表、来源抽屉、状态视图或使用徽标。
- 把记忆事实、生命周期或删除权威迁移到 M06 工具模块，或为未来能力预建通用命令模块。
- tenant/team 共享记忆或把 owner 私有记忆提升为共享记忆。
- 在 M05 第一版建设 episodic memory 或当前任务 TaskMem。
- 把 conversation 短期摘要变成独立消息权威、跨会话 episodic memory，或把当前任务执行状态迁入 M05-S。
- M05 拥有 M08 的 RAG 文档、RAG evidence 向量索引或共享知识图谱。M05 可以通过 adapter 使用只服务于个人记忆的派生检索索引，但该索引不成为事实权威。
- 在 PostgreSQL、文件或进程内状态中保留 durable edge fallback、shadow copy 或双写路径；non-durable graph test double 只用于测试或明确的非持久运行。
- 把 PostgreSQL `memory_edges` 迁移或复制到 Neo4j。Neo4j 初始图只从权威 facts/sources 冷重建，重建完成前 G1 安全退化为普通长期事实。
- M05 建设实体事实图。
- 任意深度图遍历、自动本体构建、无证据的模型推理和自动写回。

## 6. 评测与验收

### 6.1 数据集契约

- 评测样本按 owner 和时间线组织，而不是把单条消息随机切分。
- 每条时间线包含输入事件、各时间点的 gold memory state、probe query、允许召回事实、禁止召回事实和预期生命周期动作。
- 困难样本至少覆盖否定、假设、转述他人、临时信息、assistant 无来源断言、工具授权差异、冲突更新、实体别名、TTL、删除和跨 owner 相似事实。
- 已检查的 `memory_store_eval_dataset_1000.csv` 只能作为 Store 层种子：共 1000 行、213 条唯一 dialogue、934 行位于重复组，12 组相同文本标签冲突。任何训练/校准/验证切分必须按唯一 dialogue 分组，不能按行随机切分。
- 原数据中的 141 条 `preference` 按 VenAgent 契约映射为 `REJECT_PREFERENCE`，109 条 `episodic` 映射为 `OUT_OF_SCOPE`；其余与 M05 基本一致的 750 行只有 161 条唯一 dialogue，不能单独代表真实对话分布。
- 导入时保留 `source_label` 并增加 `venagent_expected_action`；未确认再分发许可前不提交原始下载文件，只提交许可明确且经过审查的派生样本或使用本地路径运行。
- Recall gold 样本至少包含 `owner_id`、`eval_time`、`query`、`relevant_memory_ids`、`forbidden_memory_ids` 和 `expected_fact`；时间线样本还必须记录各时间点活动、superseded、quarantine、expired 和 deleted 状态。

### 6.2 分层指标

- Store：候选 Precision/Recall/F1、`ADD/UPDATE/DELETE/NOOP` 动作准确率、来源归因准确率、不可记忆内容误写率。
- Subject policy：偏好显式请求正确拒绝率、健康/财务/法律三类第一方显式意图识别率、非敏感第三方事实提取 Precision/Recall、第三方 subject 归因准确率和错误 owner 映射率。
- Third-party safety：第三方特殊类别事实候选、quarantine、活动存储、图节点和索引写入率均必须为零。
- Safety：禁存秘密误写率、特殊类别未经明确请求写入率和跨 owner/tenant 访问率；三项均作为硬门槛。
- Consolidation：重复合并率、冲突状态准确率、旧事实残留率、TTL 失效率和删除传播完整性。
- Correction and deletion：明确纠正自动替代准确率、模糊纠正 quarantine 准确率、新旧事实同时活动率、自然语言删除唯一匹配准确率、歧义误删率和零匹配误删率。
- Quarantine：活动召回泄漏率、用户命令结果泄漏率、后台重评准确率、来源链完整率和不必要对话提示率。
- Quarantine retention：默认 30 天边界、配置覆盖、保留期内重评和超期内容清除完整性。
- Lifecycle：稳定事实误过期率、时效事实到期残留率、多来源保留正确率、最后来源失效传播完整性，以及中心性错误覆盖强制生命周期约束的次数。
- Recall：Precision@K、Recall@K、MRR、NDCG、过期/删除事实召回率和 owner/tenant 泄漏率。
- Threshold calibration：候选 Recall、注入 Precision、阈值覆盖率、空结果率、错误注入率，以及普通召回、明确回忆和图邻居三类档位的差异。
- Context Assembly：相关事实覆盖、上下文精度、矛盾数量、token 利用率、记忆 provider 延迟和降级结果。
- Degradation/Recovery：provider 单点/组合故障下的回答完成率、各能力降级比例、deadline 超时率、恢复耗时、重试积压、投影同步延迟和降级后的 Recall/Context Precision 损失；事实 `index_pending` 与 `graph_pending` 必须独立可观测且不能改变生命周期判断。
- Degradation safety：陈旧/删除/过期/superseded 事实注入率、跨 owner/tenant 泄漏率、恢复重放重复事实/边率、删除或关闭后后台任务复活率、显式命令错误成功率均为零容忍硬门槛。
- Startup/Observability：启动各能力状态与 reason code 的准确率、终端与 `/health` 状态一致率、启动探测超时边界、可选依赖故障下的启动成功率、敏感信息/事实正文日志泄漏率、运行时状态转移去重率和多 worker 日志行为。
- Short-term Context：完整 turn 保留率、窗口预算确定性、摘要 source-range 完整率、摘要事实一致性、纠正后旧摘要冲突泄漏率、摘要失败降级成功率、conversation 删除传播完整性，以及摘要/assistant 文本成为长期来源的次数（必须为零）。
- Command and transparency：命令授权正确率、来源追踪完整率、无专用前端 UI 约束，以及特殊类别、冲突和不确定事实影响正文时的披露完整率。
- Command ownership：斜杠命令确定性解析、无意外消息/run/模型调用、M05 application port 复用，以及未来 M06 wrapper 不改变记忆权威。
- Global switch：关闭后当前输入仍可处理但历史 conversation、短期摘要、长期事实和图邻居均不注入；写入被拒绝而管理命令仍可用，停用本身不删除数据；temporary/guest 的 enable 拒绝率必须为 100%；`delete-all` 同时清理长期事实/边与短期派生摘要但保留原始消息，重新启用后的摘要重建正确。
- Command privacy and deletion：静默默认启用无提示事件、`list/show` 最小内容、固定 20 条活动时间倒序分页、owner 绑定 opaque cursor、`forget` 精确活动 ID、deleted/quarantine 不可见、`delete-all` token 的 owner 绑定/过期/重放防护，以及确认后的立即失效和异步清除。
- Command update：新用户来源归因、新版本与 `superseded` 关联完整率、资格/敏感/冲突/授权检查覆盖率、关闭状态拒绝率和原地覆盖次数（必须为零）。
- Background extraction failure：重试耗尽后的主动消息率（必须为零）、安全错误摘要可用率、摘要敏感内容泄漏率（必须为零），以及显式“记住”失败的即时反馈完整率。
- Source revocation：最小影响摘要准确率、确认 token 的 owner 绑定/过期/重放防护、影响集合重校验、多来源保留正确率和最后来源失效向事实及关联边的传播完整性。
- Graph Expansion：最小记忆节点引用完整性、事实/来源正文未复制率、同一 owner/tenant/source timeline 内早到晚相邻 `FOLLOWS` 的正确率、规范化对称 `SIMILAR_TO` 的 Precision/Recall、边 owner/tenant 隔离、1-hop 路径命中、相对普通事实召回的增益、authority/applied revision 与 generation fencing、乱序 worker 拒绝和注册表版本兼容性。未来新增或完善语义边时，必须使用新注册表版本，并增加关系映射准确率、未知关系比例、错误关系类型率、迁移回放和新版本召回变化。

未知关系比例是诊断指标，不以越低越好为目标；必须结合错误映射率和通用关系滥用情况解释。

### 6.3 基线和阶段门槛

- G0 至少建立无记忆、最近 N 条消息、普通事实记忆和 G1 1-hop 四组可重放基线；OpenViking provider 实际接入后增加对应组合基线。
- M05-S 至少比较最近 N 条消息、完整 turn 预算窗口、完整 turn + 派生摘要三组可重放基线，并记录上下文精度、事实覆盖、冲突和 token 成本；摘要质量不能只用平均生成分抵消来源或删除违规。
- 权限、跨 owner/tenant、删除和来源约束是硬门槛，不能用平均质量分抵消失败。
- `valid_until`、`superseded`、用户删除、授权撤销和最后来源失效均为硬门槛；中心性带来的召回收益不能抵消任何生命周期违规。
- G1 优先保证事实与边精度，具体数值阈值在 G0 gold set 完成后冻结，不能为了通过 Verify 临时下调。
- M05 的评测终点是 G1 1-hop；M08 的 2-3 hop 收益与错误路径必须在 M08 自身的知识图谱基线和数据上验证，不复用 M05 个人事实图准入结论。
- LLM Judge 只能辅助判定模糊语义；事实、边、路径、权限、删除和生命周期以确定性 gold label 为主。
- 可选 provider 故障时普通回答完成率应保持为 100%；摘要失败必须成功回退完整 turn。该门槛不适用于 Agent 模型本身或权威对话存储不可用的情况，但这些情况必须有明确的无状态/失败结果。
- 安全硬门槛包括跨 owner/tenant 泄漏率、deleted/expired/superseded/quarantine 注入率、关闭或删除后的后台复活率、恢复重放重复事实/边率和显式命令错误成功率均为零。
- 权威事实事务成功但 Neo4j 图投影失败时，验收必须区分事实保存成功、普通事实召回可用、G1 图增益暂不可用和投影恢复收敛，不能以“所有 adapter 同步”作为隐含事务条件。

### 6.4 验收方向

- 事实提取资格、来源、冲突、删除和 owner/tenant 隔离可测试。
- 当前 conversation 的完整 turn 窗口、摘要来源、纠正、降级和删除行为可重放测试，且不改变 LangGraph State 与长期事实的权威边界。
- G1 的 1-hop 召回在预算内稳定、可解释并可降级；真实 PostgreSQL + Neo4j 验证冷重建、权威 mutation 与 revision/job 原子提交、Neo4j 单事务替换、authority/applied revision 漂移、N/N+1 乱序、重启恢复与删除清理，活动代码和 schema 不再读写或要求 `memory_edges`。
- 每个 provider 的超时、空响应、格式错误和组合故障都能按层省略，不绕过 `ContextProjection`；权威存储、授权或 owner/tenant 校验失败时能安全关闭。
- 自动提取故障恢复后按幂等键收敛，不重复创建事实、版本、索引或边；删除、撤销、TTL 到期和关闭期间产生的旧任务不能复活数据。
- `disable`、`enable`、`delete-all` 和显式记忆命令在权威事务失败、`index_pending`、`purge_pending` 和 token 重放场景下返回真实、稳定的纯文本结果。
- `/memory delete-all <token>`、`/memory revoke-source <source_ref> <token>` 和 `/memory forget <memory_id>` 只接受精确参数位置；缺失、额外参数、过期、重放或 owner/目标不匹配均不得执行操作。`/memory list` 只接受零个参数或一个 owner 绑定 cursor，固定返回最多 20 条。
- run 与命令两条入口都必须生成等强度的 `MemoryAuthorization` 并通过 owner/tenant/scope/action/epoch 测试；命令入口不得创建或伪造 `AgentRun`。
- 启动时能够对已选择的记忆能力输出一次逐项终端状态；未配置能力映射为 `DISABLED`，安全部分可用映射为 `DEGRADED`，组件完全不可用映射为 `FAILED`，且只有 `required` 组件失败阻止启动；启动探测不产生模型调用、记忆写入或敏感日志。
- 启动时终端报告与 `/health` 初始状态同源一致；运行时故障与恢复由同一 provider 状态源更新 `/health` 并产生限流状态转移日志，不要求回写已经输出的启动快照；多 worker 不按请求重复输出。
- M07/M08 后续图能力只有在各自 Shape 与真实数据中相对所属模块基线有明确收益时才允许进入实现，不得在 M05 预建多跳代码或准入资产。
- 所有评测报告区分存储、召回、整合、上下文组装和图扩展错误。

### 6.5 评测资产与分阶段执行

- `evals/memory/` 至少包含可复现 runner、metrics，以及 `store_policy_v1`、`timelines_v1`、`recall_gold_v1`、`graph_gold_v1` 四类版本化数据集；评测代码调用 M05 application port，不以直接改库或只测 adapter 代替业务链路。
- M05-S 比较无历史、最近 N 条消息、完整 turn 预算窗口和完整 turn + 摘要；硬门槛覆盖完整 turn、预算确定性、摘要来源范围、纠正冲突抑制、失败降级、disable/delete-all 和摘要不得提升为长期来源。
- M05-L 比较 Store policy、普通事实召回和生命周期时间线；硬门槛覆盖动作分类、来源、禁存、owner 隔离、TTL、superseded、quarantine、删除和最后来源传播。
- Recall 复用 RAG 的 Recall@K、MRR、NDCG@K 和 HitRate@K 方法，但 gold 单位是 memory ID，并额外记录 forbidden recall rate、owner/time 边界和最终 Context Precision。
- G1 使用 graph gold 测 source timeline 内有向相邻 `FOLLOWS` 正确率、规范化对称 `SIMILAR_TO` Precision/Recall、边隔离、注册表版本迁移回放、1-hop 相对普通长期事实召回的增益，以及 recall snapshot 一致性、epoch/generation 失效和图降级；M05 不建立 2-hop 准入数据或通过结论。
- Degradation gold 在相同 owner/time-line 上记录 provider 故障点、预期降级层、允许/禁止召回事实、预期命令结果、重试 generation 和恢复收敛状态；故障注入不得只测 adapter 返回错误而绕过 M05 application port。
- Startup/health gold 记录依赖配置、探测结果、预期 `InfrastructureState`、reason code、终端报告、`/health` 响应和运行时状态转移；必须覆盖未配置、超时、schema 不兼容、部分可用、恢复和多 worker 场景。
- 端到端生成未稳定前，RAGAS、LLM Judge、5000/10000 轮压力曲线和固定质量总分只作延后项；首版可以运行 100/500/1000 事件的确定性时间线以验证状态传播，不得把未运行项写成通过。
- 完整对照顺序为无历史、最近 N 条消息、完整 turn 窗口、完整 turn + 摘要、短期 + 普通长期事实、短期 + 长期事实 + G1 1-hop。Dense/BM25/Hybrid 只比较 Build 实际实现的检索方式，不为评测本身引入未选择的产品依赖。

## 7. 已确认的阶段边界

- M05 个人图记忆与 M08 RAG 知识图谱完全分离，分别维护事实、权限、来源和评测。
- M05 个人图记忆采用 G0 契约/评测准备与 G1 事实图/1-hop 召回两阶段，M05 不产品化 2-hop 或更深遍历。
- 个人图推理不属于 M05 G1；未来个人图编排由 M07 独立评估，RAG 知识图谱 2-3 hop 由 M08 负责。
- M05-S 负责 conversation 短期上下文，M05-L/G1 负责长期事实与个人记忆条目图；M07 继续负责 Working Memory/TaskMem，跨会话 episodic memory 仍需未来独立评测后重新进入 Shape。
