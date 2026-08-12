# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-0429a12294351cb72ae437d81e810e0fa42f2cb7fb2d1e6b82a0b9ffea0e16b1",
    "evidence_refs": [
      "tests/test_migration_v4.py",
      "tests/test_persistence.py",
      "venagent/infra/platform/migrations.py",
      "web/src/modules/chat/store.ts"
    ]
  },
  {
    "acceptance_id": "acceptance-3998380b190eb918979dbcade8f048bfab15d97981350167e20535719758014e",
    "evidence_refs": [
      "tests/test_ownership.py",
      "web/tests/e2e/workspace.spec.ts"
    ]
  },
  {
    "acceptance_id": "acceptance-55c65f331b991c84c24deec7e73604ac8b3b67fdad5bca37f58c6d281ee3f489",
    "evidence_refs": [
      "tests/test_ownership.py",
      "web/src/modules/chat/store.ts",
      "web/tests/e2e/workspace.spec.ts"
    ]
  },
  {
    "acceptance_id": "acceptance-aa8e4d36c8075ff987a9bce75e9b3187b0a2da831540031d2fa5ee9ad0e583dc",
    "evidence_refs": [
      "tests/test_commit_recovery.py",
      "tests/test_ownership.py",
      "venagent/conversation/service.py"
    ]
  },
  {
    "acceptance_id": "acceptance-bfeda7c781002554d491e4976fc7ad374e3f001dc3d5a08e86eca09880f76495",
    "evidence_refs": [
      "tests/test_ownership.py",
      "web/src/modules/chat/store.ts",
      "web/tests/e2e/workspace.spec.ts"
    ]
  },
  {
    "acceptance_id": "acceptance-bff4128bdaa4c09933a4b6896bbd7cefcbc209ee8393e8e5123ae0bf5daf515f",
    "evidence_refs": [
      "tests/test_commit_recovery.py",
      "tests/test_streaming_api.py",
      "venagent/conversation/service.py"
    ]
  },
  {
    "acceptance_id": "acceptance-d787f3e8d71cb75b086fea11efc544bd1d956b99afdd674186199d2e27aa0e26",
    "evidence_refs": [
      "tests/test_api.py",
      "tests/test_ownership.py",
      "venagent/infra/security/tokens.py"
    ]
  },
  {
    "acceptance_id": "acceptance-f23db4c9b9523d2067c3f2a9a5250de68124ff75147a4f35f9f1f73957545673",
    "evidence_refs": [
      "tests/test_commit_recovery.py",
      "tests/test_ownership.py",
      "venagent/conversation/service.py"
    ]
  },
  {
    "acceptance_id": "acceptance-fd7e0662d1ebb9005306b9a7afd3f1357f87c93ed932afd7a9999a27736a71ef",
    "evidence_refs": [
      "tests/test_ownership.py",
      "tests/test_persistence.py",
      "web/tests/e2e/workspace.spec.ts"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `.\.venv\Scripts\python.exe -m pytest -q`：130 passed，1 skipped；跳过项是未配置隔离 PostgreSQL 的集成测试。
- `npm.cmd run build`（`web/`）：Vue TypeScript 检查与 Vite production build 通过。
- `npm.cmd run test:e2e`（`web/`）：5 passed，覆盖临时匿名、仅本地迁移、双浏览器账号历史、标题和移动抽屉焦点。
- `.\.venv\Scripts\python.exe -m compileall -q venagent tests`：通过。
- `.\.venv\Scripts\python.exe -m pip check`：No broken requirements found。
- `comet native check ownership-lifecycle --json`：45/45 scope 文本文件完成扫描，0 issue，receipt 为 `runtime/evidence/check-receipts/40f7154250791b02f4722c8aff0a8add021b5306f8bf4ec38bc0f99ba6fe82d1.json`。

# Skipped checks

- 未设置 `VENAGENT_TEST_DATABASE_URL`，因此没有执行真实 PostgreSQL v4 migration/restart 集成用例；迁移顺序、公共 checkpoint 枚举/删除、失败不记录 v4 与幂等边界由 fake connection/saver 测试覆盖。
- 当前虚拟环境未安装 Ruff、mypy、Bandit 或 pip-audit，因此未把这些外部工具写成通过；已执行 compileall、依赖一致性检查、定向人工安全审查和全量测试。

# Spec consistency

实现范围完整覆盖已确认 M04：匿名与账号 actor、15 分钟 access JWT、opaque refresh Cookie、账号生命周期、owner-scoped history/title、七天匿名清理与限额、业务 history/checkpoint 修复、v3 到 v4 清理迁移、temporary 匿名降级以及单工作区 Vue 交互。未引入邮箱、找回、MFA、RBAC、组织、管理后台或匿名历史认领。

# Known limitations and risks

- 当前 M04 明确只支持单 API 进程；进程内 run registry、refresh 宽限和创建频率窗口不声称跨 worker 一致。
- 真实 PostgreSQL 行为仍需在提供隔离测试数据库后运行现有集成用例确认；普通启动不会自动执行 DDL。
- 离线其他浏览器的账号缓存不能被远程擦除，只会在下次身份校验失败后由前端隐藏和清理。

# Conclusion

PASS。实现与已确认规格一致，自动化回归、前端构建、浏览器交互和 Comet scope 安全检查均通过；唯一跳过项已明确记录且不伪装为通过。
