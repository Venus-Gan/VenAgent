# Sprint 03 审查报告

## 结论

P1-06～P1-08 已完成。延迟到达的专项审查曾发现多项 HIGH/MEDIUM 问题，现已全部补测并修复；复核后未保留 CRITICAL/HIGH 问题。全量测试、覆盖率、语法和依赖边界门禁通过。

## 已处理问题

- `_bootstrap_concurrent()` 的线程实现已移入 `src/venagent/bootstrap/concurrent.py`；legacy Agent 仅保留 callback adapter 和兼容包装。
- `UnifiedAgent.__init__()` 不再恢复持久化数据、检查已有 RAG chunks、初始化 KG 或启动 worker。
- `Preference` 和 RAG existing-chunks 检查均可延迟到 runtime startup；旧直接构造行为仍由默认参数保持兼容。
- `AsyncMemoryWriter` 改为显式启动，stop 先排空队列再无超时等待 worker，避免 lifespan 结束后残留线程或写入已关闭存储。
- FastAPI app factory 只创建无副作用 app shell；资源装配延迟到 lifespan startup，业务 state 只保存安全诊断和生命周期状态。
- FastAPI lifespan 支持同步/异步 start/close；同步 hook 使用线程执行，取消时先排空线程，再按反序关闭资源。
- startup 失败先清理已启动或部分初始化资源，保留 cleanup diagnostics，再返回不携带原始异常上下文的稳定错误。
- legacy `initialize_runtime()` 和 `build_deps()` 增加失败回滚，避免 worker、Agent 或 Infrastructure 半途泄漏。
- 并发 Bootstrap 按完成顺序收集结果、按声明顺序返回；中断时取消未开始任务并等待已运行线程结束，不强杀不可安全中断的 Python 线程。
- 测试网络熔断扩展到 socket/urllib/SDK transport，同时允许事件循环所需的 loopback socket。
- health snapshot 使用不可变 tuple DTO；`as_dict()` 返回新对象，状态映射不输出原始 DSN/secret。
- PostgreSQL 故障不会被错误报告为 durable workflow 可恢复；chat 和短期记忆保持独立可用。

## 审查覆盖

- TDD：通过；新测试先 RED，随后 GREEN/REFACTOR。
- Python 3.11 并发与生命周期：通过等价主会话审查。
- FastAPI lifespan/app state：通过定向集成测试和等价主会话审查。
- 安全：无新增 secret、原始异常或外部网络路径；网络熔断保持 ENABLED，并覆盖 requests 与 socket 层。
- 依赖边界：`src/venagent/**` 与 `apps/**` 不导入 `final/**`。

本轮不再启动后台专项代理；对延迟专项审查报告逐项执行了等价主会话复核、回归测试和完整验证，未将本地检查表述为新的代理调用。

## 保留风险与后续边界

- P1-09 仍未将 `APIConfig/build_deps` 完整收敛为兼容 façade；P1-10 仍未完成旧入口的完整启动/关闭/降级集成门禁。
- `final/internal/infra/Infrastructure` 的旧构造器仍负责真实连接；本 Sprint 只建立新生命周期边界，不提前完成旧基础设施 provider 迁移。
- legacy `restore_from_db`、`restore_rag_from_db`、`init_sandbox` 内部仍保持 best-effort 行为；更细粒度 capability catalog/授权语义属于 Phase 2。
- 新 health snapshot 尚未替换旧 `/health` 或 `/api/status` 外部 envelope，避免提前改变 HTTP 契约。
- 未安装 `pytest-asyncio`、ruff、pyright 等未获批准依赖；生命周期测试使用标准库 asyncio，ruff/pyright 没有被虚构为已执行。

## 交付判定

Sprint 03 收口通过。不得据此宣称旧入口已完成兼容 façade、完整集成门禁或 Phase 1 全部结束；Sprint 04 仍需单独生成计划并取得用户审批。
