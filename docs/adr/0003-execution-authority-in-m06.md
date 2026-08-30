# ADR-0003: 执行权威归 M06 与工具限制语义

工具调用每步回到 M06 单工具闭环作为唯一权威（审批、沙箱、幂等、审计均在此层）；外层编排只做选择与编排，不兼任工具授权、审批恢复或终止判断。两层工具限制取消：每轮绑定 tools，M06 内以稳定错误拒绝而非重试。这保证了权限与副作用事实只有一处事实源（tools/control 的 ToolGateway/ApprovalService/InvocationStore 边界）。

来源：Wayfinder 票 `剩余功能规划` Q4（resolved）。
