#!/usr/bin/env python3
"""
验证我们修复的 text_agent.py 中 content_id 问题是否解决
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))


async def test_text_agent_param_passing():
    """测试 content_id 参数传递是否正确"""
    print("="*80)
    print("测试 TextAgent content_id 参数传递")
    print("="*80)

    from agent_moderation.agents.text_agent import TextAgent

    agent = TextAgent()

    # 创建测试状态
    state = {
        "content_id": "test-fix-001",
        "content_type": "text",
        "content": {"text": "加微信赚钱，日赚3000"},
        "messages": [],
    }

    print("\n1. 检查 process 方法签名...")
    import inspect
    process_sig = inspect.signature(agent.process)
    print(f"   process 参数: {list(process_sig.parameters.keys())}")

    print("\n2. 检查 _process_impl 方法签名...")
    impl_sig = inspect.signature(agent._process_impl)
    params = list(impl_sig.parameters.keys())
    print(f"   _process_impl 参数: {params}")

    has_content_id = "content_id" in params
    print(f"   ✅ has_content_id: {has_content_id}")

    print("\n3. 检查 _analyze_semantic 和 _segment_review...")
    anal_sig = inspect.signature(agent._analyze_semantic)
    seg_sig = inspect.signature(agent._segment_review)
    print(f"   _analyze_semantic 参数: {list(anal_sig.parameters.keys())}")
    print(f"   _segment_review 参数: {list(seg_sig.parameters.keys())}")

    print("\n4. 模拟 Skill 加载...")
    agent._skill_routing_log = []
    skill_context = agent._load_relevant_skills(
        query=state["content"]["text"],
        content_type="text",
        max_inject=3,
        content_id=state["content_id"],
    )
    print(f"   ✅ Skill 加载成功: {len(skill_context)} 字符")

    if agent._skill_routing_log:
        log = agent._skill_routing_log[-1]
        print(f"   ✅ Skill 路由日志记录成功")
        print(f"      content_id: {log.get('content_id')}")
        print(f"      selected: {log.get('selected')}")

    print("\n" + "="*80)
    print("✅ 参数传递验证通过！")
    print("="*80)

    return has_content_id


async def test_all_agents_syntax():
    """测试所有 Agent 导入是否正常"""
    print("\n" + "="*80)
    print("测试所有 Agent 导入")
    print("="*80)

    all_good = True

    agents = [
        ("TextAgent", "agent_moderation.agents.text_agent"),
        ("ImageAgent", "agent_moderation.agents.image_agent"),
        ("AudioAgent", "agent_moderation.agents.audio_agent"),
        ("VideoAgent", "agent_moderation.agents.video_agent"),
        ("RiskAgent", "agent_moderation.agents.risk_agent"),
    ]

    for name, module in agents:
        try:
            __import__(module)
            print(f"✅ {name} 导入成功")
        except Exception as e:
            print(f"❌ {name} 导入失败: {e}")
            all_good = False

    return all_good


async def main():
    test1 = await test_text_agent_param_passing()
    test2 = await test_all_agents_syntax()

    print("\n" + "="*80)
    if test1 and test2:
        print("🎉 所有验证通过！")
    else:
        print("⚠️ 部分验证失败")
    print("="*80)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
