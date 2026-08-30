"""
手动测试多工具功能的简单脚本
用于验证：
1. 后端多工具顺序执行
2. /api/operations 返回多个 operation
3. 前端数据结构支持
"""

import httpx
import time
import json

BASE_URL = "http://127.0.0.1:8090"

def test_multi_tool():
    print("=== VenAgent 多工具手动测试 ===\n")
    
    # 1. 健康检查
    print("1. 检查后端健康状态...")
    try:
        response = httpx.get(f"{BASE_URL}/")
        print(f"   ✓ 后端运行正常 (HTTP {response.status_code})\n")
    except Exception as e:
        print(f"   ✗ 后端连接失败: {e}\n")
        return
    
    # 2. 获取 guest 身份
    print("2. 获取 guest 身份...")
    try:
        client = httpx.Client(base_url=BASE_URL, follow_redirects=True)
        response = client.post("/api/auth/guest")
        identity_data = response.json()
        print(f"   ✓ 身份获取成功: {identity_data.get('identity', {}).get('kind')}\n")
        # 使用 cookie 认证
    except Exception as e:
        print(f"   ✗ 获取身份失败: {e}\n")
        return
    
    # 3. 创建会话
    print("3. 创建测试会话...")
    try:
        response = client.post(
            "/api/conversations",
            json={"title": "Multi-tool test"}
        )
        conv_data = response.json()
        conv_id = conv_data["conversation"]["conversationId"]
        print(f"   ✓ 会话创建成功: {conv_id}\n")
    except Exception as e:
        print(f"   ✗ 创建会话失败: {e}\n")
        return
    
    # 4. 发送多工具请求（使用 /control 命令触发）
    print("4. 发送多工具请求...")
    print("   提示：发送 '/control' 命令可能触发多个工具调用\n")
    
    try:
        # 发送消息
        response = client.post(
            f"/api/conversations/{conv_id}/runs",
            json={
                "user_message": "列出当前目录的文件，然后显示日期",
                "skill_id": None
            },
            timeout=30.0
        )
        
        if response.status_code == 200:
            run_data = response.json()
            run_id = run_data["run"]["runId"]
            print(f"   ✓ 消息发送成功，run_id: {run_id}\n")
            
            # 5. 等待执行完成
            print("5. 等待执行完成...")
            time.sleep(3)
            
            # 6. 获取 operations
            print("6. 获取执行的工具调用...")
            ops_response = client.get(
                "/api/operations",
                params={"run_id": run_id}
            )
            
            if ops_response.status_code == 200:
                ops_data = ops_response.json()
                operations = ops_data.get("operations", [])
                
                print(f"   ✓ 获取到 {len(operations)} 个工具调用：\n")
                
                for i, op in enumerate(operations, 1):
                    print(f"   [{i}] {op['toolId']}")
                    print(f"       状态: {op['status']}")
                    print(f"       耗时: {op.get('timingMs', 'N/A')} ms")
                    if op.get('argumentsSummary'):
                        print(f"       参数: {op['argumentsSummary'][:50]}...")
                    if op.get('resultSummary'):
                        print(f"       结果: {op['resultSummary'][:50]}...")
                    print()
                
                # 验证
                if len(operations) >= 2:
                    print("   ✅ 多工具顺序执行成功！")
                    print("   ✅ 前端数据结构支持多工具（operations 是数组）")
                elif len(operations) == 1:
                    print("   ⚠️  只有 1 个工具调用，可能需要调整测试消息")
                else:
                    print("   ⚠️  没有工具调用")
            else:
                print(f"   ✗ 获取 operations 失败: HTTP {ops_response.status_code}")
        else:
            print(f"   ✗ 发送消息失败: HTTP {response.status_code}")
            print(f"   响应: {response.text}")
    
    except Exception as e:
        print(f"   ✗ 请求失败: {e}")
    
    print("\n=== 测试完成 ===")
    print("\n下一步：在浏览器中访问 http://127.0.0.1:8090")
    print("验证前端显示：thinking 块 → tool_call 消息 × N → 最终答案气泡")

if __name__ == "__main__":
    test_multi_tool()
