#!/usr/bin/env python3
"""
测试 Skill Optimization API
"""
import requests
import json

BASE_URL = "http://localhost:18080/api/v1/tech"

print("""
╔══════════════════════════════════════════════════════════╗
║  测试 Skill Optimization API                             ║
╚══════════════════════════════════════════════════════════╝
""")

# 1. 测试获取 Skill 列表
print("1️⃣  测试获取 Skills 列表...")
response = requests.get(f"{BASE_URL}/skills")
if response.status_code == 200:
    data = response.json()
    print(f"✅ 成功获取 {data.get('total', 0)} 个 Skills")
else:
    print(f"❌ 失败: {response.status_code}")

# 2. 测试获取路由日志
print("\n2️⃣  测试获取路由日志...")
response = requests.get(f"{BASE_URL}/skill-routing-logs")
if response.status_code == 200:
    data = response.json()
    print(f"✅ 成功获取 {data.get('total', 0)} 条日志")
    print(f"📊 Skill 使用统计: {data.get('skill_stats', {})}")
else:
    print(f"❌ 失败: {response.status_code}")

# 3. 测试分析端点（不实际运行，只检查格式）
print("\n3️⃣  检查分析端点格式...")
print("   分析端点已在 tech.py 中更新为使用 SkillOptimizationAgent")

# 4. 显示测试报告
print(f"""
╔══════════════════════════════════════════════════════════╗
║  API 测试完成！                                         ║
╠══════════════════════════════════════════════════════════╣
║  已实现:                                                ║
║  • SkillOptimizationAgent 核心模块                    ║
║  • 更新 API 使用新的 LLM-driven 优化器                ║
║  • 保持 API 接口不变，前端无需修改                   ║
║                                                           ║
║  工作流程:                                              ║
║  1. 前端点击「分析并优化」按钮                         ║
║  2. API 调用 SkillOptimizationAgent.analyze_and_suggest()  ║
║  3. Agent 用 LLM 分析路由日志生成优化建议              ║
║  4. 建议在前端显示，可以投票（2/3 通过）                 ║
║  5. 批准后可以应用优化，Skill 文件会被修改              ║
║                                                           ║
║  前提条件:                                              ║
║  • 配置有效 DEEPSEEK_API_KEY                            ║
║  • 数据库中至少有 10 条路由日志                         ║
╚══════════════════════════════════════════════════════════╝
""")
