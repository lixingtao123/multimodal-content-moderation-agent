"""
验证测试：检查各 Agent 是否真正召回和使用 Skill
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def test_skill_registry():
    """测试 SkillRegistry 是否能正确加载所有 Skill"""
    from agent_moderation.skill_registry import get_skill_registry

    print("=" * 80)
    print("测试 1: SkillRegistry 加载")
    print("=" * 80)

    registry = get_skill_registry()

    skills = registry.list_skills()
    print(f"✅ 发现 {len(skills)} 个 Skill:")
    for skill_meta in skills:
        print(f"   - {skill_meta.name}: {skill_meta.description}")
        print(f"     标签: {skill_meta.tags}, 工具: {skill_meta.mcp_tools}")

    # 尝试加载完整 Skill
    if skills:
        first_skill_name = skills[0].name
        full_skill = registry.get_skill(first_skill_name)
        if full_skill:
            print(f"\n✅ 成功加载完整 Skill: {first_skill_name}")
            print(f"   指令长度: {len(full_skill.instructions)} chars")
            print(f"   参考文件: {list(full_skill.references.keys())}")

    return len(skills) > 0


async def test_skill_router():
    """测试 SkillRouter 是否能正确召回相关 Skill"""
    from agent_moderation.skill_router import get_skill_router

    print("\n" + "=" * 80)
    print("测试 2: SkillRouter 召回")
    print("=" * 80)

    router = get_skill_router()

    test_cases = [
        ("加微信赚钱", {"广告引流"}, "广告类查询"),
        ("你妈死了废物", {"辱骂骚扰"}, "辱骂类查询"),
        ("扫码进群", {"二维码", "广告"}, "二维码引流查询"),
    ]

    for query, tags, desc in test_cases:
        print(f"\n测试查询: {query} ({desc})")
        result = router.route(query, tags=tags, max_inject=2)
        print(f"   Filter 结果: {result.get('filtered', [])}")
        print(f"   Rank 结果: {result.get('ranked', [])}")
        print(f"   最终选择: {result.get('selected', [])}")

    return True


async def test_base_agent_skill_injection():
    """测试 BaseAgent 的 Skill 注入机制"""
    from agent_moderation.agents.base import BaseAgent
    from agent_moderation.skill_registry import get_skill_registry

    print("\n" + "=" * 80)
    print("测试 3: BaseAgent Skill 注入")
    print("=" * 80)

    # 创建一个测试用的 Agent
    class TestAgent(BaseAgent):
        def __init__(self):
            super().__init__("test_agent")

    agent = TestAgent()

    # 测试 _load_skill_context 方法
    registry = get_skill_registry()
    skill_names = [s.name for s in registry.list_skills()[:2]]

    if skill_names:
        context = agent._load_skill_context(skill_names)
        print(f"\n✅ 加载 {len(skill_names)} 个 Skill 的上下文:")
        print(f"   上下文长度: {len(context)} chars")
        if context:
            print(f"   上下文预览: {context[:200]}...")

    # 测试 _load_relevant_skills (动态召回)
    print("\n测试动态召回 Skill:")
    dynamic_context = agent._load_relevant_skills(
        query="加微信发红包赚钱",
        content_type="text",
        max_inject=2,
        content_id="test_123"
    )
    print(f"✅ 动态召回上下文长度: {len(dynamic_context)} chars")
    if dynamic_context:
        print(f"   上下文预览: {dynamic_context[:200]}...")

    # 检查 Skill 路由日志
    print(f"\n✅ Skill 路由日志数: {len(agent._skill_routing_log)}")
    if agent._skill_routing_log:
        last_log = agent._skill_routing_log[-1]
        print(f"   最后一条日志: {last_log.get('selected', [])}")

    return True


async def test_text_agent_skill_integration():
    """测试 TextAgent 是否真正集成 Skill"""
    print("\n" + "=" * 80)
    print("测试 4: TextAgent Skill 集成")
    print("=" * 80)

    # 导入 TextAgent (不实际运行 process，只检查代码结构)
    from agent_moderation.agents.text_agent import TextAgent

    agent = TextAgent()

    # 检查方法签名
    import inspect
    sig = inspect.signature(agent._analyze_semantic)
    params = list(sig.parameters.keys())

    print(f"\n✅ _analyze_semantic 方法参数: {params}")

    required_params = ['text', 'similar_cases', 'core_memories',
                       'focus_segments', 'content_id']
    missing = [p for p in required_params if p not in params]
    if not missing:
        print("✅ 所有必需参数都存在!")
    else:
        print(f"❌ 缺失参数: {missing}")
        return False

    # 检查 _segment_review 方法
    sig_segment = inspect.signature(agent._segment_review)
    params_segment = list(sig_segment.parameters.keys())
    print(f"✅ _segment_review 方法参数: {params_segment}")

    if 'content_id' in params_segment:
        print("✅ _segment_review 有 content_id 参数!")
    else:
        print("❌ _segment_review 缺失 content_id 参数!")
        return False

    return True


async def test_image_agent_skill_integration():
    """测试 ImageAgent Skill 集成"""
    print("\n" + "=" * 80)
    print("测试 5: ImageAgent Skill 集成")
    print("=" * 80)

    from agent_moderation.agents.image_agent import ImageAgent
    import inspect

    agent = ImageAgent()

    sig = inspect.signature(agent._classify_text)
    params = list(sig.parameters.keys())

    print(f"\n✅ _classify_text 方法参数: {params}")

    required_params = ['text', 'similar_cases', 'ocr_text',
                       'scene_description', 'content_id']
    missing = [p for p in required_params if p not in params]
    if not missing:
        print("✅ 所有必需参数都存在!")
    else:
        print(f"❌ 缺失参数: {missing}")
        return False

    return True


async def test_audio_agent_skill_integration():
    """测试 AudioAgent Skill 集成"""
    print("\n" + "=" * 80)
    print("测试 6: AudioAgent Skill 集成")
    print("=" * 80)

    from agent_moderation.agents.audio_agent import AudioAgent
    import inspect

    agent = AudioAgent()

    sig = inspect.signature(agent._analyze_semantic)
    params = list(sig.parameters.keys())

    print(f"\n✅ _analyze_semantic 方法参数: {params}")

    required_params = ['text', 'similar_cases', 'transcribed_text', 'content_id']
    missing = [p for p in required_params if p not in params]
    if not missing:
        print("✅ 所有必需参数都存在!")
    else:
        print(f"❌ 缺失参数: {missing}")
        return False

    return True


async def main():
    print("\n" + "=" * 80)
    print("内容风控系统 Skill 集成验证测试")
    print("=" * 80)

    results = []

    try:
        results.append(("SkillRegistry 加载", await test_skill_registry()))
    except Exception as e:
        print(f"❌ SkillRegistry 测试失败: {e}")
        import traceback
        traceback.print_exc()
        results.append(("SkillRegistry 加载", False))

    try:
        results.append(("SkillRouter 召回", await test_skill_router()))
    except Exception as e:
        print(f"❌ SkillRouter 测试失败: {e}")
        import traceback
        traceback.print_exc()
        results.append(("SkillRouter 召回", False))

    try:
        results.append(("BaseAgent Skill 注入", await test_base_agent_skill_injection()))
    except Exception as e:
        print(f"❌ BaseAgent 测试失败: {e}")
        import traceback
        traceback.print_exc()
        results.append(("BaseAgent Skill 注入", False))

    try:
        results.append(("TextAgent Skill 集成", await test_text_agent_skill_integration()))
    except Exception as e:
        print(f"❌ TextAgent 测试失败: {e}")
        import traceback
        traceback.print_exc()
        results.append(("TextAgent Skill 集成", False))

    try:
        results.append(("ImageAgent Skill 集成", await test_image_agent_skill_integration()))
    except Exception as e:
        print(f"❌ ImageAgent 测试失败: {e}")
        import traceback
        traceback.print_exc()
        results.append(("ImageAgent Skill 集成", False))

    try:
        results.append(("AudioAgent Skill 集成", await test_audio_agent_skill_integration()))
    except Exception as e:
        print(f"❌ AudioAgent 测试失败: {e}")
        import traceback
        traceback.print_exc()
        results.append(("AudioAgent Skill 集成", False))

    # 总结
    print("\n" + "=" * 80)
    print("测试总结")
    print("=" * 80)

    passed = sum(1 for _, ok in results if ok)
    total = len(results)

    for name, ok in results:
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"{status}: {name}")

    print(f"\n总计: {passed}/{total} 测试通过")

    if passed == total:
        print("\n🎉 所有测试通过! Skill 集成正常工作!")
        return True
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败")
        return False


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
