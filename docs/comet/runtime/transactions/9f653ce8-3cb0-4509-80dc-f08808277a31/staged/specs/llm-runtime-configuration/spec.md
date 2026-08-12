# LLM 运行时配置完整目标规格

## 1. 取舍与目标

LLM 配置层 SHALL 由代码内安全默认值与白名单环境变量共同驱动的不可变配置对象。它 SHALL 保留 LangChain 公开模型边界，并支持 OpenAI、OpenAI-compatible、Azure OpenAI、Anthropic 和 Google Gemini 五个显式 provider。

真实模型配置 SHALL 在应用装配时完成解析、校验和 adapter 构造；LangGraph State、ConversationService 和聊天 API SHALL NOT 感知 provider 或配置来源细节。

## 2. 来源与离线选择

`llm` 的所有字段 SHALL 仅由白名单 `LLM_*` 变量通过仓库根 `.env`、显式进程环境或 Secret Manager 提供；显式进程环境 SHALL 覆盖 `.env`。`api_key` SHALL 只存在于秘密包装的配置对象中，不得写入仓库文件、日志或异常。

- 当且仅当所有 LLM 配置字段不存在或为空白时，运行时 SHALL 使用现有离线本地模型。
- 任一 LLM 配置字段存在时，运行时 SHALL 把它视为真实模型配置意图，并严格校验全部必需字段。
- 部分配置、未知 provider、非法类型、非法 URL、互斥字段并存或 provider 不支持的参数组合 SHALL 在应用装配阶段抛出稳定的 `LLMConfigurationError` 或等价专用错误。
- 配置错误 SHALL 指出字段名与原因，但 SHALL NOT 包含 API key、完整认证头、`.env` 内容或其他凭据值。

## 3. Provider 与核心字段

真实模型配置 SHALL 使用 `LLM_PROVIDER` 显式选择：

- `openai`：要求 API key 与 model，API root 可省略以使用 SDK 默认值。
- `openai_compatible`：要求 API key、model，并且 API root 与完整 endpoint 二选一。
- `azure_openai`：要求 API key、model、Azure endpoint、deployment 与 API version。
- `anthropic`：要求 API key 与 model。
- `google_genai`：要求 API key 与 model。

核心字段为 provider、api_key 与 model；Azure 专用字段使用同一 `LLM_*` 白名单。当前 provider 不适用的专用字段 SHALL 被拒绝，而不是静默忽略。

## 4. OpenAI-family API 形态与 URL

- `openai` 与 `openai_compatible` SHALL 支持 `chat_completions` 和 `responses` 两种显式 API mode；默认 mode 为 `chat_completions`。
- 配置 SHALL 支持 API root 及完整 `/chat/completions` 或 `/responses` endpoint，且二者互斥。
- 完整 endpoint 的后缀必须与 API mode 一致；配置层仅移除已识别资源后缀以得到 SDK root。
- URL SHALL 只接受绝对 `http` 或 `https` 地址，移除无意义尾部 `/`，并拒绝 query、fragment、userinfo 和无法识别的完整 endpoint。
- 配置层 SHALL NOT 对任意站点根无条件追加 `/v1`。
- Azure、Anthropic 与 Google Gemini SHALL 使用各自原生 LangChain adapter。

## 5. 常用参数与扩展对象

配置层 SHALL 类型化支持 `reasoning_effort`、`temperature`（有限 `0..2`）、`max_tokens`（正整数）、`timeout`（正有限秒数）、`max_retries`（非负整数）和 `verbosity`（`low`、`medium`、`high`）。未配置参数 SHALL NOT 传给模型工厂。

`reasoning_effort` 与 `verbosity` 仅适用于明确支持的 OpenAI-family/Azure adapter；Anthropic 与 Google Gemini 的不支持组合 SHALL 失败。

`extra_body` SHALL 是 provider 扩展 JSON object。它不得覆盖 provider、model、认证、messages、stream 或已配置的类型化参数；无法安全传递该对象的 adapter SHALL 明确失败。

## 6. 依赖、适配与验收

- OpenAI/Azure SHALL 使用 `langchain-openai`；Anthropic 和 Gemini SHALL 使用各自公开 LangChain adapter。
- `build_runtime_loop` SHALL 支持测试注入 provider factory registry；生产 registry SHALL 延迟选择对应 adapter。
- provider 依赖缺失 SHALL 产生不含凭据的明确错误，不得回退到其他 provider。
- 无网络测试 SHALL 覆盖环境变量加载后的离线选择、五种 provider、URL/endpoint 规则、类型化参数、扩展对象和秘密安全。
- 活动 LLM 配置实现、README 与测试 SHALL NOT 依赖 YAML 或 `VENAGENT_CONFIG_PATH`。
