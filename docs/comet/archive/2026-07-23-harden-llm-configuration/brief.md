# Outcome

建立一个可验证、可扩展但仍保持最小范围的 LLM 配置边界：修正当前第三方 OpenAI 兼容 API root 配置错误，支持明确选择 API 形态和常用模型参数，并在配置无效时给出可诊断结果，而不是把错误静默伪装成离线成功。

# Scope

- 审计并重构 `venagent/llm.py` 的环境变量解析、校验、URL 处理和 LangChain 模型装配。
- 增加 OpenAI、OpenAI-compatible、Azure OpenAI、Anthropic 与 Google Gemini 五个显式 provider adapter，并补充所需 LangChain provider 依赖。
- 更新 `.env.example` 与 README 的本机配置说明；真实 `.env` 只修改 API root 等非凭据字段，不读取、输出或提交密钥。
- 为 API root、完整 endpoint、API 模式、思考强度和常用调用参数增加离线单元测试。
- 保持 `AgentLoop` 通过 `MessageInvoker` 使用模型，不把 provider 细节泄漏进 LangGraph State。

# Non-goals

- 不修改已废弃的 `final/`。
- 不实现 M02 SSE、token streaming、取消和断线协议。
- 不增加模型配置 Web UI、数据库配置中心、密钥托管或运行时热切换。
- 不迁移旧项目的 YAML 配置系统、快模型路由或失败后 mock 降级。

# Acceptance examples

- 配置某 OpenAI-compatible 网关时，明确填写服务商要求的 API root，LangChain 不再错误地向站点根路径发送模型请求。
- 输入完整 `.../chat/completions` endpoint 时，配置层可以按已批准规则得到正确 API root，避免旧项目与 VenAgent 对 URL 含义不同造成误配。
- 显式设置思考强度、temperature、token 上限、超时或重试次数时，模型工厂收到类型正确的参数；未设置的可选参数不被发送。
- 配置值非法或只配置一部分真实模型字段时，系统按已批准错误策略处理，并且测试无需访问网络或使用真实密钥。
- 分别选择 Azure OpenAI、Anthropic 或 Google Gemini 时，模型工厂收到各自原生 LangChain adapter 所需参数，不经 OpenAI 兼容协议伪装。

# Constraints and invariants

- 模型适配继续使用 LangChain 公开边界；当前安装版本为 `langchain-openai 1.4.0`，其 `ChatOpenAI` 已提供 `reasoning_effort`、`reasoning`、`use_responses_api`、`extra_body`、timeout 和 retry 字段。
- 外部模型失败不得伪装成真实成功；凭据不得出现在日志、异常、Comet 产物或测试 fixture 中。
- 环境变量继续使用 `VENAGENT_LLM_` 命名空间，显式进程环境优先于 `.env`。
- URL 规范化不得无条件给所有服务追加 `/v1`；智谱等兼容服务使用不同 API root。
- 配置解析和参数映射必须可在无网络环境下完整测试。

# Decisions

- 本 change 是 M01 完成后的横切配置修复，不改变已批准的 conversation-context 行为，也不提前实现 M02。
- AGI-saber 旧实现仅支持完整 chat completions endpoint、model、fast_model 和 temperature；没有 provider adapter、Responses API 或 reasoning 参数。
- 旧项目“远端失败后返回 mock”的做法违反当前路线中“外部失败不得伪装成真实成功”的不变量，因此不迁移。
- 当前故障曾表现为站点根路径请求返回 HTTP 403，而正确 API 版本路径返回标准模型元数据；因此配置层必须区分站点地址、API root 与完整 endpoint。
- 用户选择范围 C：本次直接支持 OpenAI-family、Azure OpenAI、Anthropic 与 Google Gemini 原生适配。
- 用户选择参数方案 A：类型化支持 `reasoning_effort`、`temperature`、`max_tokens`、`timeout`、`max_retries`、`verbosity`，同时提供经过 JSON 对象校验的 provider 扩展字段。
- 用户选择错误策略 A：只有完全未配置 LLM 时才使用离线模型；部分配置、非法值、冲突或不受支持组合在启动装配阶段失败。
- 不把不同厂商的“思考强度”静默换算成看似等价的值；OpenAI-family/Azure 使用 adapter 支持的 `reasoning_effort`，Anthropic/Gemini 的原生 thinking 配置通过受校验扩展对象传递。
- 用户已确认本 brief 与 `llm-runtime-configuration` 完整目标规格，可以进入 Build。

# Open questions

- 无阻塞问题。

# Verification expectations

- 单元测试覆盖空配置、完整配置、部分配置、非法类型、边界值、API root、完整 endpoint、Chat Completions/Responses 模式及显式/未设置模型参数。
- 模型工厂记录参数，证明 URL、API 模式与常用参数映射正确且未泄漏凭据，不发起网络请求。
- 运行完整 pytest、`git diff --check` 和 Comet scoped text check。
- 使用实际第三方服务的手动联网验证只作为可选补充；自动验收不得依赖外网或真实密钥。
