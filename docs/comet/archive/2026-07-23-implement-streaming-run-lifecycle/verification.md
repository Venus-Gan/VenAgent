# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-0a65dc3c735808c87d1f3d57b453f9d219e758f32add2b1d735178382fd99e51",
    "evidence_refs": [
      "tests/test_streaming.py",
      "tests/test_streaming_api.py",
      "venagent/agent_loop.py"
    ]
  },
  {
    "acceptance_id": "acceptance-0bf959ba5d213ce16f3651b2b406a5d5e522e88069b6ccf559452491d0458e60",
    "evidence_refs": [
      "tests/test_streaming_api.py",
      "venagent/api.py",
      "venagent/conversation.py"
    ]
  },
  {
    "acceptance_id": "acceptance-0d5d8dec91e366fc3574805f9e8f390e83bae0cafb665d1673cb87ddc8ad771f",
    "evidence_refs": [
      "tests/test_streaming_api.py",
      "venagent/agent_loop.py",
      "venagent/streaming.py"
    ]
  },
  {
    "acceptance_id": "acceptance-214e6fd39b38aa6d45279e7771df1ed5ce0c9e6928421fdd857e85b6f01f1f16",
    "evidence_refs": [
      "tests/test_streaming_api.py",
      "venagent/api.py"
    ]
  },
  {
    "acceptance_id": "acceptance-436441c45d4c1539a3a7d5b16467438b43f4f0413338bdac35e719de39270870",
    "evidence_refs": [
      "tests/test_runs.py",
      "tests/test_streaming_api.py",
      "venagent/runs.py"
    ]
  },
  {
    "acceptance_id": "acceptance-594f7cf3ab91a197276e18ebcb9297fd6792db8d709c88cf9c8772829e0df48a",
    "evidence_refs": [
      "tests/test_api.py",
      "tests/test_streaming_api.py",
      "venagent/api.py",
      "venagent/web/index.html"
    ]
  },
  {
    "acceptance_id": "acceptance-b44ab05a981c8ce40bed937c8337923695d353909cdb06e48f6e759c3b06b0dc",
    "evidence_refs": [
      "tests/test_api.py",
      "venagent/web/index.html"
    ]
  },
  {
    "acceptance_id": "acceptance-daf02652ea50226a929a3ef9148638fafc144de570c87f4e30f27566b01d2861",
    "evidence_refs": [
      "tests/test_runs.py",
      "tests/test_streaming.py",
      "tests/test_streaming_api.py",
      "venagent/runs.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `.\\.venv\\Scripts\\python.exe -m pytest -q`：通过，87 项测试通过；存在 1 条 Starlette/httpx 弃用警告。
- `.\\.venv\\Scripts\\python.exe -m pytest -q tests\\test_runs.py tests\\test_streaming.py tests\\test_streaming_api.py`：通过，16 项 M02 专项测试通过。
- Node stdin JavaScript 语法检查：通过，`venagent/web/index.html` 内嵌脚本可由 `new Function` 编译。
- `.\\.venv\\Scripts\\python.exe -m compileall -q venagent`：通过，无 Python 语法或导入编译错误。
- TestClient SSE 探针：通过，实际响应为 `text/event-stream`，事件顺序为 `started → token → completed`，completed 携带完整 answer。
- `comet native check implement-streaming-run-lifecycle --json`：通过；receipt 为 `runtime/evidence/check-receipts/0dd82f6c64e5a77e6ef91b278dbdcb179eb8e781a2b25b79131e675a10e021cc.json`，10/10 scope 文件扫描，0 issue，结果 fresh。
- implementation scope `83978eb9e02d09aba49f054159adc1af780bb28bff415913ac9153a56e08ec9d`：complete，10 个声明 artifact，0 unattributed，0 unresolved。

# Skipped checks

- 未调用真实 OpenAI、Anthropic、Google、Azure 或 OpenAI-compatible provider；使用 Runnable/fake async stream 验证公开 streaming 边界，避免网络和真实凭据。
- 未启动交互式浏览器执行人工点击；Web UI 由 JavaScript 语法检查、静态契约断言和 API/ASGI 集成测试覆盖。
- 未验证跨进程恢复、断线续传、run status 或 owner 授权；这些是 canonical M02 的明确非目标。

# Spec consistency

- 同步 `/api/chat` 保持 M01 JSON 行为；新增 `/api/chat/stream` 和目标 `/api/runs/{run_id}/cancel`，没有 Accept 合并或失败后同步自动回退。
- `run_id`、active-only registry、重复取消 accepted、非法 400、未知/结束 404 与 canonical 规格一致。
- token 直接使用 provider/LangChain 非空文本 delta；SSE 只有 started/token 和唯一 completed/cancelled/error，completed 携带完整 answer。
- Agent Loop 只在完整流结束后通过 LangGraph 公共 `update_state` 提交完整轮次；取消、异常和断开不会提交 partial。
- ASGI disconnect 与 StreamingResponse background cleanup 都会协作式取消并释放 run/thread lease，不使用旧全局 cancel-all 或 daemon worker。
- Web UI 只取消当前 run，区分 generating/cancelling/cancelled/failed，保留 partial 文本并要求用户显式重试。

# Known limitations and risks

- 协作式取消依赖 provider 对 async cancellation 或下一次 chunk/timeout 的响应；同步 fallback 会保持 thread busy 直到底层 invoke 收口，不声称立即强杀。
- M02 只保存 active run；运行结束后 cancel 返回 404，且没有结果查询或断线续传。
- `run_id` 与 `thread_id` 在 M04 前不是授权凭据，能力仅适合单用户或受信环境。
- 当前测试环境持续报告 Starlette TestClient/httpx 弃用警告；不影响 87 项测试结论，但后续依赖维护应处理。

# Conclusion

PASS。M02 streaming-run-lifecycle 已按批准契约实现：独立 SSE、provider delta、完整 answer 终态、目标取消、断开清理、成功后提交和最小 Web UI 流式体验均有离线测试证据；scope 完整且无未归属变化，可以进入 Archive。
