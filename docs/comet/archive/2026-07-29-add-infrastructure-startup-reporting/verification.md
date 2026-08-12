# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-071b28065cce49b5461b350209240910baf03303d0dc8361219bb230fb345623",
    "evidence_refs": [
      "tests/test_persistence.py",
      "tests/test_startup_reporting.py",
      "venagent/observability.py"
    ]
  },
  {
    "acceptance_id": "acceptance-0970d4e4aa59ad2632938e2431adccf86d27495cc8338dfa5c5525280c9b9ca1",
    "evidence_refs": [
      "tests/test_persistence.py",
      "venagent/infra/platform/runtime.py",
      "venagent/observability.py"
    ]
  },
  {
    "acceptance_id": "acceptance-1dc223845e238e58464dfc6d136544c68af0f324a44a35b589d858b4b1e05683",
    "evidence_refs": [
      "tests/test_startup_reporting.py",
      "venagent/observability.py"
    ]
  },
  {
    "acceptance_id": "acceptance-5552338144538bdd59a41b104b0a1fcb0a1e8e1672116d337d331811de61fca4",
    "evidence_refs": [
      "tests/test_persistence.py",
      "venagent/infra/platform/runtime.py",
      "venagent/observability.py"
    ]
  },
  {
    "acceptance_id": "acceptance-5a1ff93f9ebf185890ff5b84d692e80aa432d0cb1976982efc89a101bee9f6dc",
    "evidence_refs": [
      "tests/test_persistence.py",
      "tests/test_startup_reporting.py",
      "venagent/infra/platform/runtime.py"
    ]
  },
  {
    "acceptance_id": "acceptance-d3692307a58b33e2f072195216726a44ed3cc09459658839b16adc1b11993721",
    "evidence_refs": [
      "tests/test_startup_reporting.py",
      "venagent/interfaces/http/app.py",
      "venagent/observability.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `.\.venv\Scripts\python.exe -m pytest tests\test_startup_reporting.py -q`：先按 TDD 运行，因 `_build_log_config` 尚不存在而失败；实现后 3 项通过。
- `.\.venv\Scripts\python.exe -m pytest tests\test_startup_reporting.py tests\test_persistence.py tests\test_config.py -q`：21 项通过，1 项真实 PostgreSQL 集成测试因未配置环境而跳过。
- `.\.venv\Scripts\python.exe -m pytest -q`：首次发现 10 项 `PersistenceStatus` 四参数构造兼容回归；保留原构造签名并改为只读通用状态投影后，最终 140 项通过，1 项跳过。
- `.\.venv\Scripts\python.exe -m compileall -q venagent tests`：通过。
- `comet native check add-infrastructure-startup-reporting --json`：通过；扫描 8 个范围文件、48803 字节，0 个问题，receipt 为 `runtime/evidence/check-receipts/d58a92ee79a84833b6f329532e0f11f0be7e42f8336deeafa5706ee141c622a5.json`。
- 定向敏感信息检索只命中测试哨兵连接串与 README 的环境变量说明；测试断言哨兵用户名和密码不会进入日志。

# Skipped checks

- 未设置 `VENAGENT_TEST_DATABASE_URL`，因此真实 PostgreSQL migration/restart 集成测试跳过；用户选择自行启动已配置后端观察正常连接输出。
- `ruff`、`mypy`、`black`、`isort`、`bandit` 和 `pip-audit` 未安装，未运行且不记录为通过。
- 未完成真实 CLI 控制台验收：隔离启动环境缺少默认真实 LLM provider 所需的 `LLM_API_KEY`，随后用户明确选择手动启动查看效果。日志配置、自然语言输出、lifespan 单次输出和 `/health` 一致性均由隔离测试覆盖。

# Spec consistency

- `InfrastructureStatus` 和 `StartupReport` 为不可变统一状态；`log_startup_report` 只遍历状态并按统一级别映射输出，不含组件专属分支。
- PostgreSQL 继续保留既有 `PersistenceStatus` 构造与 durable/temporary 选择，通过只读属性投影到通用状态，避免相邻模块回归。
- `bootstrap.py` 显式聚合基础设施状态；FastAPI lifespan 在进入服务态前输出一次报告；CLI 复制 Uvicorn 默认配置并只开启 `venagent` INFO 命名空间。
- `/health` 继续从同一 `PersistenceStatus` 事实生成，字段和 HTTP 语义未改变。
- 固定运维文案不拼接原始异常、连接串或秘密；新增代码在状态投影、聚合、日志配置与生命周期位置包含职责注释。

# Known limitations and risks

- 本次没有在当前机器上完成真实可用 PostgreSQL 的控制台输出观察；自动化覆盖状态投影和报告行为，真实环境输出由用户手动确认。
- 启动报告是每个应用进程的一次启动快照，不持续探测运行中依赖；这与规格一致。
- 当前 composition root 只装配 PostgreSQL。未来基础设施仍需显式加入 `StartupReport.infrastructure`，但通用报告函数无需修改。

# Conclusion

自动化实现、回归、语法和 Comet 范围检查通过，未发现阻塞性正确性、安全或 FastAPI 边界问题。真实 PostgreSQL 控制台观察作为已披露的手动验收项，不影响当前实现进入归档。
