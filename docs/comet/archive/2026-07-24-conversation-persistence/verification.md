# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-5d06911a33906a52188de32c80ac77c4fb66866077b2b81dbca4f998cf3a4b00",
    "evidence_refs": [
      "tests/test_api.py",
      "tests/test_runs.py",
      "tests/test_streaming_api.py"
    ]
  },
  {
    "acceptance_id": "acceptance-747ee77486dcf6cac251185fc5d06046123577c0e743d8707cb58e4e78566092",
    "evidence_refs": [
      "tests/test_agent_loop.py",
      "tests/test_persistence.py"
    ]
  },
  {
    "acceptance_id": "acceptance-7b76a06d2b5cca88081634a2f49596dc19f998eb18e30ed5adb67d0b47f7ec3f",
    "evidence_refs": [
      "tests/test_agent_loop.py",
      "tests/test_streaming.py",
      "tests/test_streaming_api.py"
    ]
  },
  {
    "acceptance_id": "acceptance-a0ef6fc68867d5c17fbd18018b3220131c6a248d70f2b2789327924106f1f3fb",
    "evidence_refs": [
      "tests/test_persistence.py",
      "venagent/api.py",
      "venagent/persistence.py"
    ]
  },
  {
    "acceptance_id": "acceptance-b6c42e875b59313c61eca118851eef42fb5faba53c7f00054c4e80bbab2f3f60",
    "evidence_refs": [
      "tests/test_persistence.py",
      "venagent/conversation.py",
      "venagent/web/index.html"
    ]
  },
  {
    "acceptance_id": "acceptance-da0c6bafe0796332720d980e82c9b3da1363c9cbbbd5b041585fd9ca5595bb53",
    "evidence_refs": [
      "tests/test_conversation.py",
      "tests/test_persistence.py"
    ]
  },
  {
    "acceptance_id": "acceptance-f386d9251599653de3e1d5bf67083e2aff7a46aee6a5f2610d9dc1c14c9f7be4",
    "evidence_refs": [
      "tests/test_persistence.py",
      "venagent/persistence.py"
    ]
  },
  {
    "acceptance_id": "acceptance-f515b6b8456c70adbca22489dc383a6204a901a428654e0e3cce81058122c800",
    "evidence_refs": [
      "tests/test_persistence.py",
      "venagent/persistence.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `VENAGENT_TEST_DATABASE_URL=<redacted> python -m pytest -q`：96 passed，包含真实 PostgreSQL 显式迁移、v1→v2 成功升级、失败升级不标记、重启恢复、继续对话和删除清理。
- `python -m compileall -q venagent tests`：通过。
- Web 内联脚本使用 Node `new Function` 语法检查：通过。
- `python -m pip check`：通过，无损坏依赖。
- `docker compose config --quiet`：通过；Docker 用户配置权限警告不影响 Compose 解析。
- `git diff --check -- .`：通过；只有既有工作区 CRLF 转换提示。
- `comet native check conversation-persistence --json`：通过，13 个范围内文本文件无问题。

# Skipped checks

无。

# Spec consistency

持久 checkpointer、自有线程/import 表、连续版本迁移、固定模式降级、健康状态、中文启动说明、删除清理和受限浏览器导入均与规格一致。

# Known limitations and risks

M04 前 `thread_id` 仍不是身份凭据；active run、SSE 事件和 partial token 仍按非目标不持久化。Docker 用户配置权限警告不影响 Compose 配置和实际容器测试。

# Conclusion

通过。8 个派生验收项均有项目内证据，完整测试与真实 PostgreSQL 验证通过。
