"""
测试建议验证功能
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def test_suggestion_validation():
    """测试建议验证功能"""
    from optimization.skill_optimization_agent import SkillOptimizationAgent, SkillOptimizationSuggestion

    agent = SkillOptimizationAgent()

    # 获取真实技能列表
    skills = agent.registry.list_skills()
    skills_list = [
        {"name": s.name, "description": s.description, "triggers": s.triggers, "tags": s.tags, "version": s.version}
        for s in skills
    ]
    print(f"Loaded {len(skills_list)} skills from registry")
    print(f"First skill: {skills_list[0]['name'] if skills_list else 'None'}")

    # 测试一个skill_deprecate建议
    test_suggestion = SkillOptimizationSuggestion(
        skill_name=skills_list[0]['name'],
        suggestion_type="skill_deprecate",
        suggested_value="deprecated_skill",
        reason="这是一个足够长的理由来支持废弃这个技能",
        confidence=0.75,
        analysis_detail="这个技能在最近的日志中从未被选中",
        impact="低 - 对系统影响很小",
        supporting_examples=["example 1"]
    )

    print(f"\nTesting skill_deprecate suggestion...")
    print(f"  Skill: {test_suggestion.skill_name}")
    print(f"  Type: {test_suggestion.suggestion_type}")
    print(f"  Confidence: {test_suggestion.confidence}")
    print(f"  Reason: '{test_suggestion.reason}' (len: {len(test_suggestion.reason)})")
    print(f"  Suggested value: '{test_suggestion.suggested_value}'")

    result = agent._validate_suggestion(test_suggestion, skills_list)
    print(f"\nValidation result: {'✅ PASS' if result else '❌ FAIL'}")

    return result


if __name__ == "__main__":
    success = asyncio.run(test_suggestion_validation())
    sys.exit(0 if success else 1)
