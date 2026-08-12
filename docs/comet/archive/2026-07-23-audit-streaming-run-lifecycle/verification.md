# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-29dc716375b0a6db4a2f3b9306c1c877ddcedbf29300b7729184349cfe50266a",
    "evidence_refs": [],
    "skipped_reason": "该项是审计与规格验收；定向文本断言和源码定位已确认建流前 JSON 错误与建流后 SSE error 终态边界，本 change 没有运行时代码产物。"
  },
  {
    "acceptance_id": "acceptance-7f1d8204b97057efc55efab3309befb3ae1fb2c34164eae45e56766b8a468cf2",
    "evidence_refs": [],
    "skipped_reason": "完整目标规格文本断言已确认 started、token、唯一 completed/cancelled/error、目标取消和 M01 提交边界；代码实现由后续独立 change 交付。"
  },
  {
    "acceptance_id": "acceptance-990c1090f0905878424b1a7fa9d402909a9424b1b9825ca61946b3eec43b148d",
    "evidence_refs": [],
    "skipped_reason": "brief、audit 与完整规格已记录整体 replace 和各子能力的 adopt/replace/drop/defer 边界；这是规格事实而非运行时证据。"
  },
  {
    "acceptance_id": "acceptance-a765da83c57b58cc8f3a34cf53355d294bc04d9e518b397880f3f308eee692e6",
    "evidence_refs": [],
    "skipped_reason": "源码定位确认当前 venagent 仅有同步 chat、ThreadRegistry busy 与 model.invoke 成功提交路径；本审计不修改这些项目文件。"
  },
  {
    "acceptance_id": "acceptance-c2bbe8173343e91ad4e0f4c10545d9d8b33dc9c8ff08360eb2278cd8e4ffcbe1",
    "evidence_refs": [],
    "skipped_reason": "Build 使用明确 no-code reason 封存完整 scope；71 项现有测试通过，运行时代码将在归档后的独立 M02 implementation change 中验证。"
  },
  {
    "acceptance_id": "acceptance-cca20d61efbb1147b2cffd2f992088824c8038d025419a9b66a67bd116752289",
    "evidence_refs": [],
    "skipped_reason": "审计与规格已分别定义浏览器停止、网络断开、accepted 取消信号和服务端权威终态；当前 change 无可执行流式实现。"
  },
  {
    "acceptance_id": "acceptance-d31559acd5bb5e4bf02a02ff21ebb9bcbbe2757e475a558fdad4f03f8bdeedd0",
    "evidence_refs": [],
    "skipped_reason": "源码定位确认旧 CancelRegistry.cancel_all 会取消全部 in-flight token，且旧 /api/chat/cancel 不接收目标 run ID；本 change 只记录替换决策。"
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `.\\.venv\\Scripts\\python.exe -m pytest -q`：通过，71 项测试通过；存在 1 条 Starlette/httpx 弃用警告，不影响结论。
- `comet native check audit-streaming-run-lifecycle --json`：通过，receipt 为 `runtime/evidence/check-receipts/bb9620bc5f9c9b3da2421f3a630c3f2e8b81cafb413183ba2d2511e454cabbba.json`；implementation scope 无项目实现文件，因此 selected/scanned 均为 0，issue 为 0。
- PowerShell M02 契约断言：通过，10/10 为 true；覆盖 replace、无 open question、旧 cancel-all/done 事实、两条 API、三种终态、完整 answer、active-only registry 与无断线续传。
- `rg` 当前实现定位：通过；确认 `venagent/api.py` 只有同步 chat，`conversation.py` 提供 ThreadRegistry，`agent_loop.py` 仍通过 `model.invoke` 成功返回后提交。
- `rg` 旧参考定位：通过；确认 cancel-all、无目标 `/api/chat/cancel`、daemon worker、0.5 秒 join、`[DONE]` 和模型前预写 user 历史。

# Skipped checks

- 未运行真实 provider token streaming、浏览器流式 E2E、目标取消或网络断开测试；本审计 change 按批准范围不修改运行时代码，这些检查由后续独立 M02 implementation change 执行。
- 未访问网络、真实模型或凭据；所有现有项目测试均使用本地可控路径。

# Spec consistency

- `streaming-run-lifecycle` 完整规格与 canonical M01 一致：同步 `/api/chat` 保留，同线程单活跃，只有完整成功轮次提交，失败和 partial token 不进入上下文。
- 与路线边界一致：M02 只定义 SSE、文本 delta、run ID、目标取消、断开和流中错误；持久化/重启恢复留给 M03，身份授权留给 M04，可靠恢复留给 M15。
- 用户确认的全部决定已进入 brief 与规格，Open questions 为“无”；没有把推荐项保留为未确认契约。

# Known limitations and risks

- 本结论验证的是审计和规格完整性，不证明 token streaming 运行时代码已经存在或通过。
- 协作式取消无法保证任意 provider 立即停止；后续实现必须用可控阻塞模型验证 busy lease、取消/完成竞态和最终释放。
- `run_id` 与 `thread_id` 在 M04 前不构成授权凭据；当前能力仅适合单用户或受信环境。
- 内置 check 的扫描文件数为 0，因为 implementation scope 是诚实的 no-code scope；它只证明 receipt 新鲜和无 scoped 文本问题，不替代项目测试或规格断言。

# Conclusion

PASS。M02 专项审计、整体 replace 取舍、完整目标规格、相邻模块边界和后续实现验收基线均已明确；71 项现有测试与定向事实/契约检查通过。当前 change 可以进入 Archive，token streaming 与运行时代码由随后独立 M02 implementation change 实现。
