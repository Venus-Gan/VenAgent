# Outcome

测试输入与现有的 `LLM_*` / `VENAGENT_DATABASE_URL` 运行时兼容契约一致。

# Scope

- 恢复 `tests/test_llm.py` 中的 `LLM_*` 测试环境变量。
- 更新 `tests/test_config.py` 对旧变量接受与未知嵌套变量拒绝的断言。

# Non-goals

- 不修改运行时代码、YAML 配置或真实 `.env`。
- 不运行配置和 LLM 测试套件。

# Acceptance examples

- LLM 用例通过 `LLM_API_KEY`、`LLM_PROVIDER` 等现有变量名构造测试环境。
- 配置用例验证 `LLM_API_KEY` 被接受，未声明的 `VENAGENT_*__*` 键仍被拒绝。

# Constraints and invariants

- 不在测试数据或 Comet 产物中记录真实秘密值。

# Decisions

- 用户明确要求更新测试代码，但暂不运行完整配置与 LLM 测试。

# Open questions

- 无。

# Verification expectations

- 检查替换范围与测试文件语法；配置和 LLM 测试执行按用户要求跳过。
