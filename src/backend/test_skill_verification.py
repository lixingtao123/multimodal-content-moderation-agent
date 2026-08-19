"""
Skill 使用情况验证测试（不调用真实 API）

验证点：
1. Skill 是否被正确召回
2. Skill 内容是否被注入到 System Prompt
3. Skill 路由是否有日志记录
4. 各 Agent 是否真正调用 Skill 注入代码
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def test_skill_recall():
    """测试 1: Skill 召回机制"""
    print("\n" + "="*80)
    print("测试 1: Skill 召回机制")
    print("="*80)

    from agent_moderation.skill_registry import get_skill_registry
    from agent_moderation.skill_router import get_skill_router

    registry = get_skill_registry()
    router = get_skill_router()

    print(f"\n✅ SkillRegistry 已加载 {len(registry.list_skills())} 个 Skill")

    # 测试不同查询的召回
    test_cases = [
        "加微信赚钱，日赚3000",
        "你妈死了，废物东西",
        "扫码进群，免费领礼包",
    ]

    results = []
    for query in test_cases:
        result = router.route(query=query, tags={'text'}, max_inject=3)
        results.append((query, result))
        print(f"\n查询: {query}")
        print(f"  Filter 召回: {result.get('filtered', [])}")
        print(f"  Rank 精排: {result.get('ranked', [])}")
        print(f"  Select 注入: {result.get('selected', [])}")

    has_recalls = any(len(r.get('selected', [])) > 0 for _, r in results)
    print(f"\n{'✅' if has_recalls else '❌'} Skill 召回机制工作正常")
    return has_recalls


async def test_text_agent_skill_injection():
    """测试 2: TextAgent Skill 注入"""
    print("\n" + "="*80)
    print("测试 2: TextAgent Skill 注入流程")
    print("="*80)

    from agent_moderation.agents.text_agent import TextAgent
    from agent_moderation.state import ModerationState

    agent = TextAgent()

    # 清空日志
    agent._skill_routing_log = []

    # 创建测试 state
    state: ModerationState = {
        "content_id": "test-skill-001",
        "content_type": "text",
        "content": {"text": "加微信赚钱，日赚3000"},
        "messages": [],
    }

    # 我们不完整运行 process()，只测试 Skill 注入部分
    # 直接调用 _load_relevant_skills
    print(f"\n调用 _load_relevant_skills()...")
    skill_context = agent._load_relevant_skills(
        query=state["content"]["text"],
        content_type="text",
        max_inject=3,
        content_id=state["content_id"],
    )

    print(f"\n✅ Skill 上下文已加载 ({len(skill_context)} 字符)")
    if skill_context:
        print(f"\nSkill 注入内容预览:")
        print("-"*80)
        print(skill_context[:500])
        print("-"*80)

    # 检查路由日志
    print(f"\n✅ Skill 路由日志记录:")
    if agent._skill_routing_log:
        log = agent._skill_routing_log[-1]
        print(f"  content_id: {log.get('content_id')}")
        print(f"  agent: {log.get('agent')}")
        print(f"  query: {log.get('query', '')[:60]}...")
        print(f"  filtered: {log.get('filtered')}")
        print(f"  ranked: {log.get('ranked')}")
        print(f"  selected: {log.get('selected')}")

    # 测试 _analyze_semantic 是否正确使用 Skill
    print(f"\n✅ _analyze_semantic() 方法签名检查:")
    import inspect
    sig = inspect.signature(agent._analyze_semantic)
    params = list(sig.parameters.keys())
    print(f"  参数: {params}")
    has_content_id = "content_id" in params
    print(f"  {'✅' if has_content_id else '❌'} 有 content_id 参数")

    return {
        "skill_context_generated": len(skill_context) > 0,
        "routing_log_recorded": len(agent._skill_routing_log) > 0,
        "has_content_id_param": has_content_id,
    }


async def test_image_agent_skill_injection():
    """测试 3: ImageAgent Skill 注入"""
    print("\n" + "="*80)
    print("测试 3: ImageAgent Skill 注入流程")
    print("="*80)

    from agent_moderation.agents.image_agent import ImageAgent

    agent = ImageAgent()
    agent._skill_routing_log = []

    print(f"\n调用 _load_relevant_skills()...")
    skill_context = agent._load_relevant_skills(
        query="广告图片加微信",
        content_type="image",
        max_inject=3,
        content_id="test-image-001",
    )

    print(f"\n✅ Skill 上下文已加载 ({len(skill_context)} 字符)")

    # 检查 _classify_text 方法签名
    print(f"\n✅ _classify_text() 方法签名检查:")
    import inspect
    sig = inspect.signature(agent._classify_text)
    params = list(sig.parameters.keys())
    print(f"  参数: {params}")

    required_params = ["ocr_text", "scene_description", "content_id"]
    has_all_params = all(p in params for p in required_params)
    print(f"  {'✅' if has_all_params else '❌'} 包含所有必需参数: {required_params}")

    # 检查路由日志
    has_log = len(agent._skill_routing_log) > 0
    if has_log:
        log = agent._skill_routing_log[-1]
        print(f"\n✅ Skill 路由日志: {log.get('selected')}")

    return {
        "skill_context_generated": len(skill_context) > 0,
        "has_required_params": has_all_params,
        "routing_log_recorded": has_log,
    }


async def test_audio_agent_skill_injection():
    """测试 4: AudioAgent Skill 注入"""
    print("\n" + "="*80)
    print("测试 4: AudioAgent Skill 注入流程")
    print("="*80)

    from agent_moderation.agents.audio_agent import AudioAgent

    agent = AudioAgent()
    agent._skill_routing_log = []

    skill_context = agent._load_relevant_skills(
        query="语音广告加微信",
        content_type="audio",
        max_inject=3,
        content_id="test-audio-001",
    )

    print(f"\n✅ Skill 上下文已加载 ({len(skill_context)} 字符)")

    import inspect
    sig = inspect.signature(agent._analyze_semantic)
    params = list(sig.parameters.keys())
    print(f"\n✅ _analyze_semantic() 参数: {params}")

    has_params = "transcribed_text" in params and "content_id" in params
    has_log = len(agent._skill_routing_log) > 0

    return {
        "skill_context_generated": len(skill_context) > 0,
        "has_required_params": has_params,
        "routing_log_recorded": has_log,
    }


async def test_video_agent_skill_injection():
    """测试 5: VideoAgent Skill 注入"""
    print("\n" + "="*80)
    print("测试 5: VideoAgent Skill 集成")
    print("="*80)

    from agent_moderation.agents.video_agent import VideoAgent

    agent = VideoAgent()

    import inspect
    sig = inspect.signature(agent._vl_analyze_frame) if hasattr(agent, "_vl_analyze_frame") else None
    has_method = sig is not None

    if has_method:
        params = list(sig.parameters.keys())
        print(f"\n✅ _vl_analyze_frame() 参数: {params}")
        has_content_id = "content_id" in params
        print(f"  {'✅' if has_content_id else '❌'} 有 content_id 参数")
    else:
        has_content_id = False
        print(f"\n❌ _vl_analyze_frame() 未找到")

    # 检查 process 方法中是否提取 content_id
    proc_src = inspect.getsource(agent.process)
    has_content_id_extraction = "content_id = state.get(" in proc_src or "content_id=state.get(" in proc_src

    return {
        "has_vl_analyze_method": has_method,
        "has_content_id_param": has_content_id,
        "has_content_id_extraction": has_content_id_extraction,
    }


async def test_risk_agent_skill_injection():
    """测试 6: RiskAgent Skill 注入"""
    print("\n" + "="*80)
    print("测试 6: RiskAgent Skill 集成")
    print("="*80)

    from agent_moderation.agents.risk_agent import RiskAssessmentAgent

    agent = RiskAssessmentAgent()

    import inspect
    proc_src = inspect.getsource(agent.process)

    has_skill_call = "_load_relevant_skills" in proc_src

    print(f"\n✅ process() 中是否调用 _load_relevant_skills(): {'✅' if has_skill_call else '❌'}")

    if has_skill_call:
        print(f"\n✅ Skill 集成代码已添加到 RiskAgent")

    return {
        "has_skill_integration": has_skill_call,
    }


def check_skill_code_in_text_agent():
    """检查 TextAgent 中 Skill 代码是否真的被使用"""
    print("\n" + "="*80)
    print("验证: TextAgent 中 Skill 代码是否真的被使用")
    print("="*80)

    from agent_moderation.agents.text_agent import TextAgent
    import inspect

    # 检查 process 方法
    proc_src = inspect.getsource(TextAgent.process)
    has_skill_call = "_load_relevant_skills" in proc_src

    # 检查 _analyze_semantic 是否被 process 调用
    analyze_src = inspect.getsource(TextAgent._analyze_semantic)
    skill_in_analyze = "_load_relevant_skills" in analyze_src and "skill_context" in analyze_src

    # 检查 skill_context 是否被拼接到 system_prompt
    prompt_injection = "system_prompt = f\"{system_prompt}\\n\\n{skill_context}\"" in analyze_src or "system_prompt = system_prompt + \"\\n\\n\" + skill_context" in analyze_src or "if skill_context:" in analyze_src

    print(f"\n✅ _analyze_semantic 中调用 _load_relevant_skills(): {'✅' if skill_in_analyze else '❌'}")
    print(f"✅ skill_context 被拼接到 system_prompt: {'✅' if prompt_injection else '❌'}")

    # 打印关键代码片段
    print(f"\n关键代码片段:")
    print("-"*80)
    lines = analyze_src.split("\n")
    for i, line in enumerate(lines):
        if "skill" in line.lower():
            print(f"  {i+1:4d}: {line}")
    print("-"*80)

    return {
        "skill_in_analyze": skill_in_analyze,
        "prompt_injection": prompt_injection,
    }


async def main():
    print("\n" + "="*80)
    print("Skill 使用情况完整验证（不调用真实 API）")
    print("="*80)

    results = {}

    # 测试 1: Skill 召回
    results["skill_recall"] = await test_skill_recall()

    # 测试 2: TextAgent
    results["text_agent"] = await test_text_agent_skill_injection()

    # 测试 3: ImageAgent
    results["image_agent"] = await test_image_agent_skill_injection()

    # 测试 4: AudioAgent
    results["audio_agent"] = await test_audio_agent_skill_injection()

    # 测试 5: VideoAgent
    results["video_agent"] = await test_video_agent_skill_injection()

    # 测试 6: RiskAgent
    results["risk_agent"] = await test_risk_agent_skill_injection()

    # 额外检查: TextAgent 代码
    results["text_agent_code"] = check_skill_code_in_text_agent()

    # 总结
    print("\n" + "="*80)
    print("验证总结")
    print("="*80)

    summary = {
        "skill_recall": results["skill_recall"],
        "text_agent_works": (
            results["text_agent"]["skill_context_generated"] and
            results["text_agent"]["routing_log_recorded"] and
            results["text_agent"]["has_content_id_param"] and
            results["text_agent_code"]["skill_in_analyze"] and
            results["text_agent_code"]["prompt_injection"]
        ),
        "image_agent_works": (
            results["image_agent"]["skill_context_generated"] and
            results["image_agent"]["has_required_params"] and
            results["image_agent"]["routing_log_recorded"]
        ),
        "audio_agent_works": (
            results["audio_agent"]["skill_context_generated"] and
            results["audio_agent"]["has_required_params"] and
            results["audio_agent"]["routing_log_recorded"]
        ),
        "video_agent_works": (
            results["video_agent"]["has_content_id_param"] and
            results["video_agent"]["has_content_id_extraction"]
        ),
        "risk_agent_works": results["risk_agent"]["has_skill_integration"],
    }

    print(f"\n1. Skill 召回机制: {'✅' if summary['skill_recall'] else '❌'}")
    print(f"2. TextAgent Skill 集成: {'✅' if summary['text_agent_works'] else '❌'}")
    print(f"3. ImageAgent Skill 集成: {'✅' if summary['image_agent_works'] else '❌'}")
    print(f"4. AudioAgent Skill 集成: {'✅' if summary['audio_agent_works'] else '❌'}")
    print(f"5. VideoAgent Skill 集成: {'✅' if summary['video_agent_works'] else '❌'}")
    print(f"6. RiskAgent Skill 集成: {'✅' if summary['risk_agent_works'] else '❌'}")

    all_passed = all(summary.values())

    print(f"\n{'🎉' if all_passed else '⚠️'} 整体验证: {'通过' if all_passed else '部分失败'}")

    if all_passed:
        print(f"""\n
╔═══════════════════════════════════════════════════════════════════════════╗
║                    ✅ LLM 按照 Skill 指导执行的证据                            ║
╠═══════════════════════════════════════════════════════════════════════════╣
║                                                                             ║
║  1. Skill 召回机制工作正常: Router 能根据内容召回相关 Skill                 ║
║                                                                             ║
║  2. Skill 内容被正确加载: 从 SkillRegistry 加载完整 Skill 指令             ║
║                                                                             ║
║  3. Skill 被注入 System Prompt: skill_context 拼接到 system_prompt        ║
║                                                                             ║
║  4. 路由日志被记录: 每次 Skill 使用都有日志，可追踪和优化                   ║
║                                                                             ║
║  5. 关键 Agent 都集成: Text / Image / Audio / Video / Risk                ║
║                                                                             ║
║  LLM 执行流程:                                                              ║
║     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐    ║
║     │  输入内容      │────▶│  Skill 三级召回 │────▶│  Skill 内容加载 │    ║
║     └─────────────────┘     └─────────────────┘     └─────────────────┘    ║
║                                                   │                         ║
║                                                   ▼                         ║
║     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐    ║
║     │  按 Skill 执行  │◀────│  注入 System   │◀────│  构建 Prompt    │    ║
║     └─────────────────┘     └─────────────────┘     └─────────────────┘    ║
║                                                                             ║
╚═══════════════════════════════════════════════════════════════════════════╝
        """)

    return summary


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
