# LLM 运行时配置完整目标规格

## 1. 取舍与目标

LLM 配置层 SHALL 由代码内安全默认值与白名单环境变量共同驱动的不可变配置对象。它 SHALL 保留 LangChain 公开模型边界，并支持 OpenAI、OpenAI-compatible、Azure OpenAI、Anthropic 和 Google Gemini 五个显式 provider。

真实模型配置 SHALL 在应用装配时完成解析、校验和 adapter 构造；LangGraph State、ConversationService 和聊天 API SHALL NOT 感知 provider 或配置来源细节。

记忆结构化提取 SHALL 默认复用当前对话模型，并允许可选 extractor override。override 可以只替换模型名以使用同 provider 的低成本模型，也可以显式提供完整独立 provider profile；无论模型实例是否复用，extractor 调用、结构化解析和健康状态仍与普通聊天分层观察。

Embedding SHALL 具有独立、通用的 `EmbeddingConfig` 和 adapter，输入为文本或有界文本批次，输出为维度一致的有限浮点向量。配置使用 `EMBEDDING_API_URL/API_KEY/MODEL`，不从 chat model 名称推断 embedding model；M05 作为首个消费者，未来 M08 通过同一技术 port 复用，不与 M05 共享事实、索引或生命周期。

## 2. 来源与离线选择

`llm` 的所有字段 SHALL 仅由白名单 `LLM_*` 变量通过仓库根 `.env`、显式进程环境或 Secret Manager 提供；显式进程环境 SHALL 覆盖 `.env`。`api_key` SHALL 只存在于秘密包装的配置对象中，不得写入仓库文件、日志或异常。

记忆提取 override SHALL 仅由同一来源的 `MEMORY_EXTRACTOR_*` 白名单提供。全部为空时 `MemoryExtractorConfig` 引用已解析的主模型 profile；仅设置 `MEMORY_EXTRACTOR_MODEL` 时从主 profile 派生并替换 model；设置独立 provider、凭据或 endpoint 时必须构造并严格校验完整独立 profile。

- 当且仅当所有 LLM 配置字段不存在或为空白时，运行时 SHALL 使用现有离线本地模型。
- 任一 LLM 配置字段存在时，运行时 SHALL 把它视为真实模型配置意图，并严格校验全部必需字段。
- 部分配置、未知 provider、非法类型、非法 URL、互斥字段并存或 provider 不支持的参数组合 SHALL 在应用装配阶段抛出稳定的 `LLMConfigurationError` 或等价专用错误。
- 显式独立 extractor profile 的部分配置、provider 依赖缺失或非法参数 SHALL 产生稳定配置错误，不得静默退回主模型；运行期 extractor 调用失败只更新提取能力健康状态，普通聊天按其自身模型状态运行。
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
- extractor provider 依赖缺失、调用超时或结构化输出解析失败 SHALL 只失败当前 extraction job 并按 durable job 策略重试/降级；不得阻塞回答发布，也不得生成事实候选。
- embedding adapter SHALL 使用配置的完整 `/embeddings` endpoint，验证 HTTP 状态、响应 schema、结果数量、向量非空/有限/同维和输入顺序；任何失败均返回稳定技术错误，不记录原文、key 或向量，也不调用 chat completion 作为降级。
- embedding 配置缺失时 adapter absent，M05 的 slot 精确路径和已评测 lexical fallback 可以继续；配置存在但运行时失败时，事实权威提交不回滚，index job 重试并把 embedding/index 健康标为 degraded。
- 无网络测试 SHALL 覆盖环境变量加载后的离线选择、五种 provider、URL/endpoint 规则、类型化参数、扩展对象和秘密安全。
- 活动 LLM 配置实现、README 与测试 SHALL NOT 依赖 YAML 或 `VENAGENT_CONFIG_PATH`。
