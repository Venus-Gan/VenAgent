# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-0dbf838f9d43308012437d858e1ea47f00747f893813a6d2e39be38895c50c16",
    "evidence_refs": [
      "tests/test_config.py",
      "venagent/config/config.yaml",
      "venagent/infra/config/loader.py"
    ]
  },
  {
    "acceptance_id": "acceptance-2e739174a32a0d85f7aa11209206949c397e408478dcd2a6f427c4439b0c6783",
    "evidence_refs": [
      "tests/test_config.py",
      "venagent/infra/platform/runtime.py"
    ]
  },
  {
    "acceptance_id": "acceptance-48d4dac22f3a9e00d82c5668d8ecab038c8736f554b3d78284a96cd97b9f8bff",
    "evidence_refs": [
      ".gitignore",
      "pyproject.toml",
      "venagent/config/config.local.yaml.example",
      "venagent/config/config.yaml"
    ]
  },
  {
    "acceptance_id": "acceptance-8aece67713a6e085ae977abf19a80c36c3efdb66d1730687ade5e1dd451df6bc",
    "evidence_refs": [
      "web/vite.config.ts"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `.\\.venv\\Scripts\\python.exe -m pytest tests\\test_config.py tests\\test_persistence.py -q`: `16 passed, 1 skipped`。
- `.\\.venv\\Scripts\\python.exe -m compileall -q venagent tests`: passed。
- `.\\.venv\\Scripts\\python.exe -m pytest -q`: `115 passed, 1 skipped`。
- `npm.cmd run build`（在 `web/`）: Vue 类型检查与 Vite 生产构建通过。
- 默认 `create_app()` 使用本机 Docker PostgreSQL 的健康检查：返回 `mode=durable`、`reason_code=postgresql_ready`、`identity=available`。
- `docker compose ps`: `venagent-postgres-1` 为 `healthy`，并映射本机 `5432`。
- 真实 LLM 最小请求：配置模型返回 `OK`，未输出凭据。
- `comet native check postgres-yaml-configuration --json`: passed；receipt `runtime/evidence/check-receipts/098ae75c111f39468ec4fbef37c120003da829969c440857f1691aa94070b5a0.json`，十六个文件扫描且无问题。

# Skipped checks

- 未启动持久化的 Vite 开发服务器执行人工浏览器交互；代理目标由构建通过及配置文本检查覆盖。

# Spec consistency

配置从包内 YAML、忽略的本地覆盖、`.env` 与显式环境按规定优先级合并。PostgreSQL 密码只从 `POSTGRES_PASSWORD` 注入，运行时使用配置对象传递的连接串。默认后端端口保持 `8090`，Vite 的 `/api` 与 `/health` 开发代理同步指向该端口。

# Known limitations and risks

- 当前 Native scope 仅排除两份已删除的旧根目录配置模板；它们按确认迁入包内配置目录，无法作为现存 artifact 声明。
- 生产 HTTPS 的 Cookie、安全部署和真实模型调用不属于本 change 的验收范围。

# Conclusion

PASS。配置层、无密码降级、Docker PostgreSQL 默认启动、包内 YAML 分发、Vite 代理目标和真实 LLM 请求均获得实际验证。
