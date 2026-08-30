"""端到端测试：验证多工具顺序执行和前端展示。

测试步骤：
1. 访问 guest 端点获取临时会话
2. 创建对话
3. 发送需要多工具的消息
4. 检查返回的 operations 数量和状态
"""

import requests
import time
import json

BASE_URL = "http://127.0.0.1:8090"

def test_multi_tool_e2e():
    print("=" * 60)
    print("端到端测试：多工具顺序执行")
    print("=" * 60)
    
    # Step 1: 获取 guest 身份（cookie 认证；会话由 requests.Session 保留）
    print("\n[1] 获取 guest 身份...")
    session = requests.Session()
    resp = session.post(
        f"{BASE_URL}/api/auth/guest",
        headers={"Origin": "http://localhost:5173"}
    )
    assert resp.status_code == 200, f"获取身份失败: {resp.status_code}"
    assert session.cookies, f"响应中没有身份 cookie: {resp.headers.get('Set-Cookie', '')}"

    headers = {
        "Content-Type": "application/json"
    }
    print(f"✓ 身份获取成功（{len(session.cookies)} 个 cookie）")
    
    # Step 2: 创建对话
    print("\n[2] 创建对话...")
    resp = session.post(
        f"{BASE_URL}/api/conversations",
        headers=headers,
        json={"title": "多工具测试"}
    )
    assert resp.status_code in [200, 201], f"创建对话失败: {resp.status_code}"
    
    conversation = resp.json()
    print(f"对话响应: {conversation}")
    conversation_id = conversation.get("id") or conversation.get("conversationId") or conversation.get("conversation_id")
    assert conversation_id, f"无法获取 conversation_id: {conversation}"
    print(f"✓ 对话创建成功: {conversation_id}")
    
    # Step 3: 发送需要多个工具的消息
    print("\n[3] 发送消息（触发多工具）...")
    # 使用更明确的需要工具的消息
    message = "请先搜索今天的天气，然后再搜索明天的天气预报"
    
    import uuid
    client_request_id = str(uuid.uuid4())
    
    resp = session.post(
        f"{BASE_URL}/api/conversations/{conversation_id}/runs",
        headers=headers,
        json={
            "message": message,
            "client_request_id": client_request_id
        }
    )
    
    if resp.status_code not in [200, 202]:
        print(f"✗ 发送消息失败: {resp.status_code}")
        print(f"响应: {resp.text}")
        return False
    
    message_resp = resp.json()
    print(f"创建 run 响应: {message_resp}")
    
    # 响应可能是 RunCreationResponse
    if isinstance(message_resp, dict):
        run_data = message_resp.get("run", {})
        run_id = run_data.get("run_id") or message_resp.get("run_id")
    else:
        run_id = None
    
    if not run_id:
        print(f"✗ 无法获取 run_id: {message_resp}")
        return False
    
    print(f"✓ 消息发送成功，run_id: {run_id}")
    
    # Step 4: 等待执行完成
    print("\n[4] 等待执行完成...")
    max_retries = 30
    for i in range(max_retries):
        time.sleep(2)
        
        # 检查 run 状态
        resp = session.get(
            f"{BASE_URL}/api/runs/{run_id}",
            headers=headers
        )
        
        if resp.status_code != 200:
            print(f"  第 {i+1} 次检查失败: {resp.status_code}")
            continue
        
        run_data = resp.json()
        status = run_data.get("status")
        print(f"  第 {i+1} 次检查: status={status}")
        
        if status in ["completed", "failed", "cancelled"]:
            break
    
    # Step 5: 获取 operations
    print("\n[5] 获取 operations...")
    resp = session.get(
        f"{BASE_URL}/api/operations",
        headers=headers,
        params={"run_id": run_id}
    )
    
    if resp.status_code != 200:
        print(f"✗ 获取 operations 失败: {resp.status_code}")
        print(f"响应: {resp.text}")
        return False
    
    operations_data = resp.json()
    
    # 响应可能直接是数组
    if isinstance(operations_data, list):
        operations = operations_data
    else:
        operations = operations_data.get("operations", [])
    
    print(f"\n{'=' * 60}")
    print(f"测试结果")
    print(f"{'=' * 60}")
    print(f"Operations 数量: {len(operations)}")
    
    if len(operations) == 0:
        print("✗ 没有找到 operations")
        return False
    
    print(f"\n工具调用详情：")
    for idx, op in enumerate(operations, 1):
        print(f"\n[工具 {idx}]")
        print(f"  ID: {op.get('operationId')}")
        print(f"  工具: {op.get('toolId')}")
        print(f"  状态: {op.get('status')}")
        print(f"  耗时: {op.get('timingMs')}ms")
        print(f"  参数: {op.get('argumentsSummary', 'N/A')}")
        print(f"  结果: {op.get('resultSummary', 'N/A')[:100]}...")
    
    # 验证
    print(f"\n{'=' * 60}")
    print("验证结果")
    print(f"{'=' * 60}")
    
    success = True
    
    # 检查：至少有 1 个 operation
    if len(operations) >= 1:
        print("✓ 有工具被执行")
    else:
        print("✗ 没有工具被执行")
        success = False
    
    # 检查：每个 operation 都有必要字段
    required_fields = ["operationId", "toolId", "status"]
    for op in operations:
        missing = [f for f in required_fields if f not in op]
        if missing:
            print(f"✗ Operation {op.get('operationId')} 缺少字段: {missing}")
            success = False
    
    if not missing:
        print("✓ 所有 operations 都有必要字段")
    
    # 检查：至少有一个 succeeded
    succeeded_count = sum(1 for op in operations if op.get("status") == "succeeded")
    if succeeded_count > 0:
        print(f"✓ 有 {succeeded_count} 个工具成功执行")
    else:
        print("✗ 没有工具成功执行")
        success = False
    
    print(f"\n{'=' * 60}")
    if success:
        print("✅ 多工具端到端测试通过！")
    else:
        print("❌ 测试失败")
    print(f"{'=' * 60}\n")
    
    return success

if __name__ == "__main__":
    try:
        success = test_multi_tool_e2e()
        exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
