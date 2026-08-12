# 聊天负载边界完整目标规格

## 1. 输入边界

- 单条 user message 的 UTF-8编码长度不得超过 32 KiB；Pydantic/HTTP、conversation command和直接应用调用都必须在创建 message/run前执行相同验证。
- 空白输入、非法类型和超限输入返回稳定客户端错误，不创建 ConversationMessage、AgentRun、RunGrant或 checkpoint，也不调用模型。
- `client_request_id`、标题、ID与分页参数分别有明确长度/格式上限；错误不得回显超长正文或内部验证细节。

## 2. 输出边界

- 单个 AgentRun 对用户公开的累计流式文本和最终 `final_answer` 的 UTF-8编码长度不得超过 128 KiB。
- token超过上限时停止继续公开输出，持久取消/失败意图并让图在安全边界收敛为 `failed/output_limit_exceeded`；不得创建正式 assistant message。
- 已持久化的 user message保持存在，动态 retry规则决定是否可新建 run；浏览器 partial仅是本次观察状态，不上传或写入正式历史。
- 非流式模型返回、SSE token聚合、checkpoint final_answer和 finalizer在各自信任边界重复验证同一上限，防止绕过。

## 3. 上下文预算

- ContextProjection SHALL 使用注入的 TokenCounter/预算配置，对 system、当前任务、conversation与后续 memory/tool/evidence blocks进行确定性预算；不得只靠字符截断猜测模型窗口。
- 当前任务和不可省略的安全/output contract优先保留；其他 section按 ProjectionPolicy截断或舍弃，并生成不含正文的 BudgetReport。
- 预算、过滤和截断不能修改正式 ConversationMessage或 LangGraph State权威事实。

## 4. 流式与生命周期

- 输出边界由 run执行拥有，不由单个 SSE连接拥有；观察者断开不取消，多个观察者不能各自重置累计上限。
- output limit终态通过 AgentRun query/snapshot/failed事件一致呈现；不持久化 token delta，也不以 partial长度作为恢复依据。
- 模型错误、用户取消、基础设施中断与 output limit使用不同稳定 reason；日志只记录 code、run关联、计数和耗时，不记录输出正文。

## 5. 配置隔离

- `build_runtime` 或等效 composition helper接收显式 `Mapping[str,str]` 时，只使用该 mapping解析 LLM/预算配置；本机 YAML、`.env`与进程环境不得污染隔离测试路径。
- 配置缺失、非法或模型上限不匹配时使用稳定失败/启动状态，不静默取消保护。

## 6. 验收

- 测试 ASCII、多字节 UTF-8、恰好边界、超一字节、空白和非法输入，证明超限前无业务写入/模型调用。
- 测试多个 token跨越边界、单个超大 token、非流式超限和 finalizer二次校验，证明没有正式 assistant message或假 succeeded。
- 测试断连/重连和多个观察者不重置累计输出保护，snapshot返回一致终态。
- 测试 ContextProjection预算确定、优先级与 BudgetReport安全，显式配置 mapping不受本机层污染。
