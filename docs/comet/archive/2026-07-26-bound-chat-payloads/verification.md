# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-0def1cc68a22215d2929a1bf582c6d33184d43da4fc74bd84a7dd62b2a632b47",
    "evidence_refs": [
      "tests/test_streaming.py",
      "venagent/agent/runtime.py"
    ]
  },
  {
    "acceptance_id": "acceptance-49daafd75ced3e4e042afd37c5a49d911d4f59e1e376cad95260c34d4afca923",
    "evidence_refs": [
      "venagent/agent/graph.py"
    ]
  },
  {
    "acceptance_id": "acceptance-90a9cfe2ee8d0f1808f4e8be8b8aec8802b65c02177b9f2b730e8aa682fa0489",
    "evidence_refs": [
      "tests/test_streaming.py",
      "tests/test_streaming_api.py",
      "venagent/interfaces/http/streaming.py"
    ]
  },
  {
    "acceptance_id": "acceptance-d340994ea885caf82f75dca7ad0e0e42ce28c03577c3face7a90dba81dd335b7",
    "evidence_refs": [
      "tests/test_agent_loop.py",
      "tests/test_api.py",
      "venagent/agent/runtime.py",
      "venagent/interfaces/http/schemas.py"
    ]
  },
  {
    "acceptance_id": "acceptance-f3f4284bb76a399875471125610231f60ab5558b3714e3c6876b8cd528c41340",
    "evidence_refs": [
      "tests/test_llm.py",
      "venagent/infra/llm/factory.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `python -m pytest tests/test_llm.py tests/test_agent_loop.py tests/test_api.py tests/test_streaming.py tests/test_streaming_api.py -p no:cacheprovider`
  - 84 passed in 105.43 seconds.
- 新增边界测试单独运行：3 passed in 15.92 seconds。
- `git diff --check`
  - 未发现空白错误；输出仅包含既有用户工作树文件的 CRLF 提示。
- 已人工复核 Python、FastAPI、错误映射与流式清理边界：输入在 schema 与运行时双层校验；输出超限在 checkpoint 写入前终止；`OutputLimitExceeded` 被映射为 `output_limit_exceeded`。

# Skipped checks

- Ruff、mypy、Bandit、pip-audit 未安装，且本 change 不以外部静态工具作为硬门槛。
- 未运行全仓 pytest；本次运行了覆盖所有变更路径及其直接集成面的 84 项相关测试。

# Spec consistency

实现保持当前 `START → agent → END` 图结构与五轮历史窗口。显式 LLM mapping 仅由调用方提供的值解析，生产配置路径保持使用 `AppConfig` 与加载器。超限流不写入完整轮次，因此不会把部分用户消息或回答加入已提交历史。

# Known limitations and risks

本 change 按已确认范围不加入流式总时长、token-aware 上下文裁剪或未来工具循环限制。输出字节预算只限制产生文本的累计大小；无输出且不结束的上游流需要后续以超时策略处理。

# Conclusion

LLM 测试隔离、32 KiB UTF-8 输入边界、128 KiB UTF-8 流式输出边界和 `output_limit_exceeded` 终止语义均已实现并通过相关回归测试。
