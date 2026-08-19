#!/usr/bin/env python3
"""
全面测试所有 Agent 的 Skill 集成

验证：
1. 每个 Agent 是否正确调用 _load_relevant_skills()
2. Skill 是否被正确注入到 System Prompt
3. 路由日志是否被正确记录
4. 每个 Agent 是否有正确的参数传递
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))


async def test_text_agent():
    """测试 TextAgent"""
    print("\n" + "="*80)
    print("📝 TextAgent 测试")
    print("="*80)

    from agent_moderation.agents.text_agent import TextAgent
    import inspect

    agent = TextAgent()
    # 清空类级别的日志
    TextAgent._skill_routing_log = []

    # 测试 1: 检查 _analyze_semantic 方法签名
    print("\n[1/4] 检查 _analyze_semantic 方法...")
    sig = inspect.signature(agent._analyze_semantic)
    params = list(sig.parameters.keys())
    has_content_id = "content_id" in params
    print(f"   参数: {params}")
    print(f"   ✅ has_content_id: {has_content_id}")

    # 测试 2: 检查 _segment_review 方法签名
    print("\n[2/4] 检查 _segment_review 方法...")
    sig = inspect.signature(agent._segment_review)
    params = list(sig.parameters.keys())
    has_content_id_seg = "content_id" in params
    print(f"   参数: {params}")
    print(f"   ✅ has_content_id: {has_content_id_seg}")

    # 测试 3: 调用 _load_relevant_skills
    print("\n[3/4] 调用 _load_relevant_skills...")
    skill_context = agent._load_relevant_skills(
        query="加微信赚钱，日赚3000",
        content_type='text',
        max_inject=3,
        content_id='test-text-001'
    )
    print(f"   ✅ Skill 上下文: {len(skill_context)} 字符")
    if skill_context:
        print(f"   示例: {skill_context[:150]}...")

    # 测试 4: 检查路由日志
    print("\n[4/4] 检查路由日志...")
    has_log = len(TextAgent._skill_routing_log) > 0
    if has_log:
        log = TextAgent._skill_routing_log[-1]
        print(f"   ✅ 日志已记录: {log.get('selected')}")

    # 检查代码中是否真的使用 Skill
    print("\n[代码检查] 验证 Skill 注入...")
    src = inspect.getsource(agent._analyze_semantic)
    has_load = "_load_relevant_skills" in src
    has_inject = "skill_context" in src and "system_prompt" in src
    print(f"   ✅ 调用 _load_relevant_skills: {has_load}")
    print(f"   ✅ 拼接到 system_prompt: {has_inject}")

    return {
        "name": "TextAgent",
        "has_content_id_param": has_content_id and has_content_id_seg,
        "skill_loaded": len(skill_context) > 0,
        "log_recorded": has_log,
        "code_integrated": has_load and has_inject,
    }


async def test_image_agent():
    """测试 ImageAgent"""
    print("\n" + "="*80)
    print("🖼️ ImageAgent 测试")
    print("="*80)

    from agent_moderation.agents.image_agent import ImageAgent
    import inspect

    agent = ImageAgent()
    # 清空类级别的日志
    ImageAgent._skill_routing_log = []

    # 测试 1: 检查 _classify_text 方法签名
    print("\n[1/4] 检查 _classify_text 方法...")
    sig = inspect.signature(agent._classify_text)
    params = list(sig.parameters.keys())
    has_required = all(p in params for p in ["ocr_text", "scene_description", "content_id"])
    print(f"   参数: {params}")
    print(f"   ✅ 有必需参数: {has_required}")

    # 测试 2: 调用 _load_relevant_skills
    print("\n[2/4] 调用 _load_relevant_skills...")
    skill_context = agent._load_relevant_skills(
        query="广告图片加微信",
        content_type='image',
        max_inject=3,
        content_id='test-image-001'
    )
    print(f"   ✅ Skill 上下文: {len(skill_context)} 字符")

    # 测试 3: 检查路由日志
    print("\n[3/4] 检查路由日志...")
    has_log = len(ImageAgent._skill_routing_log) > 0
    if has_log:
        log = ImageAgent._skill_routing_log[-1]
        print(f"   ✅ 日志已记录: {log.get('selected')}")

    # 检查代码
    print("\n[4/4] 代码检查...")
    src = inspect.getsource(agent._classify_text)
    has_load = "_load_relevant_skills" in src
    has_inject = "skill_context" in src
    print(f"   ✅ 调用 _load_relevant_skills: {has_load}")
    print(f"   ✅ 使用 skill_context: {has_inject}")

    return {
        "name": "ImageAgent",
        "has_required_params": has_required,
        "skill_loaded": len(skill_context) > 0,
        "log_recorded": has_log,
        "code_integrated": has_load and has_inject,
    }


async def test_audio_agent():
    """测试 AudioAgent"""
    print("\n" + "="*80)
    print("🎤 AudioAgent 测试")
    print("="*80)

    from agent_moderation.agents.audio_agent import AudioAgent
    import inspect

    agent = AudioAgent()
    # 清空类级别的日志
    AudioAgent._skill_routing_log = []

    # 测试 1: 检查 _analyze_semantic 方法签名
    print("\n[1/4] 检查 _analyze_semantic 方法...")
    sig = inspect.signature(agent._analyze_semantic)
    params = list(sig.parameters.keys())
    has_required = all(p in params for p in ["transcribed_text", "content_id"])
    print(f"   参数: {params}")
    print(f"   ✅ 有必需参数: {has_required}")

    # 测试 2: 调用 _load_relevant_skills
    print("\n[2/4] 调用 _load_relevant_skills...")
    skill_context = agent._load_relevant_skills(
        query="语音广告加微信",
        content_type='audio',
        max_inject=3,
        content_id='test-audio-001'
    )
    print(f"   ✅ Skill 上下文: {len(skill_context)} 字符")

    # 测试 3: 检查路由日志
    print("\n[3/4] 检查路由日志...")
    has_log = len(AudioAgent._skill_routing_log) > 0
    if has_log:
        log = AudioAgent._skill_routing_log[-1]
        print(f"   ✅ 日志已记录: {log.get('selected')}")

    # 检查代码
    print("\n[4/4] 代码检查...")
    src = inspect.getsource(agent._analyze_semantic)
    has_load = "_load_relevant_skills" in src
    has_inject = "skill_context" in src
    print(f"   ✅ 调用 _load_relevant_skills: {has_load}")
    print(f"   ✅ 使用 skill_context: {has_inject}")

    return {
        "name": "AudioAgent",
        "has_required_params": has_required,
        "skill_loaded": len(skill_context) > 0,
        "log_recorded": has_log,
        "code_integrated": has_load and has_inject,
    }


async def test_video_agent():
    """测试 VideoAgent"""
    print("\n" + "="*80)
    print("🎬 VideoAgent 测试")
    print("="*80)

    from agent_moderation.agents.video_agent import VideoAgent
    import inspect

    agent = VideoAgent()
    # 清空类级别的日志
    VideoAgent._skill_routing_log = []

    # 测试 1: 检查 _vl_analyze_frame 方法签名
    print("\n[1/4] 检查 _vl_analyze_frame 方法...")
    sig = inspect.signature(agent._vl_analyze_frame)
    params = list(sig.parameters.keys())
    has_content_id = "content_id" in params
    print(f"   参数: {params}")
    print(f"   ✅ has_content_id: {has_content_id}")

    # 测试 2: 检查 process 方法中是否提取 content_id
    print("\n[2/4] 检查 process 方法...")
    src = inspect.getsource(agent.process)
    has_content_id_extract = "content_id" in src and "state.get" in src
    print(f"   ✅ 提取 content_id: {has_content_id_extract}")

    # 测试 3: 检查 _vl_analyze_frame 中的 Skill 集成
    print("\n[3/4] 检查 Skill 集成...")
    vl_src = inspect.getsource(agent._vl_analyze_frame)
    has_load = "_load_relevant_skills" in vl_src
    has_inject = "skill_context" in vl_src and "full_prompt" in vl_src
    print(f"   ✅ 调用 _load_relevant_skills: {has_load}")
    print(f"   ✅ 拼接到 full_prompt: {has_inject}")

    # 测试 4: 模拟调用
    print("\n[4/4] 模拟 Skill 加载...")
    skill_context = agent._load_relevant_skills(
        query="",
        content_type='video',
        max_inject=3,
        content_id='test-video-001'
    )
    print(f"   ✅ Skill 上下文: {len(skill_context)} 字符")
    has_log = len(VideoAgent._skill_routing_log) > 0
    print(f"   ✅ 日志已记录: {has_log}")

    return {
        "name": "VideoAgent",
        "has_content_id_param": has_content_id,
        "has_content_id_extract": has_content_id_extract,
        "code_integrated": has_load and has_inject,
        "skill_loaded": len(skill_context) > 0,
        "log_recorded": has_log,
    }


async def test_risk_agent():
    """测试 RiskAgent"""
    print("\n" + "="*80)
    print("⚖️ RiskAgent 测试")
    print("="*80)

    from agent_moderation.agents.risk_agent import RiskAssessmentAgent
    import inspect

    agent = RiskAssessmentAgent()
    # 清空类级别的日志
    RiskAssessmentAgent._skill_routing_log = []

    # 测试 1: 检查 process 方法中的 Skill 集成
    print("\n[1/3] 检查 process 方法...")
    src = inspect.getsource(agent.process)
    has_load = "_load_relevant_skills" in src
    print(f"   ✅ 调用 _load_relevant_skills: {has_load}")

    # 测试 2: 检查参数
    print("\n[2/3] 检查参数传递...")
    has_content_id = "content_id" in src and "state.get" in src
    has_query = "text_content" in src or "query" in src
    print(f"   ✅ 传递 content_id: {has_content_id}")
    print(f"   ✅ 传递查询内容: {has_query}")

    # 测试 3: 模拟调用
    print("\n[3/3] 模拟 Skill 加载...")
    skill_context = agent._load_relevant_skills(
        query="加微信赚钱",
        content_type='text',
        max_inject=3,
        content_id='test-risk-001'
    )
    print(f"   ✅ Skill 上下文: {len(skill_context)} 字符")
    has_log = len(RiskAssessmentAgent._skill_routing_log) > 0
    print(f"   ✅ 日志已记录: {has_log}")

    return {
        "name": "RiskAgent",
        "code_integrated": has_load,
        "has_params": has_content_id,
        "skill_loaded": len(skill_context) > 0,
        "log_recorded": has_log,
    }


def print_summary(results):
    """打印测试总结"""
    print("\n" + "="*80)
    print("📊 所有 Agent 测试总结")
    print("="*80)

    all_passed = True
    for r in results:
        name = r.get("name", "Unknown")
        # 检查除了 name 之外的所有字段是否都是 True
        checks = [v for k, v in r.items() if k != "name"]
        passed = all(checks)
        all_passed = all_passed and passed
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"\n{name}: {status}")
        for k, v in r.items():
            if k != "name":
                icon = "✅" if v else "❌"
                print(f"   {icon} {k}: {v}")

    print("\n" + "="*80)
    if all_passed:
        print("🎉 所有 Agent 测试通过!")
        print("""
╔═══════════════════════════════════════════════════════════════╗
║                    ✅ 验证结论                                  ║
╠═══════════════════════════════════════════════════════════════╣
║                                                               ║
║  所有 Agent 都已正确集成 Skill:                               ║
║                                                               ║
║  1. ✅ TextAgent - 文本审核 Skill                             ║
║  2. ✅ ImageAgent - 图像审核 Skill                            ║
║  3. ✅ AudioAgent - 音频审核 Skill                            ║
║  4. ✅ VideoAgent - 视频审核 Skill                            ║
║  5. ✅ RiskAgent - 风险评估 Skill                            ║
║                                                               ║
║  Skill 工作流程:                                             ║
║     内容输入 → SkillRouter 召回 → SkillRegistry 加载        ║
║     → 注入 System Prompt → LLM 按 Skill 执行                ║
║                                                               ║
║  验证方式:                                                  ║
║     - 路由日志记录每次使用                                   ║
║     - 代码检查确认集成                                       ║
║     - 参数验证确认传递正确                                   ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
        """)
    else:
        print("⚠️ 部分 Agent 测试失败，请检查上面的详情。")

    return all_passed


async def main():
    """主函数"""
    print("="*80)
    print("🚀 全面测试所有 Agent 的 Skill 集成")
    print("="*80)

    results = []

    # 测试所有 Agent
    results.append(await test_text_agent())
    results.append(await test_image_agent())
    results.append(await test_audio_agent())
    results.append(await test_video_agent())
    results.append(await test_risk_agent())

    # 打印总结
    all_passed = print_summary(results)

    return all_passed


if __name__ == "__main__":
    import asyncio
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
