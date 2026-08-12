# Outcome

修复聊天前端的两个已确认缺陷：真实 SSE token 已持续到达浏览器时，assistant 文本应在运行期间渐进显示；长回复增长时，消息区应在用户接近底部时智能跟随，同时尊重用户主动向上阅读的意图。

# Scope

- 修复 Pinia chat store 在插入 user/assistant 后继续修改原始对象、绕过 Vue reactive proxy 的引用问题，使 started、token、completed、cancelled、error 和连接中断状态及时反映到 DOM。
- 将新发送与重试路径统一为通过当前 conversation 的 reactive message 引用或稳定 message ID 更新，避免延迟事件写入已替换、已移除或其他 thread 的消息。
- 为消息容器增加智能跟随：用户发送、切换/加载对话或流式文本增长时，仅当用户仍接近底部才滚动到最新内容；用户主动向上滚动离开底部后暂停，重新回到底部后恢复。
- 使用 nextTick 等待 Vue 提交 DOM，并以单个待处理 requestAnimationFrame 合并高频 token 产生的滚动请求；组件卸载或切换上下文时清理帧和监听器。
- 增加可控、按时间分段到达的浏览器自动化，验证 completed 前 partial 已可见，以及桌面和 390px 移动端的跟随、暂停与恢复行为。
- 保持现有停止、错误、断流、重试、身份切换、thread 隔离、composer 可见性和消息区独立滚动语义。

## 文件级施工蓝图

### web/src/modules/chat/store.ts

- 保留现有 SSE 读取、事件解析、终态和错误收敛结构，不重写网络层。
- 新发送路径创建 user/assistant 草稿并插入 conversation.messages 后，立即从 reactive 数组中重新取得消息对象；从此不再把插入前的普通对象作为异步 SSE 生命周期的写目标。
- 重试路径先定位原 user 与相邻 assistant；若复用已有 assistant，确认该引用来自 reactive messages 数组；若需插入新 assistant，则同样在插入后重新定位 reactive 对象。
- 为长时间异步读取保存稳定的 threadId、userMessageId、assistantMessageId 和 clientMessageId，不依赖数组位置长期不变。
- 每个 started、token、completed、cancelled、error、catch 和 finally 写入前，按稳定 ID 在目标 conversation 中重新确认消息仍存在、角色正确且属于当前尝试；迟到事件无法定位时安全忽略，不回退到当前 active conversation。
- token 事件只追加非空公开 content，并同步把 assistant 状态从 thinking 改为 streaming；completed 使用 answer 与已拼接文本对账后收敛为 sent。
- 取消、读取异常、无终态 EOF、活动超时和模型错误继续保留已到达 partial，只改变状态，不重新创建重复消息。
- save、loadHistory 与 select 的既有时机保持不变；不能为了强制重绘而在每个 token 调用 localStorage save、刷新历史或整体替换 conversations。

预期最小实现形态：插入消息后保存稳定 ID，并通过 conversation.messages.find(message => message.id === targetId) 取得 reactive 对象；若实现选择数组索引，索引只能用于插入后的即时重新取得，后续异步事件仍以稳定 ID 校验归属。

### web/src/modules/chat/ChatWorkspace.vue

- 给 .messages section 增加 messagesContainer 模板 ref，不改变其 aria-live 和独立滚动语义。
- 增加单一命名常量 bottomThresholdPx，初始设计值 64；所有接近底部判断复用同一函数，不散落不同阈值。
- 维护 followLatest 布尔状态和 pendingScrollFrame；followLatest 表示用户是否仍允许自动跟随，不等同于 busy。
- 监听消息容器 scroll，使用 max(0, scrollHeight - scrollTop - clientHeight) 计算底部距离。距离不大于阈值时 followLatest 为 true，超过阈值时为 false。
- 新一轮提交、对话切换和历史加载完成时显式恢复 followLatest；等待 nextTick 后安排滚到底部。
- 监听当前 active thread 的最小渲染签名：threadId、消息数量、最后一条消息 ID、最后一条 assistant 文本长度和状态。签名变化且 followLatest 为 true 时才安排跟随。
- 跟随函数先等待 nextTick，再用 requestAnimationFrame 将 messagesContainer.scrollTop 设置为 messagesContainer.scrollHeight；已有待处理帧时不重复安排。
- animation frame 执行前再次核对容器和 active thread，避免旧对话帧滚动新对话。
- onBeforeUnmount、身份变化或对话上下文切换时取消 pendingScrollFrame 并清理 scroll listener；不能遗留后台帧。
- 流式 token 期间使用即时定位，不使用 smooth，以免数百个 token 累积动画。自动滚动不调用 focus，不滚动 window。

### web/tests/e2e/workspace.spec.ts

- 保留现有一次性 SSE mock，继续服务于终态、错误、取消、EOF、重试等已有场景；不能把它继续当作渐进渲染证据。
- 新增可控分段流 fixture。fixture 必须能独立放行 started、第一批 token、第二批 token 和 completed，使测试可以在每个阶段之间断言页面状态。
- 优先使用页面内可控 ReadableStream 或测试专用最小 SSE server；选择标准是 Chrome 实际 reader.read 分批完成、无真实网络凭据、无任意 sleep 猜测、测试结束可确定清理。
- fixture 暴露明确阶段信号或控制句柄，测试通过事件同步推进，不依赖固定等待若干秒。
- 流式测试在 completed 被阻塞时断言 partial 已显示，再放行第二批 token 并断言文本增长，最后放行 completed 并断言终态。
- 滚动测试直接读取 .messages 的 scrollTop、clientHeight、scrollHeight 和底部距离；不再只验证 overflowY 为 auto。
- 长文本数据使用合成内容，不调用真实 DeepSeek，不记录用户消息、凭据或真实模型回答。

### web/src/style.css

- 默认不修改。只有浏览器测试证明滚动锚点、overflow anchoring 或容器尺寸阻碍既定行为时，才做最小调整。
- 不把自动滚动行为放进 CSS，不改变 workspace 网格和 composer 固定在视口内的现有布局不变量。

## 响应式数据流设计

1. send 捕获当前 conversation 和稳定 threadId。
2. 新建或复用 user/assistant 消息，并确保异步阶段持有的是 reactive collection 中的对象或稳定 ID。
3. 请求发出前记录本次 attempt 的 clientMessageId、userMessageId、assistantMessageId 和 StreamState。
4. started 到达：重新定位目标消息，写入 runId，user 变为 sent，assistant 保持 thinking。
5. token 到达：重新定位目标 assistant，验证 attempt 仍归属当前 thread 后追加 content，状态变为 streaming；Vue 因写入经过 proxy 而提交 partial DOM。
6. completed 到达：标记已收到终态，以 answer 对账最终文本，user/assistant 变为 sent。
7. cancelled 或 error 到达：保留 partial，收敛相应状态。
8. reader EOF 但无终态、读取异常或活动超时：保留 partial，收敛为 interrupted。
9. finally 释放 StreamState、更新时间和缓存，再按既有规则同步服务端历史；这一步不再承担“触发最终一次重绘”的隐式职责。

## 智能跟随状态机

- FOLLOWING：用户位于底部阈值内。消息新增或文本增长后，在下一 DOM 提交与 animation frame 中滚到底部。
- PAUSED_BY_USER：scroll 事件显示用户离底部超过阈值。任何后续 token 都只更新内容，不改变 scrollTop。
- 恢复 FOLLOWING：用户手动滚回阈值内；或明确开始新一轮；或切换/加载一个对话并要求定位最新内容。
- CONTEXT_CHANGED：active thread、owner 或组件生命周期变化。取消旧帧、重置容器归属，再按新上下文决定首次定位。
- 跟随状态不得写入 Pinia、localStorage 或服务端；它是当前组件和当前视口的瞬时 UI 状态。

## 分步实施顺序

1. 在 Playwright 中增加可控分段流 fixture，并先写一个当前实现必然失败的断言：completed 未放行时 partial 已可见。
2. 运行该定向场景，保存真实失败事实，确认测试确实能区分“网络已分块”和“DOM 最终一次重绘”。
3. 修复 store 新发送路径的 raw object 写入，确保第一批 token 能触发 DOM 更新。
4. 修复重试、取消、错误、catch/finally 等同一异步生命周期中的全部消息引用，避免只修正常路径。
5. 运行分段流及现有取消、EOF、失败、重试场景，确认状态机没有回归。
6. 在 ChatWorkspace 增加 messages ref、底部距离判断、followLatest 和帧合并跟随。
7. 增加“接近底部持续跟随”测试，覆盖多批 token 和终态。
8. 增加“用户上滚暂停；回到底部恢复”测试，确保阅读位置优先。
9. 在 1280×720 与 390×844 重复关键滚动断言，并继续验证 composer 可见。
10. 执行前端类型检查/生产构建、定向 E2E、全量 E2E；若前端改动没有触及 Python/HTTP 契约，Python 测试仅作为风险评估后的回归证据，不虚构未运行结果。
11. 按公开前端审查项复核响应式正确性、迟到事件隔离、资源清理、布局性能与无障碍，再进入 Comet Verify。

## 预计项目改动

- 必改：web/src/modules/chat/store.ts。
- 必改：web/src/modules/chat/ChatWorkspace.vue。
- 必改：web/tests/e2e/workspace.spec.ts。
- 条件新增：web/tests/e2e 下的最小流式 fixture 辅助文件，仅当现有 spec 内无法稳定表达可控 ReadableStream 时创建。
- 条件修改：web/src/style.css，仅当真实浏览器证据表明 CSS 阻碍目标滚动行为。
- 不改：venagent/agent/runtime.py、venagent/interfaces/http/streaming.py、venagent/interfaces/http/routes.py、LLM provider 配置、数据库与 checkpoint。

# Non-goals

- 不修改 DeepSeek、其他 LLM provider、LangChain adapter、模型参数或 API 配置。
- 不修改 FastAPI POST /api/chat/stream、SSE 事件格式、heartbeat、业务 sequence、取消协议或服务端持久化/checkpoint。
- 不把完整回答在浏览器中按字符或定时器拆分为“模拟流式”，也不要求服务端强制重切 provider delta。
- 不新增全局滚动服务、虚拟列表、第三方滚动依赖、分析埋点或新的外部数据接收方。
- 不改变已归档的 fix-m04-acceptance-regressions；本 change 以新的完整目标规格替换 canonical frontend-foundation。

## 明确不采用的方案

- 不使用强制组件刷新：它掩盖 reactive proxy 引用错误，无法保证取消、重试和迟到事件正确。
- 不在每个 token 后整体复制 conversations 或 messages：会扩大渲染成本、破坏对象身份，并使异步引用更难推理。
- 不在每个 token 后调用 save、loadHistory 或 select：这些操作不应作为 DOM 刷新的副作用来源，并会增加存储和网络负担。
- 不在前端把最终 answer 按字符加定时器播放：这是伪流式，不能反映真实 SSE、取消或断流边界。
- 不要求后端逐字符重切 provider delta：实测后端已经渐进传输，且协议允许单个 token 事件含多个字符。
- 不对每个 token 使用 smooth scroll：高频动画会排队、抖动并阻碍用户上滚。
- 不无条件锁定底部：用户主动阅读历史时不得被强制拉回。
- 不依赖 CSS scroll anchoring 作为唯一跟随机制：其行为不能表达用户暂停与恢复状态，也难以稳定验收。

# Acceptance examples

- 可控 SSE 先发送 started 与 token“第一段”，暂停发送后续事件；此时页面已经显示“第一段”且 assistant 为“生成中”，即使 completed 尚未到达。
- 同一 SSE 随后发送 token“第二段”；页面在终态前增长为“第一段第二段”，最终 completed.answer 与拼接文本一致且状态收敛为成功。
- 同一流在完成前被取消、断开或返回错误；已到达的 partial 保持可见，并显示对应的已停止、连接中断或失败状态，不退化为最终一次性渲染。
- 桌面与 390px 移动视口中，用户位于或接近消息区底部时开始长回复；每批 token 渲染后，消息区与底部距离保持在允许阈值内，composer 始终可见。
- 用户在长回复期间主动向上滚动并离开底部阈值；后续 token 不把视口强制拉回。用户手动回到底部后，再到达的 token 恢复自动跟随。
- 用户切换或加载一个已有长历史的对话；内容提交后消息区定位到该对话底部，旧对话遗留的帧或 token 不得滚动或写入新对话。

# Constraints and invariants

- 浏览器收到的真实 SSE delta 是显示事实；前端不得通过假打字效果掩盖上游粒度，也不得等待 completed 才展示已经收到的公开文本。
- token 更新必须经过 Vue reactive 边界；局部变量不得在对象插入 reactive collection 后继续作为绕过 proxy 的长期写引用。
- 流式更新必须按稳定 message.id、client_message_id、thread 与 active run 归属写入；迟到事件不得污染已切换、已移除或其他 owner 的内容。
- “接近底部”使用单一命名阈值判断，计划默认 64px；实现可在 48--96px 内选择并由测试锁定，不得把多个魔法数字散落在组件中。
- 自动跟随只能作用于 .messages 容器，不滚动 window，不移动键盘焦点，不影响输入、停止、重试或移动抽屉。
- 高频 token 的自动跟随每个 animation frame 最多安排一次，不为每个 token 堆积 smooth scroll 动画；流式期间使用即时定位，避免动画队列、抖动与额外布局压力。
- 用户上滚后的阅读位置优先于自动跟随；只有重新进入底部阈值、切换/加载对话或明确开始新一轮时才恢复跟随。
- 保持既有 owner 隔离、浏览器缓存、失败/取消 partial、幂等重试、终态收敛和安全纯文本渲染边界。

# Decisions

- 根因已通过三层真实时序测试确认：DeepSeek/ChatOpenAI 返回多个 chunk，VenAgent SSE 与 Chrome ReadableStream 持续分块到达；DOM 仅在终态重绘，原因是 conversation.messages.push(assistant) 后仍通过插入前原始对象修改 assistant.text/status，绕过 Vue proxy。
- 修复限定在 web/src/modules/chat/store.ts、web/src/modules/chat/ChatWorkspace.vue、相应 Playwright 测试及确有必要的最小样式调整；不修改已经确认正常的后端链路。
- 插入或定位消息后，后续状态写入应通过 reactive 数组中的对象或按稳定 ID 重新定位的 reactive 对象完成；不使用强制刷新、全量复制 conversations 或人为 nextTick 掩盖引用错误。
- 自动滚动采用“接近底部时跟随”的智能策略，而非生成期间无条件锁底；用户上滚暂停、回到底部恢复。
- Playwright 必须使用真正按时间分段的 ReadableStream/测试 SSE fixture，不能继续用一次性 route.fulfill body 作为渐进渲染证据。
- 用户已审阅完整设计并要求将计划写入 change；本轮只记录 Shape，不进入 Build。

## 已有诊断证据摘要

- 当前 DeepSeek/ChatOpenAI 真实 astream 测试产生 611 个非空 chunk；首块约 2.16 秒，随后持续逐块到达，因此上游不是一次性全文返回。
- VenAgent 真实 POST /api/chat/stream 使用 text/event-stream 与 chunked transfer；测试客户端收到 started、数百个独立 token 数据块和最后的 completed，因此 FastAPI/SSE 没有等待全文。
- Chrome ReadableStream 在一次真实页面运行中收到 321 次非空读取，但 DOM 只有空 assistant 与最终全文两次文本状态，排除浏览器网络缓冲。
- 当前 store 在 conversation.messages.push(assistant) 后继续通过插入前的 assistant 局部变量写 text/status；该写入不经过 Vue proxy，直到 streams.delete、updatedAt 或其他 reactive 变化触发重绘，DOM 才读取累计全文。
- 当前长文本 E2E 只证明消息区可滚动、composer 可见，没有断言 scrollTop 接近 scrollHeight，也没有任何组件自动滚动实现。

# Open questions

无。

# Verification expectations

- 新增定向浏览器回归，在 completed 尚未发送时断言非空 partial 已显示，并至少观察到两个不同的非零 DOM 文本长度。
- 验证 started 前发送中、started 后思考中、首 token 后生成中、唯一终态后的成功/取消/中断/失败状态保持一致。
- 验证接近底部时持续跟随、用户上滚后保持阅读位置、回到底部后恢复跟随；断言使用容器的 scrollTop、clientHeight 与 scrollHeight，不能只验证 overflow-y: auto。
- 在 1280×720 和 390×844 视口验证长文本、composer 可见性和消息区独立滚动。
- 运行前端 production build、定向 Playwright 与全量 npm.cmd run test:e2e，并如实记录失败、跳过和剩余风险。
- 既有取消、EOF、读取错误、活动超时、重试、thread_not_found、身份失效、跨标签页、移动抽屉和长文本布局场景保持通过。

## 分段流测试协议

- 阶段 A：请求建立但 started 尚未发送。断言 user 为“发送中”，assistant 尚未显示生成文本。
- 阶段 B：放行 started。断言 user 为 sent 语义，assistant 为“思考中”。
- 阶段 C：放行 token“第一段”，保持 completed 阻塞。断言 DOM 已显示“第一段”且状态为“生成中”。
- 阶段 D：放行 token“第二段”，继续阻塞 completed。断言 DOM 增长为“第一段第二段”，证明存在第二次非零可见更新。
- 阶段 E：放行 completed.answer。断言最终文本对账、状态标签消失、stream 状态释放。
- 变体：在阶段 C 后分别放行 cancelled、error、EOF 或网络断开，断言 partial 保留且状态正确。

## 滚动验证矩阵

| 视口 | 初始位置 | 事件 | 预期 |
| --- | --- | --- | --- |
| 1280×720 | 底部阈值内 | 多批 token | 每批 DOM 更新后底部距离不超过阈值与测试容差 |
| 390×844 | 底部阈值内 | 多批 token | 保持跟随，composer 底边不超出视口 |
| 1280×720 | 用户上滚超过阈值 | 后续 token | 文本增长但不强制滚到底部，阅读位置无不合理跳跃 |
| 390×844 | 用户上滚超过阈值 | 后续 token | 同上，移动布局不触发 window 滚动 |
| 两种视口 | 用户重新滚到底部 | 再到 token | 自动跟随恢复 |
| 两种视口 | 切换长历史对话 | DOM 完成加载 | 新对话定位到底部，旧帧不影响当前容器 |
| 两种视口 | 取消/失败/中断 | partial 已显示 | partial 保留，终态可见，滚动策略不重置用户上滚意图 |

## 验证命令顺序

1. 在 web 工作目录运行新增分段流场景的 Playwright 定向命令；具体过滤参数以最终测试名称为准并记录真实命令。
2. 在 web 工作目录运行 npm.cmd run build，覆盖 vue-tsc -b 与 Vite production build。
3. 在 web 工作目录运行 npm.cmd run test:e2e，执行全部浏览器回归。
4. 若 Build 实际触及共享 HTTP 类型或其他 Python 边界，再运行对应 pytest 定向测试或全套项目 pytest；未触及时仍需在 Verify 中说明选择依据。
5. 在 Verify 报告中逐项记录实际结果、跳过项、桌面/移动证据、规格一致性和剩余风险。

## 完成判定

- completed 前可以稳定观察到至少两次不同的非零 assistant DOM 文本长度。
- 新发送与重试都不再依赖 raw message 对象触发最终重绘。
- 接近底部、上滚暂停、回底恢复、切换对话和生命周期清理全部有浏览器证据。
- 现有取消、断流、失败、重试、身份与布局回归保持通过。
- 没有引入后端协议变化、模拟打字、第三方滚动依赖或新的隐私边界。
- 所有实际运行检查及未运行检查均在 verification.md 如实记录。

## 风险与回退

- 风险：watch 签名过宽导致高频无效滚动。控制方式是只观察 active thread 的消息数量、最后消息 ID、assistant 文本长度与状态，并用单帧合并。
- 风险：程序滚动触发 scroll 后错误切换 followLatest。控制方式是统一使用底部距离推导状态，程序滚到底部自然保持 true。
- 风险：用户上滚与 token 同帧竞争。控制方式是 animation frame 执行前再次检查 followLatest 和 active thread；若用户已离底则取消本次跟随。
- 风险：迟到 token 写入新对话。控制方式是稳定 thread/message/run 归属校验，不使用 this.active 作为异步写目标。
- 风险：重试路径复用旧 assistant 时仍持有 raw 引用。控制方式是新发送与重试共用同一 reactive 定位规则，并分别提供回归场景。
- 若实现引入不可接受的布局或状态回归，回退仅撤销本 change 的前端代码与测试，不需要回退后端或 provider 配置；已有 SSE 链路保持原样。
