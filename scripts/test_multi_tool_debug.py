#!/usr/bin/env python
"""调试多工具执行问题"""
import asyncio
import sys
import traceback
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tests.agent.conftest import _agent_harness
from langgraph.checkpoint.memory import InMemorySaver


async def debug_multi_tool():
    harness = _agent_harness()
    store = harness.make_store()
    actor, run_id = harness.create_test_run(store)
    control, calls = harness.make_tool_control(
        descriptors=(harness.exec_descriptor("safe"),),
        available_servers=frozenset(),
        risk_overrides=(("exec_command", "safe"),),
    )
    saver = InMemorySaver()
    model = harness.ToolCallingModel(
        (
            {
                "id": "call_1",
                "name": "exec_command",
                "args": '{"command":"printf one"}',
                "index": 0,
            },
            {
                "id": "call_2",
                "name": "exec_command",
                "args": '{"command":"printf two"}',
                "index": 1,
            },
        )
    )
    runtime = harness.make_runtime(
        model, store, tool_control=control, checkpointer=saver
    )
    
    try:
        await harness.await_status(store, actor.owner_id, run_id, "succeeded", timeout=5.0)
        print("✓ Run succeeded")
        print(f"Model calls: {model.calls}")
        print(f"Tool calls: {calls}")
        print(f"Operations: {len(control.operations.list_by_run(run_id))}")
    except Exception as e:
        print(f"✗ Run failed: {e}")
        traceback.print_exc()
        
        # 检查 run 状态
        run = store.get_run(actor.owner_id, run_id)
        if run:
            print(f"\nRun status: {run.status}")
            print(f"Run failure: {run.failure}")
        
        # 检查 checkpoint
        print("\n=== Checkpoint History ===")
        for checkpoint in saver.list({"configurable": {"thread_id": run_id}}):
            print(f"Checkpoint: {checkpoint}")
    finally:
        await runtime.stop()


if __name__ == "__main__":
    asyncio.run(debug_multi_tool())
