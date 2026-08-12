# LLM 运行时配置完整目标规格

## 1. 取舍与目标

当前最小 LLM 配置层 SHALL 以 `replace` 方式演进：保留环境变量和 LangChain 公开模型边界，替换“只认一个 OpenAI-compatible base URL、配置不完整则静默离线”的实现。

配置层 SHALL 支持 OpenAI、OpenAI-compatible、Azure OpenAI、Anthropic 和 Google Gemini 五个显式 provider。真实模型配置 SHALL 在应用装配时完成解析、校验和 adapter 构造；LangGraph State、ConversationService 和聊天 API SHALL NOT 感知 provider 细节。

## 2. 离线与真实模型选择

- 当且仅当所有 `VENAGENT_LLM_` 配置均不存在或为空白时，运行时 SHALL 使用现有离线本地模型。
- 任一 `VENAGENT_LLM_` 配置存在时，运行时 SHALL 把它视为真实模型配置意图，并严格校验全部必需字段。
- 部分配置、未知 provider、非法类型、非法 URL、互斥字段并存或 provider 不支持的参数组合 SHALL 在应用装配阶段抛出稳定的 `LLMConfigurationError` 或等价专用错误。
- 配置错误 SHALL 指出字段名与原因，但 SHALL NOT 包含 API key、完整认证头、`.env` 内容或其他凭据值。
- 远端调用失败 SHALL 继续作为模型失败传播到现有安全 API 错误边界，不得返回离线 mock 答案。

## 3. Provider 与核心字段

真实模型配置 SHALL 使用 `VENAGENT_LLM_PROVIDER` 显式选择：

- `openai`：官方 OpenAI adapter；要求 API key 与 model，API root 可省略以使用 SDK 默认值。
- `openai_compatible`：第三方 OpenAI-compatible adapter；要求 API key、model，并且 API root 与完整 endpoint 二选一。
- `azure_openai`：Azure OpenAI 原生 adapter；要求 API key、model、Azure endpoint、deployment 与 API version。
- `anthropic`：Anthropic 原生 adapter；要求 API key 与 model。
- `google_genai`：Google Gemini 原生 adapter；要求 API key 与 model。

核心环境变量至少包括 `VENAGENT_LLM_PROVIDER`、`VENAGENT_LLM_API_KEY` 与 `VENAGENT_LLM_MODEL`。Azure 专用字段 SHALL 使用同一命名空间并使用可辨识名称；不适用于当前 provider 的专用字段 SHALL 被拒绝，而不是静默忽略。

## 4. OpenAI-family API 形态与 URL

- `openai` 与 `openai_compatible` SHALL 支持 `chat_completions` 和 `responses` 两种显式 API mode；默认 mode 为 `chat_completions`。
- 配置层 SHALL 支持 API root 输入，以及完整 `/chat/completions` 或 `/responses` endpoint 输入。
- API root 与完整 endpoint SHALL 互斥；完整 endpoint 的后缀必须与 API mode 一致，配置层只移除已识别的末尾资源路径来得到 SDK root。
- URL SHALL 只接受绝对 `http` 或 `https` 地址，移除无意义的尾部 `/`，并拒绝 query、fragment、userinfo 和无法识别的完整 endpoint。
- 配置层 SHALL NOT 对任意站点根无条件追加 `/v1`。第三方服务的本机配置 SHALL 按其文档明确填写正确 API root。
- Azure、Anthropic 与 Google Gemini SHALL 使用各自原生 LangChain adapter，不通过 OpenAI-compatible URL 规则改写。

## 5. 常用模型参数

配置层 SHALL 类型化支持以下可选参数；未配置的参数 SHALL NOT 传给模型工厂：

- `reasoning_effort`：非空字符串；仅传给明确支持该字段的 OpenAI-family/Azure adapter。
- `temperature`：有限浮点数，范围 `0..2`。
- `max_tokens`：正整数。
- `timeout`：正有限秒数。
- `max_retries`：非负整数。
- `verbosity`：`low`、`medium` 或 `high`。

Anthropic 与 Google Gemini SHALL NOT 自动接收或换算 `reasoning_effort`。当用户为不支持该通用字段的 provider 配置它时，装配 SHALL 失败并指明使用 provider 扩展对象。

## 6. Provider 扩展对象

- 配置层 SHALL 接受一个 `VENAGENT_LLM_EXTRA_BODY_JSON` JSON 对象，用于第三方 `thinking`、Anthropic/Gemini 原生思考配置或其他 adapter 支持的 provider 扩展。
- 值必须是合法 JSON object；数组、标量、重复/冲突的核心字段和请求控制字段 SHALL 被拒绝。
- 类型化参数具有唯一来源；扩展对象 SHALL NOT 覆盖 provider、model、认证、messages、stream 或已配置的类型化参数。
- adapter SHALL 通过其公开 passthrough 参数接收扩展对象。目标 adapter 无安全 passthrough 边界时，装配 SHALL 明确失败，不得丢弃字段。

## 7. 依赖与适配边界

- OpenAI 与 Azure OpenAI SHALL 使用 `langchain-openai` 公开 adapter。
- Anthropic SHALL 使用对应的 LangChain Anthropic 公开 adapter。
- Google Gemini SHALL 使用对应的 LangChain Google Generative AI 公开 adapter。
- `build_runtime_loop` SHALL 允许测试注入 provider factory registry；生产默认 registry SHALL 延迟选择对应 adapter。
- provider 依赖缺失 SHALL 产生不含凭据的明确配置/装配错误，不得静默改用其他 provider。

## 8. 文档与本机配置

- `.env.example` SHALL 列出默认 OpenAI-compatible 示例和全部可选字段，但只包含占位密钥。
- README SHALL 说明 provider、API mode、root 与 endpoint 的区别、严格错误策略、常用参数及扩展 JSON。
- 被忽略的真实 `.env` SHALL 使用当前第三方服务要求的 API root，并增加本机实际需要的非凭据配置；实现和验证不得读取、打印或提交 API key。
- 显式进程环境 SHALL 继续优先于 `.env`，`.env` SHALL NOT 覆盖已存在的进程变量。

## 9. 验收基线

无网络测试 SHALL 证明：

- 全空配置使用离线模型，任何部分真实配置均失败；
- 五种 provider 分别选择正确的 LangChain factory 与核心参数；
- OpenAI-family 的两种 API mode、root/endpoint 归一化、冲突和非法 URL 行为正确；
- 类型化参数解析、边界值、未设置不发送及不支持组合失败；
- provider 扩展对象接受合法 object，拒绝非法 JSON、非 object 与关键字段冲突；
- 错误文本和测试证据不含 API key；
- 现有 Conversation Context 与 Agent Loop 测试继续通过。

联网调用只作为当前本机 provider 的补充手工验证，不得成为自动验收前提。
