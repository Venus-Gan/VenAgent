# Outcome

修复 LLM 测试配置隔离，并为当前 VenAgent 聊天输入与流式输出建立明确的字节上限，防止异常大请求或无终止输出占用无界内存，同时保持取消或超限的部分回答不提交到对话历史。

# Scope

- 对单条聊天消息实施 32 KiB UTF-8 字节上限。
- 对单次流式输出实施 128 KiB UTF-8 字节上限。
- 使 `build_runtime_loop(mapping)` 只解析显式传入的 mapping，不读取本机 YAML、`.env` 或进程环境；生产路径继续使用 `AppConfig` 与配置加载器。
- 在 HTTP schema 与运行时边界应用输入限制，防止非 HTTP 调用绕过限制。
- 输出超限时停止 run、发送稳定 SSE 终止事件，并不提交部分对话。
- 为输入、输出、SSE 和不提交行为添加匹配现有风格的 pytest 测试。

# Non-goals

- 不改变 LangGraph 图结构或新增循环次数限制；当前图为 `START → agent → END`，不存在回边。
- 不改变 `MAX_COMMITTED_TURNS = 5` 的历史轮次窗口。
- 不修改模型 provider 的 `max_tokens` 配置、文档导入大小限制或持久化模型。
- 不加入流式总时长、token-aware 上下文裁剪或工具循环限制；这些在本 change 外单独讨论。

# Acceptance examples

- UTF-8 编码后不超过 32 KiB 的消息正常通过；超过上限的消息在 HTTP 和直接运行时调用中均被拒绝。
- 累计输出不超过 128 KiB 的流正常完成并提交完整回答。
- 累计输出将超过 128 KiB 时，流发送一个稳定错误终止事件、取消 run，且历史不包含本轮部分回答。
- 向 `build_runtime_loop` 传入完整测试 mapping 时，结果只由该 mapping 决定，不受开发者本机 LLM YAML 配置影响。
- 现有图继续只执行一个 `agent` 节点；不引入图循环或 recursion-limit 配置。

# Constraints and invariants

- 限制按 UTF-8 字节数而不是 Python 字符数计算。
- 不记录或回显完整的超长用户输入或模型输出。
- 既有 SSE 事件顺序、取消清理和完整回答才提交的语义保持一致。
- 不引入新的配置文件或未来扩展层；限制使用命名常量表达。

# Decisions

- 输入上限为 32 KiB。
- 流式输出上限为 128 KiB。
- 输出超限时不提交部分对话。
- 当前 LangGraph 图无循环；不新增最大循环次数限制。
- 用户确认将 LLM 测试隔离并入本 change。
- 输出超限 SSE 错误码为 `output_limit_exceeded`；相关边界逻辑保留简短中文注释。
- 用户于 2026-07-26 确认完整范围。

# Open questions

无。

# Verification expectations

- 运行相关输入校验、Agent Loop、SSE 与 API pytest。
- 验证超限路径不提交消息、释放 active run 和线程租约。
- 复核图仍保持 `START → agent → END`，没有新增回边。
