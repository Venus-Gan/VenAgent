"""M06 tools 审批服务契约（单点）。

- decide_detailed 幂等（同审批重复决定不改变状态），且反向决定产生冲突：
  本文件单点（从 tests/agent/test_m06_agent_tool_loop.py 迁入）。

「拒绝后模型解释」「审批过期」分别由 tests/agent/test_m06_langgraph.py
与 agent 机制侧单点覆盖。
"""

from __future__ import annotations

from venagent.tools.approval import ApprovalService


def test_approval_decide_detailed_is_idempotent_and_conflict_aware() -> None:
    approvals = ApprovalService()
    item = approvals.create(
        run_id="run-approval",
        owner_id="owner-approval",
        operation_id="op-approval",
        tool_id="exec_command",
        tool_call_id="call-approval",
        reason="test",
    )
    first, changed1, conflict1 = approvals.decide_detailed(
        item.approval_id, "owner-approval", True
    )
    second, changed2, conflict2 = approvals.decide_detailed(
        item.approval_id, "owner-approval", True
    )
    assert first.status == "approved"
    assert changed1 is True
    assert conflict1 is False
    assert second.status == "approved"
    assert changed2 is False
    assert conflict2 is False

    _third, _changed3, conflict3 = approvals.decide_detailed(
        item.approval_id, "owner-approval", False
    )
    assert conflict3 is True