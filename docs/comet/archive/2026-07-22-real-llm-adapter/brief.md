# Outcome

让最小 Agent Loop 在本机已配置自定义 OpenAI 兼容服务时调用真实聊天模型，同时保持未配置凭据时的离线本地回显体验。

# Scope

- 增加从本机环境变量读取 OpenAI 兼容服务地址、API 密钥和模型标识的配置边界。
- 增加可替换的真实聊天模型适配器，并让 HTTP/Web UI 通过现有 Agent Loop 使用它。
- 提供不含真实凭据的 `.env.example`、测试和清晰的本地启动说明。

# Non-goals

- 不把 API 密钥、真实服务响应、模型内容或其他凭据写入 Git、测试、日志或 Comet 产物。
- 不添加流式输出、工具、记忆、RAG、多轮会话或多模型路由。
- 不改造已废弃的 `final/` 目录。

# Acceptance examples

- 当本机已配置有效的服务地址、密钥和模型标识时，一次 Web UI 提交调用真实聊天模型，并显示其回复。
- 当缺少任一真实模型配置时，应用仍可启动并使用当前离线本地回显模型。
- 配置的密钥永不出现在 HTTP 响应、异常文本、日志、测试夹具或受版本控制文件中。

# Constraints and invariants

- 仅从 Git 忽略的本机 `.env` 或进程环境变量读取凭据；仓库中仅保留占位符示例。
- 服务端地址必须作为 OpenAI 兼容 base URL 使用，不能硬编码到业务逻辑或前端。
- 真实模型仍经现有单节点 Agent Loop 调用；HTTP 层不得直接调用提供商 SDK。
- 默认离线模型和自动化测试不得访问外部网络。

# Decisions

- 使用用户提供的第三方 OpenAI 兼容服务地址作为本地部署时的候选 base URL；密钥不记录在本变更产物中。
- 已确认的模型 ID 为 `gpt-5.6-terra`；它作为本地 `.env` 的示例值，实际运行仍可由环境变量覆盖。
- 未配置真实模型时保留当前本地回显回退，确保开发和测试不需要 API Key。

# Open questions

无。

# Verification expectations

- 使用注入的假 OpenAI 兼容客户端测试配置选择、请求转发与凭据脱敏，不访问外网。
- 验证缺失配置时仍使用离线模型；验证 `.env.example` 不含真实密钥。
