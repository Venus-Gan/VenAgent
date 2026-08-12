# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-1bf6b2e772e56be85db39d9900855065c767d9759b7c3fe89733f628b4cc437a",
    "evidence_refs": [
      "README.md",
      "tests/test_package_layout.py",
      "venagent/__main__.py"
    ]
  },
  {
    "acceptance_id": "acceptance-2288f8b0885742c49a7d13e4ed99422aa1aef5d6a37f5e9cd956d179da53880a",
    "evidence_refs": [
      "tests/test_package_layout.py",
      "venagent/agent",
      "venagent/conversation",
      "venagent/infra",
      "venagent/interfaces"
    ]
  },
  {
    "acceptance_id": "acceptance-4e104fb50a2077f451b28e691b296b7cbe1c7eb83173aa3726c421c560adf0d4",
    "evidence_refs": [
      "tests/test_package_layout.py",
      "venagent/agent",
      "venagent/bootstrap.py"
    ]
  },
  {
    "acceptance_id": "acceptance-96ca387a2c8a4d788458ef89a5e72262b5dc8456ffd6d18926494bd0201d0c98",
    "evidence_refs": [
      "tests/test_package_layout.py",
      "venagent/conversation/ports.py",
      "venagent/conversation/service.py",
      "venagent/infra/persistence"
    ]
  },
  {
    "acceptance_id": "acceptance-cdca2ecf4547144f98cbb63284692a409906f6d50ae41fe6fc5b367cefd44e3c",
    "evidence_refs": [
      "tests/test_api.py",
      "tests/test_persistence.py",
      "tests/test_streaming_api.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `VENAGENT_TEST_DATABASE_URL=<redacted> python -m pytest -q`：99 passed，包含真实 PostgreSQL 迁移、重启恢复与新架构约束。
- `python -m compileall -q venagent tests`：通过。
- `python -m venagent --help`：通过，serve/migrate CLI 保持可用。
- `python -m pip check`：通过，无损坏依赖。
- Web 内联脚本 Node 语法检查：通过。
- `docker compose config --quiet`：通过；Docker 用户配置权限警告不影响解析和真实容器测试。
- `git diff --check`：通过；只有工作区既有 CRLF 转换提示。
- `comet native check feature-first-package-layout --json`：通过，44 个范围内文本文件无问题。

# Skipped checks

无。

# Spec consistency

目录按 conversation/agent 能力优先聚合，infra 与 interfaces/http 位于边缘；Protocol 由 conversation 消费方拥有，bootstrap 集中装配。旧扁平实现文件已删除，HTTP、CLI、数据库和 Web 行为保持不变。

# Known limitations and risks

内部 Python 模块路径发生有意变化且未提供旧扁平 shim；稳定的顶层 Agent 导出、HTTP 与 CLI 入口仍保留。`final/` 继续只是旧实现参考，不属于本次新 runtime 重构范围。

# Conclusion

通过。5 个派生验收项均有项目内证据，完整测试和真实 PostgreSQL 验证通过。
