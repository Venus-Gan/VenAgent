# Outcome

在 VenAgent 现有运行基础上交付 M05 `memory-context`：补齐当前 conversation 的短期上下文治理，提供可授权、可追溯、可删除的长期事实记忆，并以分阶段方式引入个人图记忆。第一版不追求完整图推理，而是先建立可靠的短期窗口与摘要、长期事实、来源、生命周期和评测边界。

# Scope

- M05-S 会话短期记忆：以 `ConversationMessage` 为权威来源，按完整 turn、相关性和 token 预算选择近期消息；较旧消息可以形成带消息范围来源、可重建的派生摘要，并作为 `ContextBlock` 参与当前 conversation 的上下文组装。
- M05-L 长期事实记忆：候选、提取资格、去重、召回、TTL/importance、冲突、quarantine、superseded、审计和删除。
- 个人图记忆采用记忆条目图并阶段化交付：本 change 只交付 G0 契约/评测准备与 G1 `FOLLOWS/SIMILAR_TO` 记忆节点图和 1-hop 召回；G2 有界 2-hop 必须在 G1 真实 Verify 后通过后续 change 重新进入，G3 由后续 M07/M08 在稳定子图/evidence 接口上引入受限图推理或知识图谱多跳。
- 用户消息及明确授权的工具结果/执行产物可作为提取来源；assistant 自由生成文本不得直接成为记忆事实来源。
- 姓名、职业、所在地、负责项目等稳定身份信息不形成独立 profile，而是在通过来源、授权、敏感信息和稳定性过滤后，作为普通长期事实自动提取。
- 凭据、密钥、认证令牌和完整支付数据不得进入长期记忆；首版特殊类别注册表只包含健康、财务、法律，第一方相关事实只有在用户明确要求“记住”时才可持久化。
- 用户明确要求“记住”偏好或人格化指令时，系统明确说明不会长期保存，只在当前 conversation/task 中临时使用。
- 用户消息中的非敏感第三方个人事实可以进入自动候选提取，但仍属于当前 owner 的私有记忆并保留原始主体与来源。
- 第三方健康、财务、法律事实始终不持久化，即使当前 owner 明确要求“记住”也拒绝写入；其他类别按普通事实策略处理。
- M05 第一版只提供 owner 私有记忆；tenant 参与授权与隔离，不形成共享记忆空间。
- M05 不建设专用前端记忆页面、面板、列表或使用徽标；查看和管理能力通过返回文本结果的命令接口提供。
- 当前任务工作记忆、步骤观察和恢复现场由 LangGraph State/checkpoint 持有并归后续 M07；M05-S 只治理 conversation 短期上下文。M05 第一版不建设跨会话 episodic memory，未来只有独立评测证明收益后才能重新进入 Shape。
- G1 使用固定核心关系集和版本化关系注册表；首版只有 `FOLLOWS/SIMILAR_TO`，未注册边类型不得写入活动图。
- 将真实对话数据接入记忆评测，区分明确事实、临时信息、不可记忆内容和错误召回。
- 通过由 run 授权或已认证命令会话派生的 `MemoryAuthorization` 与现有 `ContextProjection` 边界提供 owner/tenant 隔离、预算控制和降级行为。

# Non-goals

- 不持久化用户偏好，不实现 profile/preference memory。
- 不把 LangGraph State、ConversationMessage 或 Prompt 当作长期记忆权威。
- 不把会话派生摘要建设成第二份消息权威，也不让 M05-S 接管当前任务步骤、计划、工具执行现场或 LangGraph checkpoint。
- 不在 M05 实现 RAG 文档知识图谱；RAG evidence、文档图谱和知识图谱多跳归属 M08。
- 不拥有 M08 的 RAG 文档、RAG evidence 向量索引或共享知识图谱；M05 可以通过 adapter 使用仅服务于个人记忆的派生检索索引，但其不成为事实权威。
- 不在 G1 实现任意深度遍历、自由形式本体推理或无来源的 LLM 结论。
- 不提前创建没有真实消费者的 M06/M07/M08 provider、目录或占位 adapter。
- 不在 M05 第一版提供 tenant/team 共享记忆或单条记忆的共享提升。
- 不因用户显式请求而持久化偏好或人格化指令，也不以“已记住”虚假确认当前任务临时上下文。
- 不新增前端记忆管理页面、状态面板、记忆列表、来源抽屉或“使用了记忆”徽标。
- 不提前把记忆权威迁移给 M06 工具模块，也不在只有 M05 一个消费者时创建通用命令模块或共享命令框架。
- 不把长期事实、图关系或 Mem0/OpenViking adapter 塞入现有 `venagent/infra/platform/memory.py`；该文件当前只代表平台数据的进程内 adapter。

# Acceptance examples

- 用户明确陈述的稳定事实可以被抽取为带来源的记忆候选，未授权或低可信内容不会进入 owner 的记忆上下文。
- 当前 conversation 在预算内优先保留最近的完整 turn，不因逐条截断而留下孤立的用户消息或 assistant 回答；更早内容由带原始消息 ID 范围的派生摘要补充。
- 短期摘要必须可从仍有效的 `ConversationMessage` 重建，不能覆盖原始消息；新消息明确纠正旧内容时，上下文不得同时注入相互冲突的旧摘要与新事实。
- 短期摘要生成失败或校验不通过时，系统降级为只使用预算内的最近完整 turn，不得注入未验证摘要或阻塞普通回答。
- 删除 conversation 后，该 conversation 的短期窗口和派生摘要不再可用；已经基于合格原始用户消息或授权工具来源形成的长期事实仍按自己的来源撤销和删除规则治理，不能把摘要本身冒充长期来源。
- 成功回答发布后，M05-S 可以把原始用户消息及明确授权来源异步送入 M05-L 候选流程；assistant 自由文本和派生摘要不得因此获得长期事实来源资格。
- 姓名、职业、所在地和负责项目等稳定身份事实与其他长期事实使用相同的提取、授权、冲突、删除和审计规则，不建立隐式偏好画像。
- 同一记忆事实或图边的更新会保留来源和历史状态，并通过 `superseded` 或 `quarantine` 表达冲突，不静默覆盖。
- G1 只返回授权范围内的 1-hop 子图；跨 owner、tenant 或已删除来源的边不会被召回。
- M05 provider 超时可以降级省略记忆，但身份和授权失败必须 fail closed。
- 记忆上下文进入 `ContextProjection` 后受 section/global budget 约束，并保留 source reference。
- 评测能够分别报告存储准确率、召回质量、重复率、冲突处理、误记忆率、上下文精度和隔离结果。
- assistant 生成的无来源断言不会被提取；明确授权的工具结果可以生成带执行来源的候选。
- 未注册边类型不会成为活动边；注册表升级能够回放旧边并报告兼容性与召回变化。
- 自动提取在回答发布后异步、幂等执行；用户明确要求“记住”时，只有持久化成功后才能确认完成。
- 用户删除记忆后，该内容立即不可召回；物理内容异步清除，审计仅保留不含原始内容的 tombstone。
- 稳定事实不因统一年龄阈值自动过期；时效事实到达 `valid_until` 或类别 TTL 后立即停止召回并进入清除流程。
- 删除或撤销来源后，只要还有有效来源就保留派生记忆；最后一个有效来源失效时，记忆及其关联边立即不可召回。
- 图中心性只能保护记忆免于低 importance 的压缩清理，不能覆盖有效期、替代状态、用户删除、授权撤销或来源失效。
- 凭据、密钥、认证令牌和完整支付数据即使来自用户明确请求也不会持久化；特殊类别个人事实只有明确要求“记住”且其他安全边界通过时才可持久化。
- 普通请求采用宽松候选召回和严格上下文注入；不相关事实不会为了填满 Top-K 而进入上下文，显式回忆也不能绕过授权与生命周期硬门槛。
- 用户明确、可唯一定位的事实纠正会自动生成 `UPDATE`，旧事实转为 `superseded`；无法唯一判断的冲突进入 quarantine，不让新旧事实同时保持活动。
- 自然语言“忘记 X”只有在唯一强匹配时才执行删除；多条候选必须先由用户选择，无匹配时明确报告未找到。
- 普通回答不显示前端记忆标记；用户通过命令检查记忆及来源。特殊类别、冲突或不确定事实影响正文时仍必须显式说明来源或不确定性。
- quarantine 候选不参与召回、不出现在用户命令结果中并由后台重新评估；只有它会实质影响当前回答且系统无法安全判定时才提示用户。
- quarantine 候选默认最多保留 30 天且期限可配置；期间新合格来源可以触发重评，超期后物理清除内容。
- 记忆命令使用现有对话输入中的稳定 `/memory` 斜杠命名空间并返回纯文本，继续兼容已确认的自然语言“忘记 X”。
- M05 提供 owner 级全局记忆开关。关闭后停止自动提取、显式写入、召回和上下文注入，但保留已有数据；管理命令仍可查看、忘记、撤销来源或删除全部，重新开启后恢复使用。
- 全局开关选 C：关闭后仍处理当前用户输入，但不向模型注入此前 conversation 历史、M05-S 派生摘要或 M05-L/G1 长期记忆；`/memory delete-all` 同时使长期事实和短期派生摘要不可用并异步清除，原始 conversation 消息不因该命令删除，重新启用后允许从仍保留的消息重建短期摘要。
- durable/authenticated owner 的全局记忆默认启用且不发送首次写入提示；temporary/guest 不支持开启记忆，`/memory enable` 必须明确拒绝，用户只能通过 `/memory status` 主动查看状态与不可用原因。
- `/memory list` 按活动时间倒序固定每页 20 条，首次调用不带参数，后续使用 owner 绑定的 opaque cursor：`/memory list <cursor>`；响应在存在下一页时返回下一条完整命令。`/memory show` 返回规范化事实、状态、有效期和 source reference，不复制完整原始消息，也不暴露 deleted 内容或 quarantine。
- `/memory forget <memory_id>` 只接受当前 owner 可管理的精确活动记忆 ID；缺失、额外参数、owner 不匹配或目标非活动时返回稳定错误且不执行删除。自由文本删除继续使用自然语言“忘记 X”的唯一匹配与歧义保护流程。
- `/memory delete-all` 使用 owner 绑定、5 分钟有效的两步确认；确认后全部长期事实、活动边和短期派生摘要立即不可用并异步物理清除。长期事实与边不可恢复；原始 conversation 消息不被删除，重新启用后可以重建短期摘要。
- `/memory update <id> <fact>` 把命令内容作为新的用户来源重新执行资格、敏感信息、冲突和授权检查；成功后创建新版本并将旧版本标记为 `superseded`，不允许原地覆盖。
- 后台自动提取重试耗尽时不产生主动消息；`/memory status` 只显示不含事实内容、原始输入或秘密的安全错误摘要。显式“记住”失败仍立即返回明确结果。
- `/memory revoke-source <source_ref>` 影响多条活动事实时先返回最小影响摘要和 owner 绑定的短期确认 token；确认后撤销来源，仍有其他有效来源的事实继续活动，失去最后有效来源的事实及关联边立即不可召回。
- `delete-all` 的确认调用固定为 `/memory delete-all <token>`；多事实来源撤销的确认调用固定为 `/memory revoke-source <source_ref> <token>`，token 仍须 owner 绑定、短期有效、单次使用并在执行前重校验状态。
- 可选记忆 provider 故障时按层降级：摘要失败回退最近完整 turn，图存储失败省略 G1，长期事实不可验证时省略 M05-L/G1；普通回答不因增强记忆故障阻塞。
- 身份、授权、owner/tenant 隔离和删除状态无法确认时必须 fail closed；不得使用无法重新验证生命周期的旧事实缓存。
- 每个请求使用一致的记忆状态快照；provider 受独立 deadline 和总记忆预算约束，恢复发生在请求中途时不得混合新旧结果。
- 自动提取失败采用有界、幂等、可重放的异步重试；重试前重新校验开关、owner、来源、生命周期和删除代次，耗尽后不得创建消息、AgentRun 或主动提示。
- 显式记忆命令只有权威事实事务成功后才能报告成功；权威事实成功但派生索引未完成时标记 `index_pending`，不得把索引待同步误报为完整召回可用。
- `/memory disable` 持久化失败时当前请求立即停止记忆注入但明确报告未持久化成功；`/memory enable` 在 `purge_pending` 期间拒绝执行。
- `/memory delete-all` 先原子增加删除代次并使长期事实、活动边和短期派生摘要立即不可用，再异步清理派生存储；代次不匹配的后台任务必须作废，原始 `ConversationMessage` 不删除。
- `/memory status` 只展示开关、能力状态、净化后的错误摘要和同步积压，不展示事实正文、原始输入、秘密或内部堆栈；普通回答不显示技术降级提示。
- 故障注入评测必须覆盖 provider 超时、权威存储故障、索引部分失败、恢复重放、删除/撤销与重试竞争，以及跨 owner 返回结果的二次过滤。
- M05 启动状态复用现有 `StartupReport`，在终端逐项显示短期记忆、长期事实、提取/索引和 G1 图能力的 `READY/DEGRADED/DISABLED/FAILED` 状态及安全原因；不输出连接串、凭据、原始输入或事实正文。
- 启动探测只执行连接、认证、schema/version 和能力检查，不调用 LLM 生成文本或写入记忆；可选 provider 探测并行且受有界超时约束，不阻塞应用启动。
- 运行时 provider 故障和恢复只记录限流后的状态转移日志；终端启动快照、运行时能力状态和 `/health` 必须来自同一份状态模型。
- 未配置/未选择的能力显示为 `DISABLED`；已配置且仍能提供安全部分能力时显示为 `DEGRADED`，完全无法提供该组件能力时显示为 `FAILED`，是否阻止应用启动由现有 `required` 标记决定。owner 级 `/memory disable` 不进入全局启动日志，只通过 `/memory status` 查看。

# Constraints and invariants

- LangGraph 只拥有单个 AgentRun 的工作记忆、State/checkpoint；`ConversationMessage` 是 conversation 短期记忆的权威来源；M05-L 拥有跨会话长期事实。三者不得互相复制业务权威。
- 会话短期摘要是可丢弃、可重建的派生上下文，必须记录 owner、conversation、覆盖的消息 ID 范围、生成策略版本和来源状态；Prompt 文本不成为其权威来源。
- 短期窗口必须按完整 turn 和确定性预算规则选择；摘要与近期消息合并后仍统一进入纯函数 `ContextProjection`，不能绕过 section/global budget。
- 长期候选提升必须追溯到原始用户消息或明确授权工具来源；会话摘要、assistant 自由文本和已经拼装的 Prompt 均不得成为新的 `source_ref`。
- 记忆 provider 必须接收完整的操作级 `MemoryAuthorization`，不能只接收 `owner_id`。run 路径只能从已验证的 `ExecutionAuthorization` 派生，命令路径只能从已认证 session、活动 owner 和当前授权 epoch 派生；两条路径都必须携带 owner、tenant、允许的数据范围、允许的动作类别、授权 epoch 和来源类型，命令路径不得伪造 `run_id` 或创建 `AgentRun`。
- 提取、授权、召回、超时和降级由异步 collector/provider 负责；`ContextProjection` 保持纯函数和确定性。
- 每条事实和关系都必须能指向权威 `source_ref`，Prompt 文本不成为新的权威副本。
- 个人图记忆和 RAG 知识图谱使用不同的 owner、权限、TTL、删除和评测边界。
- 固定关系类型是版本化受控词表，不是永久硬编码；增加、替换或移除关系类型必须通过后续 change 产生新注册表版本，保留可重放的版本、迁移语义和召回变化证据，不得静默改写既有边的含义。
- 生命周期强约束的优先级高于图排序信号：`valid_until`、`superseded`、用户删除、授权撤销和最后有效来源失效均不得被中心性或 importance 覆盖。
- 记忆作用域固定为 owner 私有；tenant 只作为强制隔离维度，任何跨 owner 召回均 fail closed。
- 检索和注入使用分离阈值：候选召回优先保证 Recall，注入优先保证 Precision；阈值必须随 embedding、reranker 和索引版本通过 G0 评测冻结，不能依赖永久硬编码的相似度常量。
- 纠正和删除都是可审计的记忆命令：明确纠正保留被替代版本，明确删除先使目标不可召回；语义歧义不能通过“最新优先”或批量近似匹配绕过。
- 第三方事实的 subject 与记忆 owner 必须分离：允许保存第三方事实不改变 owner 私有授权边界，也不能把第三方身份映射为新的 owner。
- quarantine 是非活动内部状态，不出现在用户命令结果、普通召回或图扩展中；后台重新评估也必须保留原始来源与审计链。
- `/memory` 只是 M05 应用用例的协议 adapter：解析和返回文本不拥有记忆事实。未来 M06 可以把同一用例暴露为受控 agent tool，但 M05 继续拥有事实、生命周期、授权过滤和删除语义。
- 全局开关状态是 M05 持有的 owner 级后端事实，不依赖前端控件。关闭状态不能阻止 `status/list/show/forget/revoke-source/delete-all` 管理命令，但必须拒绝普通召回、自动写入、显式“记住”和 `update`。
- owner 级全局开关只对 durable authenticated owner 开放；temporary/guest 的 `/memory enable` 必须返回稳定的 unsupported 结果，不得创建进程内或临时长期记忆。
- 默认启用不产生系统提示、assistant 消息或可提取事件；`/memory status` 是查看开关与后台处理状态的权威命令表面。
- `delete-all` 确认 token 只授权当前 owner 的单次整库删除确认，不是会话、记忆读取或其他操作的授权凭据；过期、重放或 owner 不匹配必须失败。
- `/memory update` 是追加新来源和新版本的纠正命令，不得修改既有事实或既有来源内容；全局记忆关闭时与其他显式写入一样必须拒绝。
- 全局记忆关闭时，当前请求仍是模型的必要输入，但历史 conversation blocks、M05-S 摘要、M05-L 事实和 G1 邻居均不得进入 `ContextProjection`；启用后只能从仍有效的原始 conversation 消息重新构建摘要。
- 后台自动提取失败摘要必须经过安全净化并只由 `/memory status` 按需读取；重试耗尽不得创建系统提示、assistant 消息、ConversationMessage、AgentRun 或新的记忆候选。
- 来源撤销确认 token 只授权当前 owner 对指定 `source_ref` 的单次撤销；必须短期有效、防重放，并在执行前重新校验影响集合和来源状态。多来源保留与最后来源失效规则不得被批量操作绕过。
- 增强 provider 的读取失败只能导致对应上下文层省略，不能绕过 `ContextProjection` 的授权、生命周期和预算过滤；没有可验证权威状态时禁止使用事实内容缓存。
- 记忆能力按 `healthy/degraded/recovering/disabled/unavailable/purge_pending` 独立报告；用户主动 `disabled` 与系统故障不可混淆。
- 长期事实采用权威存储先提交、派生索引异步同步；`index_pending` 是投影同步状态，不改变 `active/quarantine/superseded/deleted` 生命周期语义。
- 所有异步重试使用 `source_ref + policy_version + operation` 等稳定幂等键，并在执行前检查 owner、开关、来源状态和删除 generation，防止恢复后重复或复活。
- 删除、撤销、过期和替代先在权威存储中立即停止召回，再清理 Mem0、OpenViking、向量索引和图边；派生清理失败不得恢复可见性。
- conversation 删除不等于长期记忆来源撤销：M05 只保留不含原始消息正文的来源存根用于 provenance，事实继续按显式来源撤销、最后来源失效、TTL 和用户删除治理。
- owner 进入 deleting/deleted 时，其 M05 开关、来源存根、短期摘要、长期事实、派生索引和图边必须立即不可访问并异步清理；owner 删除的安全语义高于普通 conversation 删除。
- 启动报告是基础设施能力快照，不代表所有 owner 的记忆开关状态；运行时状态变化必须通过同一状态源更新健康接口和操作日志。
- 全局 provider health 映射为 `InfrastructureStatus` 并供终端与 `/health` 使用；`disabled/purge_pending/index_pending` 等 owner 或数据级状态只进入授权后的 `/memory status`，不得泄漏到全局健康接口。
- 多 worker 场景允许每个服务进程输出一次启动报告，但不得按请求重复输出；状态转移日志必须限流并保留安全 reason code。
- 只有至少两个已实现能力形成稳定复用时，才能在后续 change 抽取通用命令解析/分派模块；M05 不为未来命令预建共享空壳。
- M05 业务能力预计放在 `venagent/memory/`，短期、长期、图、上下文和命令按职责拆分；外部实现放在 `venagent/infra/memory/`。现有 `venagent/infra/platform/memory.py` 在 Build 中按行为保持不变的方式拆为平台 in-memory state/ownership/runtime adapter，不能与 Agent 长短期记忆混为同一模块。
- 未经用户确认的产品行为不进入 Build；本 change 在 Shape 阶段先冻结共享理解。

# Expected implementation surface

- 新增 `venagent/memory/`，预计包含 `models.py`、`ports.py`、`policy.py`、`short_term.py`、`long_term.py`、`graph.py`、`context.py` 和 `commands.py`；文件可在 Build intake 中按真实复杂度合并，但短期、长期、图、上下文和命令职责不得重新塞回单一大文件。
- 新增 `venagent/infra/memory/`，预计包含 PostgreSQL、Mem0、OpenViking adapter；`neo4j.py` 只有在 Build intake 最终选择 Neo4j 后才创建，不预建空 adapter。
- 现有 `venagent/infra/platform/memory.py` 预计行为保持地拆为 `venagent/infra/platform/in_memory/state.py`、`ownership.py` 和 `runtime.py`，继续只承载 owner/session/conversation/run 的进程内实现。
- 预计修改 `venagent/agent/context.py`、`venagent/agent/runtime.py`、`venagent/bootstrap.py`、`venagent/conversation/service.py`、平台 migrations、严格配置加载、HTTP routes/schemas 和 `pyproject.toml`；最终以实际依赖关系和最小变更为准。
- 前端不新增记忆页面；仅在现有 `web/src/modules/chat/store.ts` 必要时增加 `/memory` 临时纯文本结果处理，不把命令结果持久化为普通消息或 run。若现有消息呈现已经足够，不修改 `ChatWorkspace.vue`。
- 新增聚焦测试预计包括短期窗口、长期治理、持久化、命令、上下文、图、安全和评测 harness；评测资产放在 `evals/memory/`，不进入运行时业务 package。

# Decisions

- [confirmed] 放弃持久化用户偏好功能；当前对话中的临时约束仍可作为 conversation/task context 使用。
- [confirmed] M05 先交付事实记忆和 G1 个人图记忆，G2 多跳必须以 G1 的真实评测结果为进入门槛。
- [confirmed] 图推理不属于 G1/G2；个人记忆图推理由后续 M07 消费稳定子图，RAG 知识图谱推理由 M08 负责。
- [confirmed] 沿用 AGI-saber/Mem0 风格的自动候选提取与 `ADD/UPDATE/DELETE/NOOP` 合并，不要求用户逐条确认。
- [confirmed] 冲突默认通过 `superseded/quarantine/expired` 等状态后台治理；只有影响当前回答且无法安全判定时才提示用户。
- [confirmed] M05 通过命令接口提供查看、删除、撤销和来源追踪能力；OpenViking 负责层级上下文资源，Mem0 负责候选提取/更新辅助，二者都不替代 VenAgent 的事实权威存储。
- [confirmed] 只有用户消息和明确授权的工具结果/执行产物具备自动提取资格；assistant 自由生成文本不得直接写成长期事实。
- [confirmed] G1 采用固定核心关系集和版本化受控扩展；未知关系进入候选/quarantine，模型不得动态创建活动关系类型。
- [confirmed] M05 G1 采用 AGI-saber 风格的记忆条目图，节点是长期记忆，首版活动边只有 `FOLLOWS/SIMILAR_TO`；不在 M05 建设实体事实图。
- [confirmed] TaskMem 保持当前任务语义并归后续 M07/LangGraph State；M05 第一版不建设 episodic memory，仅保留未来以独立评测重新进入 Shape 的可能。
- [confirmed] M05 新增 M05-S 会话短期记忆：以 `ConversationMessage` 为权威，负责完整 turn 窗口、可重建摘要、token 预算、来源和 `ContextBlock` 组装；当前任务工作记忆/TaskMem 仍归 M07，跨会话 episodic memory 仍不属于 M05。
- [confirmed] 会话短期摘要不是第二份消息权威，也不能成为长期事实来源；长期候选只能追溯原始用户消息或明确授权的工具来源。conversation 删除会清除短期派生上下文，但合法形成的长期事实继续按其独立来源规则治理。
- [confirmed] 新记忆业务按 `venagent/memory/` 和 `venagent/infra/memory/` 分离；现有过重的 `venagent/infra/platform/memory.py` 只做行为保持的结构拆分，不承载 M05 长期事实或图逻辑。
- [confirmed] 预计实现表面采用 feature package、infra adapter、平台 in-memory 拆分、聚焦测试和 `evals/memory/` 评测资产；具体文件允许在 Build intake 中按实际复杂度合并，但不得破坏已确认的模块所有权与不创建空 adapter 约束。
- [confirmed] 姓名、职业、所在地、负责项目等稳定身份信息作为普通长期事实自动提取，不建设独立 profile memory；它们仍须通过来源、授权、敏感信息和稳定性过滤。
- [confirmed] 删除采用立即逻辑失效、异步物理清除内容的语义；删除后不得召回，只保留不含原始内容的审计 tombstone。
- [confirmed] 普通自动提取在回答发布后异步、幂等完成；用户明确要求“记住”时，系统等待持久化成功后再确认，失败必须明确反馈。
- [confirmed] 稳定长期事实不设置统一固定 TTL；时效事实必须带 `valid_until` 或类别 TTL，到期后立即停止召回并进入清除流程。
- [confirmed] 派生记忆可以保留多个有效来源；删除或撤销单个来源时继续保留仍有依据的记忆，最后一个有效来源失效时同步使记忆及关联边不可召回并进入清除流程。
- [confirmed] 图中心性只可保护记忆免于低 importance 的压缩/清理，不得覆盖 `valid_until`、`superseded`、用户删除、授权撤销或来源失效。
- [confirmed] 凭据、密钥、认证令牌和完整支付数据始终禁止持久化；首版特殊类别注册表只包含健康、财务、法律，第一方相关事实只有在用户明确要求“记住”时才可持久化，第三方相关事实始终禁存，其他类别按普通事实策略处理。
- [confirmed] M05 第一版只支持 owner 私有记忆，tenant 仅作为授权和隔离边界，不提供 tenant/team 共享记忆。
- [confirmed] 普通对话自动检索长期记忆，但只将达到相关性阈值且通过授权、生命周期、来源与预算过滤的候选加入上下文；阈值采用宽松召回、严格注入，并由 G0 评测按模型/索引版本冻结。
- [confirmed] 用户直接纠正既有事实时，主体、事实槽位和纠正意图明确则自动 `UPDATE` 并将旧事实标为 `superseded`；无法唯一判定时进入 quarantine。
- [confirmed] 自然语言“忘记 X”在唯一强匹配时执行删除并确认结果；存在多条候选时先让用户选择，没有匹配时明确报告未找到。
- [confirmed] 撤回前端记忆使用标记和来源检查 UI；M05 不建设专用前端记忆界面，普通回答保持简洁，记忆及来源通过命令查看；特殊类别、冲突或不确定事实影响回答时仍在正文明确来源或不确定性。
- [confirmed] 用户明确要求“记住”偏好或人格化指令时，系统明确说明不会长期保存，只在当前 conversation/task 中临时使用，不虚假回复“已记住”。
- [confirmed] 用户消息中的非敏感第三方个人事实可以自动提取；记忆仍归当前 owner 私有，事实保留第三方 subject 与来源。
- [confirmed] quarantine 候选对用户隐藏且不参与召回，只由后台重新评估；仅当它会实质影响当前回答且无法安全判定时才提示用户。
- [confirmed] 第三方健康、财务、法律事实始终不持久化，显式“记住”请求也不能覆盖该禁令；首版不把其他类别加入特殊类别注册表。
- [confirmed] quarantine 使用可配置短期保留，默认 30 天；新合格来源可在保留期内触发重评，超期后物理清除内容。
- [confirmed] 记忆管理采用现有对话输入中的稳定 `/memory` 斜杠命令并返回纯文本，同时兼容自然语言“忘记 X”；提供已确认的 owner 级全局开关及其管理子命令。
- [confirmed] 提供 owner 级全局记忆开关；`/memory disable` 停止自动提取、显式写入、召回和上下文注入但保留数据，`status/list/show/forget/revoke-source/delete-all` 仍可管理已有数据，`/memory update` 与其他写入一样被拒绝，`/memory enable` 恢复使用；停用与删除全部是独立操作。
- [confirmed] Q34=C：`/memory disable` 后仍处理当前用户输入，但不注入此前 conversation 历史、M05-S 派生摘要、M05-L 事实或 G1 邻居；`/memory delete-all` 同时清除长期事实和短期派生摘要，但不删除原始 conversation 消息；重新启用后可从仍保留的消息重建短期摘要。
- [confirmed] durable/authenticated owner 的记忆默认启用但不发送任何首次写入提示；temporary/guest 不支持开启记忆，`/memory enable` 返回稳定 unsupported 结果且不得创建进程内或临时长期记忆，状态由 `/memory status` 主动查看。
- [confirmed] `/memory list` 只分页展示活动事实的 ID 与短摘要；`/memory show` 展示规范化事实、状态、有效期和 source reference，不复制完整原始消息，也不展示 deleted 内容或 quarantine。
- [confirmed] `/memory delete-all` 采用 owner 绑定、5 分钟有效的两步确认；确认后长期事实、活动边和短期派生摘要立即不可用并异步物理清除。长期事实与边不可恢复；原始 conversation 消息不被删除，重新启用后可以重建短期摘要。
- [confirmed] 提供 `/memory update <id> <fact>`；命令内容作为新的用户来源重新通过资格、敏感信息、冲突和授权检查，成功后生成新版本并将旧事实标为 `superseded`，绝不原地覆盖。
- [confirmed] 后台自动提取重试耗尽后不主动发送消息，只在 `/memory status` 中显示安全错误摘要；显式“记住”失败仍立即反馈。
- [confirmed] `/memory revoke-source <source_ref>` 影响多条活动事实时，先返回最小影响摘要和 owner 绑定的短期确认 token；确认后撤销来源，保留仍有其他有效来源的事实，并立即停用失去最后来源的事实及关联边。
- [confirmed] 两步确认采用短参数语法：`/memory delete-all <token>` 和 `/memory revoke-source <source_ref> <token>`；首次调用仍不执行高风险操作，token 继续绑定 owner/目标、短期有效、单次使用并在确认时重校验状态。
- [confirmed] 记忆采用逐层降级契约：增强 provider 失败时省略对应摘要、长期或图层，普通回答继续；身份、授权、owner/tenant 隔离、删除状态无法确认时 fail closed，首版不使用无法重新验证生命周期的事实缓存。
- [confirmed] 每个请求使用一致的记忆状态快照和有界 provider deadline；自动提取采用有界幂等重试，重试前重新检查开关、来源、生命周期和删除 generation，重试耗尽不产生主动消息或新 run。
- [confirmed] 显式记忆命令采用权威事实先提交、派生索引后同步；权威事务成功但索引待恢复时记录 `index_pending`，不得虚假报告完整召回可用。
- [confirmed] `/memory disable` 持久化失败时当前请求立即停止记忆注入但明确报告失败；`/memory enable` 在 `purge_pending` 期间拒绝。`delete-all` 先原子增加删除 generation 并立即停用长期事实、活动边和短期派生摘要，再异步清理，generation 不匹配的后台任务作废且不删除原始 `ConversationMessage`。
- [confirmed] `/memory status` 只返回能力状态、开关、净化错误摘要和同步积压，不展示事实正文、原始输入、秘密或堆栈；普通回答不显示技术降级提示。
- [confirmed] 记忆启动可观测性复用现有 `StartupReport`：终端逐项显示 M05-S/M05-L/提取与索引/G1 的健康状态和安全原因；启动探测只做连接、认证、schema/version 与能力检查，不能调用 LLM 或写入记忆。运行时故障/恢复采用限流状态转移日志，终端快照、运行时状态和 `/health` 使用同一状态模型；未配置能力为 `DISABLED`，安全部分可用为 `DEGRADED`，组件完全不可用为 `FAILED`，是否阻止启动由 `required` 决定，owner 级关闭不写入全局启动日志。
- [confirmed] `/memory forget <memory_id>` 只接受当前 owner 的精确活动记忆 ID；自由文本删除继续走自然语言“忘记 X”的唯一匹配、候选选择和零匹配流程。
- [confirmed] `/memory list` 使用固定 20 条、活动时间倒序的 owner 绑定 opaque cursor；首次调用不带参数，后续调用为 `/memory list <cursor>`，不提供页大小参数。
- [confirmed] 启动状态按能力实际可用性区分：未配置为 `DISABLED`，存在安全部分能力为 `DEGRADED`，该组件完全不可用为 `FAILED`；是否阻止应用启动继续由 `required` 决定。
- [confirmed] G1 `FOLLOWS` 仅连接同一 owner、tenant、source timeline 中按权威来源顺序相邻的活动记忆，方向为早到晚；`SIMILAR_TO` 是对称关系。后续可以通过新关系注册表版本扩展或完善，但改变既有语义必须经过后续 change、迁移、回放和召回验证，不能静默覆盖旧边。
- [confirmed] M05 使用操作级 `MemoryAuthorization` 消除无 run 命令与 `ExecutionAuthorization` 的结构冲突；run 路径和已认证命令路径分别受等强度的 owner、tenant、scope、action、authorization epoch 与来源校验，命令不创建或伪造 `AgentRun`。
- [confirmed] 2026-08-05 已最终确认包含精确 ID 删除、固定 cursor 分页、分级启动状态、G1 关系语义与版本化扩展、`MemoryAuthorization` 的修订后完整契约。
- [confirmed] 2026-08-05 已最终确认当前 brief 与完整目标规格的共享理解；按用户要求暂不执行 Shape → Build transition。

# Open questions

- 无。

# Verification expectations

- Shape 阶段验证规格能区分 M05 个人记忆、LangGraph State 和 M08 RAG evidence。
- Build 阶段覆盖正常、失败、超时、删除、冲突、owner/tenant 隔离和预算竞争。
- Verify 阶段运行项目 pytest 及真实数据评测；未安装依赖或未运行的检查必须如实记录。
- G2/G3 必须有对照实验，证明多跳或推理相比 G1/Hybrid baseline 的收益和新增错误。
- 评测数据按 owner 和时间线切分；每条时间线包含事件、各时间点 gold memory state、probe query、允许召回和禁止召回事实，避免随机消息切分造成泄漏。
- Store 层记录候选 Precision/Recall/F1、`ADD/UPDATE/DELETE/NOOP` 准确率、来源归因和不可记忆内容误写率。
- Store 层将禁存秘密误写率、特殊类别未经明确请求写入率和 owner 作用域错误作为硬门槛。
- Store 层覆盖偏好显式请求的诚实降级、非敏感第三方事实提取，以及第三方 subject 与 owner 隔离。
- Store 层将第三方特殊类别事实写入率作为零容忍硬门槛，并覆盖显式“记住”也被拒绝的路径。
- Consolidation 层记录重复合并、冲突状态、旧事实残留、TTL 失效和删除传播完整性。
- Consolidation 层还需覆盖多来源引用计数、最后有效来源失效、强制生命周期优先级，以及中心性保护仅作用于低 importance 清理的边界。
- Consolidation 层还需验证明确纠正的自动替代、模糊纠正进入 quarantine、新旧事实不会同时活动，以及自然语言删除的唯一匹配和歧义保护。
- Consolidation 层验证 quarantine 对用户和召回隐藏、后台重评不丢失来源，以及只有影响当前回答时才触发提示。
- Consolidation 层验证 quarantine 默认 30 天保留、配置覆盖、新来源重评和超期物理清除。
- Recall 层记录 Precision@K、Recall@K、MRR、NDCG、过期/删除事实召回及 owner/tenant 泄漏；权限、删除和来源约束是硬门槛。
- Recall 阈值在按 owner/时间线切分的验证集上扫描，选择满足上下文精度与硬门槛的最低注入阈值；embedding、reranker 或索引版本变化后必须重新校准。
- Context Assembly 层记录相关事实覆盖、上下文精度、矛盾数量、token 利用率、延迟和降级行为。
- Short-term Context 层验证完整 turn 窗口、预算确定性、摘要消息范围来源、摘要可重建性、纠正后的冲突抑制、摘要失败降级、conversation 删除传播，以及摘要/assistant 文本不会成为长期来源。
- Command/Context 层验证无专用前端记忆 UI、命令结果的授权与来源追踪，以及特殊类别、冲突和不确定事实的正文披露。
- Command/Context 层验证 `/memory` 命令确定性分派到 M05 用例、不触发不必要模型调用，并证明未来 M06 wrapper 不改变 M05 权威所有权。
- Command/Context 层验证全局关闭时普通读写均停止、管理命令仍可用、显式“记住”明确失败，以及停用与删除全部不会混淆。
- Command/Context 层验证 temporary/guest 的 `/memory enable` 始终返回稳定 unsupported 结果且不创建任何进程内或临时长期记忆。
- Command/Context 层验证静默默认启用不产生提示消息、`list/show` 的内容最小化与分页，以及 `delete-all` token 的 owner 绑定、过期、重放、长期事实不可恢复清除和短期摘要可重建边界。
- Command/Context 层验证 `/memory list` 固定 20 条、活动时间倒序、owner 绑定 opaque cursor、下一条完整命令、篡改/跨 owner cursor 拒绝，以及 `/memory forget <memory_id>` 的精确 ID、参数数量、owner 和活动状态边界。
- Command/Context 层验证 `MemoryAuthorization` 只能由有效 run 授权或已认证命令会话派生，两条路径都执行 owner/tenant/scope/action/epoch 校验，命令路径不创建或伪造 `AgentRun`。
- Command/Context 层验证 `/memory update` 会建立新用户来源和新版本、重跑资格/敏感/冲突/授权检查、旧版本转为 `superseded`、关闭状态拒绝写入且不存在原地覆盖。
- Command/Context 层验证后台自动提取重试耗尽不会产生主动消息或新 run，只在 `/memory status` 暴露安全净化后的错误摘要；显式“记住”失败仍即时可见。
- Command/Context 层验证来源撤销的最小影响摘要、owner 绑定短期 token、过期/重放/状态漂移，以及多来源保留和最后来源失效向事实与关联边的完整传播。
- Command/Context 层验证 `/memory delete-all <token>` 与 `/memory revoke-source <source_ref> <token>` 的精确参数位置；缺失、额外参数、过期、重放和 owner/目标不匹配均不得执行操作。
- Degradation/Recovery 层验证 provider 单点和组合故障、权威存储不可用、陈旧索引二次过滤、恢复重放、删除/撤销/TTL 与重试竞争、generation 防复活、`index_pending` 状态和显式命令的真实失败结果；可选 provider 故障不得阻塞普通回答，安全边界失败必须零泄漏、零错误成功。
- Startup/Observability 层验证启动终端逐项状态、可选依赖并行有界探测、不泄漏凭据/事实、运行时故障与恢复的限流转移日志、多 worker 启动行为，以及启动快照、运行时状态和 `/health` 的一致性。
- Startup/Observability 层验证未配置为 `DISABLED`、安全部分可用为 `DEGRADED`、组件完全不可用为 `FAILED`，并验证只有 `required` 组件的失败会阻止启动。
- Global switch 层验证关闭后当前输入仍可处理、历史 conversation/M05-S/M05-L/G1 均不注入，`delete-all` 对长期事实和短期派生摘要的立即失效与异步清除，以及重新启用后的摘要重建；原始 conversation 消息不得被该命令误删。
- Graph Expansion 层在 G1 记录记忆节点身份、`FOLLOWS` 正确率、`SIMILAR_TO` Precision/Recall、边隔离、1-hop 增益和注册表版本兼容性；新增语义边类型时再记录关系映射准确率、未知关系比例、错误关系类型率和新类型召回增益。
- Graph Expansion 层验证 `FOLLOWS` 只在同一 owner/tenant/source timeline 内按权威来源顺序从早到晚连接相邻活动记忆，`SIMILAR_TO` 以单一规范化 pair 表达对称关系；注册表升级必须保留旧版本并提供迁移、回放和召回变化证据。
- G0 建立无记忆、最近 N 条消息、普通事实记忆和 G1 1-hop 基线；G2 仅在相对 G1 有可复现实质收益且未破坏安全、上下文精度和延迟边界时进入。
- 已下载 `memory_store_eval_dataset_1000.csv` 只作为 Store 层种子：1000 行中只有 213 条唯一 dialogue，934 行位于重复组，12 组相同文本存在标签冲突；`preference` 141 条全部按 VenAgent 规则重标为 `REJECT_PREFERENCE`，`episodic` 109 条标为 `OUT_OF_SCOPE`。与 M05 基本一致的 750 行仍只有 161 条唯一 dialogue，必须按唯一 dialogue 分组切分而不是按行随机切分。
- 未确认原始 CSV 再分发许可前不直接提交下载文件；评测导入保留源标签并增加 `venagent_expected_action`，仓库只提交经过审查、可重放且许可明确的派生样本。
- `evals/memory/` 至少提供 Store policy、owner timelines、Recall gold 和 Graph gold 四类数据契约，以及可复现 runner/metrics；Recall 样本包含 `owner_id`、`eval_time`、`query`、`relevant_memory_ids`、`forbidden_memory_ids` 和 `expected_fact`。
- 首版硬门槛包括短期窗口/摘要来源、Store 动作、秘密和跨 owner 零泄漏、生命周期传播、Context Precision 与 G1 边约束；RAGAS/LLM Judge 和 5000/10000 轮压力曲线只在端到端链路稳定后作为补充，不得伪装为未完成阶段的通过证据。
- 对照基线依次为无历史、最近 N 条消息、完整 turn 预算窗口、完整 turn + 摘要、短期 + 普通长期事实、短期 + 长期事实 + G1 1-hop；Dense/BM25/Hybrid 只比较实际已实现检索，不为复刻 AGI-saber 评测而提前增加产品依赖。
