"""
直接测试SkillOptimizationAgent功能（无需完整数据库初始化）
"""
import sys
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent))


async def test_heuristic_suggestions():
    """测试启发式建议生成功能"""
    print("\n" + "="*80)
    print("TEST HEURISTIC SUGGESTIONS")
    print("="*80)

    from optimization.skill_optimization_agent import SkillOptimizationAgent

    agent = SkillOptimizationAgent()

    # 模拟路由日志
    test_logs = []
    log_path = Path("/workspace/skill_demo_data/skill_routing_logs.jsonl")
    if not log_path.exists():
        log_path = Path(__file__).parent.parent.parent / "skill_demo_data" / "skill_routing_logs.jsonl"

    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                test_logs.append(json.loads(line))

    print(f"Loaded {len(test_logs)} test logs")

    # 生成日志摘要
    logs_summary = agent._summarize_logs(test_logs)
    print(f"Generated logs summary")
    print(f"Total logs: {logs_summary['total_logs']}")
    print(f"Skill stats: {logs_summary['skill_stats']}")

    # 生成启发式建议
    suggestions = agent._generate_heuristic_suggestions(test_logs, logs_summary)
    print(f"\nGenerated {len(suggestions)} heuristic suggestions")

    print("\nSUGGESTIONS:")
    for i, sug in enumerate(suggestions, 1):
        print(f"\n{i}. {sug.skill_name} - {sug.suggestion_type}")
        print(f"   Confidence: {sug.confidence}")
        print(f"   Reason: {sug.reason}")
        if sug.analysis_detail:
            print(f"   Analysis: {sug.analysis_detail[:100]}...")

    return len(suggestions)


async def test_llm_suggestion_generation():
    """测试LLM建议生成（带Mock）"""
    print("\n" + "="*80)
    print("TEST LLM SUGGESTION GENERATION")
    print("="*80)

    from optimization.skill_optimization_agent import SkillOptimizationAgent

    agent = SkillOptimizationAgent()

    # 模拟日志
    test_logs = []
    log_path = Path("/workspace/skill_demo_data/skill_routing_logs.jsonl")
    if not log_path.exists():
        log_path = Path(__file__).parent.parent.parent / "skill_demo_data" / "skill_routing_logs.jsonl"

    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                test_logs.append(json.loads(line))

    test_logs = test_logs[:20]  # 少取一点
    logs_summary = agent._summarize_logs(test_logs)

    # Mock LLM调用
    mock_response = {
        "analysis_summary": "分析了20条日志，发现了几个优化机会",
        "suggestions": [
            {
                "skill_name": "spam_detect",
                "suggestion_type": "trigger_add",
                "current_value": "",
                "suggested_value": "加微信",
                "reason": "在多条日志中包含'加微信'关键词的内容都被识别为垃圾信息",
                "confidence": 0.9,
                "supporting_examples": ["加微信 abc123", "联系微信 xyz999"],
                "analysis_detail": "分析发现，有8条包含'加微信'关键词的日志都被标记为垃圾信息，但当前spam_detect技能的触发词中没有'加微信'，这可能导致该技能没有被正确激活",
                "impact": "高 - 提高垃圾信息的识别率"
            },
            {
                "skill_name": "pii_scan",
                "suggestion_type": "description_update",
                "current_value": "扫描个人信息泄露",
                "suggested_value": "扫描个人信息包括手机号、身份证号、银行卡号、微信号等隐私信息",
                "reason": "当前描述不够准确，导致语义匹配时经常排在后面",
                "confidence": 0.8,
                "supporting_examples": ["手机号是 13800138000", "身份证号是 110101199001011234"],
                "analysis_detail": "从路由日志分析来看，pii_scan在筛选阶段被选中的频率较低，可能是因为描述不够具体，语义匹配得分低",
                "impact": "中 - 提高该技能的召回率"
            },
            {
                "skill_name": "blackmarket_detect",
                "suggestion_type": "skill_split",
                "current_value": "覆盖了黑产交易、暴力威胁、辱骂等多个场景",
                "suggested_value": "拆分为blackmarket_trade和violence_threat两个技能",
                "reason": "当前技能覆盖太多不同类型的场景，拆分后可以更精准",
                "confidence": 0.75,
                "supporting_examples": ["我要杀了你", "中奖了500万", "代理加盟"],
                "analysis_detail": "分析发现，blackmarket_detect同时处理了暴力威胁、诈骗、黑产交易等多种完全不同类型的场景，导致每个场景的描述不够聚焦",
                "impact": "中 - 提高识别精度",
                "suggested_skill_names": ["blackmarket_trade", "violence_threat"]
            }
        ]
    }

    agent._call_llm = AsyncMock(return_value=mock_response)

    # 测试LLM建议生成
    suggestions = await agent._generate_suggestions_with_llm(test_logs)
    print(f"\nGenerated {len(suggestions)} LLM suggestions")

    for i, sug in enumerate(suggestions, 1):
        print(f"\n{i}. {sug.skill_name} - {sug.suggestion_type}")
        print(f"   Confidence: {sug.confidence}")
        print(f"   Reason: {sug.reason}")
        if sug.analysis_detail:
            print(f"   Analysis: {sug.analysis_detail}")
        if sug.impact:
            print(f"   Impact: {sug.impact}")
        if hasattr(sug, "suggested_skill_names") and sug.suggested_skill_names:
            print(f"   Suggested skills: {sug.suggested_skill_names}")

    return len(suggestions)


async def test_suggestion_validation():
    """测试建议验证功能"""
    print("\n" + "="*80)
    print("TEST SUGGESTION VALIDATION")
    print("="*80)

    from optimization.skill_optimization_agent import SkillOptimizationAgent, SkillOptimizationSuggestion

    agent = SkillOptimizationAgent()

    # 获取真实技能列表
    skills = agent.registry.list_skills()
    skills_list = [
        {"name": s.name, "description": s.description, "triggers": s.triggers, "tags": s.tags, "version": s.version}
        for s in skills
    ]
    print(f"Loaded {len(skills_list)} skills from registry")

    test_cases = [
        {
            "name": "Good suggestion (trigger add)",
            "suggestion": SkillOptimizationSuggestion(
                skill_name=skills[0].name if skills else "spam_detect",
                suggestion_type="trigger_add",
                suggested_value="test_trigger",
                reason="这是一个足够长的理由来满足验证条件，超过20个字符",
                confidence=0.85,
                supporting_examples=["example 1"]
            ),
            "should_pass": True
        },
        {
            "name": "Low confidence",
            "suggestion": SkillOptimizationSuggestion(
                skill_name=skills[0].name if skills else "spam_detect",
                suggestion_type="trigger_add",
                suggested_value="test_trigger",
                reason="足够长的理由",
                confidence=0.65,
                supporting_examples=["example 1"]
            ),
            "should_pass": False
        },
        {
            "name": "Reason too short",
            "suggestion": SkillOptimizationSuggestion(
                skill_name=skills[0].name if skills else "spam_detect",
                suggestion_type="trigger_add",
                suggested_value="test_trigger",
                reason="太短",
                confidence=0.85,
                supporting_examples=["example 1"]
            ),
            "should_pass": False
        },
        {
            "name": "Skill not found",
            "suggestion": SkillOptimizationSuggestion(
                skill_name="nonexistent_skill_123456",
                suggestion_type="trigger_add",
                suggested_value="test_trigger",
                reason="这是一个足够长的理由",
                confidence=0.85,
                supporting_examples=["example 1"]
            ),
            "should_pass": False
        },
        {
            "name": "Skill deprecation",
            "suggestion": SkillOptimizationSuggestion(
                skill_name=skills[0].name if skills else "spam_detect",
                suggestion_type="skill_deprecate",
                suggested_value="deprecated_skill",
                reason="这是一个足够长的理由来支持废弃这个技能吧",
                confidence=0.75,
                analysis_detail="这个技能在最近的日志中从未被选中",
                impact="低 - 对系统影响很小",
                supporting_examples=["example 1"]
            ),
            "should_pass": True
        },
        {
            "name": "Skill split",
            "suggestion": SkillOptimizationSuggestion(
                skill_name=skills[0].name if skills else "spam_detect",
                suggestion_type="skill_split",
                suggested_value="split into two skills",
                reason="当前技能覆盖太多场景，需要拆分来提高精准度",
                confidence=0.75,
                analysis_detail="技能覆盖了太多不同类型的场景",
                impact="中 - 提高识别精度",
                suggested_skill_names=["skill_a", "skill_b"],
                supporting_examples=["example 1"]
            ),
            "should_pass": True
        }
    ]

    passed_count = 0
    for tc in test_cases:
        print(f"\nTesting: {tc['name']}")
        print(f"  Suggestion: {tc['suggestion'].skill_name} - {tc['suggestion'].suggestion_type}")
        print(f"  Confidence: {tc['suggestion'].confidence}")
        print(f"  Reason len: {len(tc['suggestion'].reason)}")
        print(f"  Suggested value: {tc['suggestion'].suggested_value}")
        result = agent._validate_suggestion(tc["suggestion"], skills_list)
        status = "✅ PASS" if result == tc["should_pass"] else "❌ FAIL"
        print(f"  Result: {status}")
        print(f"  Expected: {'Pass' if tc['should_pass'] else 'Fail'}, Got: {'Pass' if result else 'Fail'}")
        if result == tc["should_pass"]:
            passed_count += 1

    print(f"\nValidation test results: {passed_count}/{len(test_cases)} passed")
    return passed_count == len(test_cases)


async def test_report_save_and_load():
    """测试报告保存和加载"""
    print("\n" + "="*80)
    print("TEST REPORT SAVE AND LOAD")
    print("="*80)

    from optimization.skill_optimization_agent import (
        SkillOptimizationAgent,
        SkillOptimizationReport,
        SkillOptimizationSuggestion
    )

    agent = SkillOptimizationAgent()

    report = SkillOptimizationReport(
        generated_at=123456789.0,
        suggestion_count=2,
        suggestions=[
            SkillOptimizationSuggestion(
                skill_name="spam_detect",
                suggestion_type="trigger_add",
                suggested_value="加微信",
                reason="这是一个足够长的理由",
                confidence=0.9,
                analysis_detail="这是一个非常详细的分析说明，解释为什么这个优化很重要",
                impact="高 - 提高垃圾识别率",
                supporting_examples=["加微信 abc123"]
            ),
            SkillOptimizationSuggestion(
                skill_name="pii_scan",
                suggestion_type="description_update",
                current_value="旧描述",
                suggested_value="新描述",
                reason="这是另一个足够长的理由",
                confidence=0.8,
                analysis_detail="详细说明为什么更新描述会有所帮助",
                impact="中",
                supporting_examples=["example"]
            )
        ],
        analysis_summary="测试报告摘要",
        voting_required=True,
        approved=False,
        votes=[]
    )

    # 保存报告
    path = agent._save_report(report)
    print(f"Report saved to: {path}")

    # 加载报告
    loaded = agent._load_report(path)
    assert loaded is not None
    assert loaded.analysis_summary == "测试报告摘要"
    assert len(loaded.suggestions) == 2
    assert loaded.suggestions[0].analysis_detail != ""
    assert loaded.suggestions[0].impact != ""

    print("✅ Report save and load test passed!")
    return True


async def main():
    print("\n" + "="*80)
    print("SKILL OPTIMIZATION AGENT - FULL TEST SUITE")
    print("="*80)

    tests = [
        ("Heuristic suggestions", test_heuristic_suggestions()),
        ("LLM suggestions (mock)", test_llm_suggestion_generation()),
        ("Suggestion validation", test_suggestion_validation()),
        ("Report save/load", test_report_save_and_load())
    ]

    passed = 0
    failed = 0

    for name, coro in tests:
        try:
            result = await coro
            if result is not False:  # 数字结果表示建议数，也视为通过
                print(f"\n✅ TEST PASSED: {name}")
                passed += 1
            else:
                print(f"\n❌ TEST FAILED: {name}")
                failed += 1
        except Exception as e:
            print(f"\n❌ TEST FAILED (exception): {name}")
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "="*80)
    print(f"FINAL RESULTS: {passed}/{len(tests)} tests passed")
    print("="*80)

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
