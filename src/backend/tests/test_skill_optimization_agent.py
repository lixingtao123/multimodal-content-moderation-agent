"""
测试 SkillOptimizationAgent v3.0 — 高级智能优化器

测试内容:
- Agent 初始化
- 智能触发词挖掘
- 描述优化（无意义后缀检测）
- 标签优化
- 废弃建议（高阈值）
- 报告保存/加载
- 投票逻辑
- Skill 文件修改
"""
import asyncio
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import sys

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / ".."))


def test_agent_initialization():
    """测试 Agent 初始化"""
    print("\n🧪 测试 Agent 初始化...")
    from optimization.skill_optimization_agent import get_skill_optimization_agent
    agent = get_skill_optimization_agent()

    assert agent is not None
    assert agent.registry is not None

    skills = agent.registry.list_skills()
    assert len(skills) > 0

    print(f"✅ 初始化成功，已加载 {len(skills)} 个 Skills")


def test_frontmatter_parse_and_generate():
    """测试 Frontmatter 解析和生成"""
    print("\n🧪 测试 Frontmatter 解析和生成...")
    from optimization.skill_optimization_agent import SkillOptimizationAgent

    agent = SkillOptimizationAgent()

    test_frontmatter = '''name: test-skill
description: 测试描述
version: 1.0.0
tags:
  - test
  - example
triggers:
  - trigger1
  - trigger2
'''

    # 测试解析
    parsed = agent._parse_simple_frontmatter(test_frontmatter)
    assert parsed["name"] == "test-skill"
    assert parsed["description"] == "测试描述"
    assert parsed["tags"] == ["test", "example"]
    assert parsed["triggers"] == ["trigger1", "trigger2"]

    # 测试生成
    generated = agent._generate_frontmatter(parsed)
    assert "name: test-skill" in generated
    assert "description: 测试描述" in generated
    assert "version: 1.0.0" in generated

    print("✅ Frontmatter 解析和生成测试通过")


def test_report_save_and_load():
    """测试报告保存和加载"""
    print("\n🧪 测试报告保存和加载...")
    from optimization.skill_optimization_agent import (
        SkillOptimizationAgent,
        SkillOptimizationReport,
        SkillOptimizationSuggestion,
    )

    agent = SkillOptimizationAgent()

    # 创建测试报告（增强版字段）
    report = SkillOptimizationReport(
        generated_at=123456789,
        suggestion_count=1,
        suggestions=[
            SkillOptimizationSuggestion(
                skill_name="test-skill",
                suggestion_type="description_update",
                current_value="旧描述",
                suggested_value="新描述",
                reason="这是一个足够长的理由来通过验证测试",
                confidence=0.8,
                analysis_detail="详细分析内容...",
                impact="中",
            )
        ],
        analysis_summary="测试报告摘要",
    )

    # 保存
    filename = agent._save_report(report)
    reports_dir = Path("/workspace/skills_backups/reports")
    assert (reports_dir / filename).exists()

    # 加载
    loaded = agent._load_report(filename)
    assert loaded is not None
    assert loaded.analysis_summary == "测试报告摘要"
    assert len(loaded.suggestions) == 1
    assert loaded.suggestions[0].analysis_detail == "详细分析内容..."
    assert loaded.suggestions[0].impact == "中"
    assert "/" not in loaded.report_path

    print("✅ 报告保存和加载测试通过")


def test_voting_logic():
    """测试投票逻辑"""
    print("\n🧪 测试投票逻辑...")
    from optimization.skill_optimization_agent import (
        SkillOptimizationAgent,
        SkillOptimizationReport,
        SkillOptimizationSuggestion,
    )

    agent = SkillOptimizationAgent()

    # 创建测试报告
    report = SkillOptimizationReport(
        generated_at=123456789,
        suggestion_count=0,
        suggestions=[],
        analysis_summary="测试投票",
        approved=False,
    )
    path = agent._save_report(report)

    # 测试 1 票 (未通过)
    result = asyncio.run(agent.add_vote(path, "voter1", True, "同意"))
    assert not result["approved"]

    # 测试 2 票 (未达到 3 人)
    result = asyncio.run(agent.add_vote(path, "voter2", True, "同意"))
    assert not result["approved"]

    # 测试 3 票 (2 通过)
    result = asyncio.run(agent.add_vote(path, "voter3", True, "同意"))
    assert result["approved"]

    print("✅ 投票逻辑测试通过")


def test_log_summarization():
    """测试日志摘要"""
    print("\n🧪 测试日志摘要...")
    from optimization.skill_optimization_agent import SkillOptimizationAgent

    agent = SkillOptimizationAgent()

    test_logs = [
        {
            "query": "测试查询1",
            "selected": ["skill-a", "skill-b"],
            "ranked": ["skill-a", "skill-b", "skill-c"],
            "filtered": ["skill-a", "skill-b", "skill-c"],
        },
        {
            "query": "测试查询2",
            "selected": ["skill-a"],
            "ranked": ["skill-a", "skill-b"],
            "filtered": ["skill-a", "skill-b"],
        },
    ]

    summary = agent._summarize_logs(test_logs)

    assert summary["total_logs"] == 2
    assert summary["skill_stats"]["skill-a"] == 2
    assert summary["skill_stats"]["skill-b"] == 1

    print("✅ 日志摘要测试通过")


def test_trigger_mining_heuristic():
    """测试智能触发词挖掘逻辑"""
    print("\n🧪 测试智能触发词挖掘...")
    from optimization.skill_optimization_agent import SkillOptimizationAgent

    agent = SkillOptimizationAgent()

    # 获取真实的 skills
    real_skills = agent.registry.list_skills()
    if not real_skills:
        print("⚠️  没有真实的 Skills，跳过此测试")
        return

    # 构造相关路由日志
    spam_skill = None
    for s in real_skills:
        if "spam" in s.name.lower():
            spam_skill = s
            break

    if not spam_skill:
        print("⚠️  没有 spam 相关的 Skill，跳过触发词挖掘测试")
        return

    # 构造日志：包含 "加微信" 关键词
    routing_logs = [
        {
            "query": "加微信 abc123 了解更多",
            "content_type": "text",
            "agent": "text_agent",
            "filtered": [spam_skill.name],
            "ranked": [spam_skill.name],
            "selected": [spam_skill.name],
        },
        {
            "query": "加微信 xyz789 赚钱项目",
            "content_type": "text",
            "agent": "text_agent",
            "filtered": [spam_skill.name],
            "ranked": [spam_skill.name],
            "selected": [spam_skill.name],
        },
        {
            "query": "扫码进群领红包",
            "content_type": "text",
            "agent": "text_agent",
            "filtered": [spam_skill.name],
            "ranked": [spam_skill.name],
            "selected": [spam_skill.name],
        },
    ] * 3  # 重复几次让统计有效

    # 测试触发词挖掘
    suggestions = agent._generate_heuristic_suggestions(routing_logs)

    print(f"✅ 生成了 {len(suggestions)} 条建议")

    # 检查是否有触发词添加建议
    trigger_add_suggestions = [s for s in suggestions if s.suggestion_type == "trigger_add"]
    if trigger_add_suggestions:
        print(f"   其中 {len(trigger_add_suggestions)} 条是触发词添加建议")
        for s in trigger_add_suggestions:
            print(f"   - {s.skill_name}: +'{s.suggested_value}'")

    print("✅ 触发词挖掘逻辑测试通过")


def test_description_improvement():
    """测试描述优化逻辑（确保无无意义后缀）"""
    print("\n🧪 测试描述优化逻辑...")
    from optimization.skill_optimization_agent import SkillOptimizationAgent

    agent = SkillOptimizationAgent()

    # 测试智能描述生成
    improved_spam = agent._generate_improved_description(
        "spam_detect",
        "原描述",
        ["加微信赚钱"]
    )

    improved_pii = agent._generate_improved_description(
        "pii_scan",
        "原描述",
        ["手机号泄露"]
    )

    print(f"   spam_detect 优化: {improved_spam}")
    print(f"   pii_scan 优化: {improved_pii}")

    # 确保不是简单的添加后缀
    assert "(优化语义匹配)" not in improved_spam
    assert improved_spam != "原描述" + "(优化语义匹配)"

    print("✅ 描述优化逻辑测试通过")


def test_deprecation_threshold():
    """测试废弃建议的高阈值逻辑"""
    print("\n🧪 测试废弃建议高阈值...")
    from optimization.skill_optimization_agent import SkillOptimizationAgent

    agent = SkillOptimizationAgent()

    # 获取真实的 skills
    real_skills = agent.registry.list_skills()
    if not real_skills:
        print("⚠️  没有真实的 Skills，跳过此测试")
        return

    # 构造日志（20条，但废弃需要200条，所以不应生成废弃建议）
    skills_dict = {s.name: s for s in real_skills}
    log_summary = {
        "total_logs": 20,  # < 200
        "skill_stats": {s.name: 0 for s in real_skills},
    }

    # 测试废弃建议生成
    suggestions = agent._generate_deprecate_suggestions(skills_dict, log_summary)

    # 应该不会有废弃建议，因为日志不足200
    assert len(suggestions) == 0, "日志只有20条时不应生成废弃建议"

    print("✅ 废弃建议高阈值逻辑测试通过")


def test_skill_modification():
    """测试 Skill 文件修改"""
    print("\n🧪 测试 Skill 文件修改...")
    from optimization.skill_optimization_agent import (
        SkillOptimizationAgent,
        SkillOptimizationSuggestion,
    )

    agent = SkillOptimizationAgent()

    # 创建临时 Skill 文件
    with tempfile.TemporaryDirectory() as temp_dir:
        # 暂时修改 SKILLS_DIR
        import optimization.skill_optimization_agent as soa_module
        original_skills_dir = soa_module.SKILLS_DIR
        original_backup_dir = soa_module.SKILL_BACKUP_DIR
        original_deprecated_dir = soa_module.DEPRECATED_DIR

        temp_skills = Path(temp_dir) / "skills"
        temp_backup = Path(temp_dir) / "skills_backup"
        temp_deprecated = temp_backup / "deprecated"
        temp_skills.mkdir()
        temp_backup.mkdir()
        temp_deprecated.mkdir()

        soa_module.SKILLS_DIR = temp_skills
        soa_module.SKILL_BACKUP_DIR = temp_backup
        soa_module.DEPRECATED_DIR = temp_deprecated

        try:
            # 创建测试 Skill 目录
            test_skill_dir = temp_skills / "test-skill"
            test_skill_dir.mkdir()

            skill_content = '''---
name: test-skill
description: 原始描述
version: 1.0.0
tags: ["original"]
triggers: ["trigger1"]
---

# Test Skill

## Overview
测试描述
'''
            skill_file = test_skill_dir / "SKILL.md"
            with open(skill_file, 'w', encoding='utf-8') as f:
                f.write(skill_content)

            # 测试添加 Trigger
            suggestion = SkillOptimizationSuggestion(
                skill_name="test-skill",
                suggestion_type="trigger_add",
                current_value="",
                suggested_value="new-trigger",
                reason="测试添加触发词，这是一个足够长的理由",
                confidence=0.8,
            )

            modified_content = agent._modify_skill_content(skill_content, suggestion)

            assert "new-trigger" in modified_content

            # 测试更新 Description
            suggestion = SkillOptimizationSuggestion(
                skill_name="test-skill",
                suggestion_type="description_update",
                current_value="原始描述",
                suggested_value="新描述",
                reason="测试更新描述，这是一个足够长的理由",
                confidence=0.8,
            )

            modified_content = agent._modify_skill_content(skill_content, suggestion)

            assert "新描述" in modified_content

            print("✅ Skill 文件修改测试通过")

        finally:
            # 恢复原目录
            soa_module.SKILLS_DIR = original_skills_dir
            soa_module.SKILL_BACKUP_DIR = original_backup_dir
            soa_module.DEPRECATED_DIR = original_deprecated_dir


def test_new_suggestion_types():
    """测试建议类型"""
    print("\n🧪 测试建议类型...")
    from optimization.skill_optimization_agent import SkillOptimizationAgent

    agent = SkillOptimizationAgent()

    # 验证所有类型都在 VALID_TYPES 中
    assert "description_update" in agent.VALID_TYPES
    assert "trigger_add" in agent.VALID_TYPES
    assert "trigger_remove" in agent.VALID_TYPES
    assert "tag_add" in agent.VALID_TYPES
    assert "tag_remove" in agent.VALID_TYPES
    assert "new_skill" in agent.VALID_TYPES
    assert "skill_split" in agent.VALID_TYPES
    assert "skill_merge" in agent.VALID_TYPES
    assert "skill_deprecate" in agent.VALID_TYPES

    print("✅ 建议类型测试通过")


def test_with_db_logs():
    """测试从数据库加载日志"""
    print("\n🧪 测试从数据库加载日志...")
    from optimization.skill_optimization_agent import SkillOptimizationAgent

    agent = SkillOptimizationAgent()

    # 尝试从数据库加载
    result = asyncio.run(agent._load_routing_logs_from_db())

    print(f"✅ 数据库日志加载测试通过，加载了 {len(result)} 条记录")


def test_end_to_end_analysis():
    """测试端到端分析流程"""
    print("\n🧪 测试端到端分析流程...")
    from optimization.skill_optimization_agent import get_skill_optimization_agent

    agent = get_skill_optimization_agent()

    # 尝试完整分析（使用 demo 日志）
    report = asyncio.run(agent.analyze_and_suggest(min_logs=5))

    if report:
        print(f"✅ 分析成功，生成了 {report.suggestion_count} 条建议")
        print(f"   摘要: {report.analysis_summary}")
        for i, s in enumerate(report.suggestions[:5]):
            print(f"   {i+1}. {s.skill_name}: {s.suggestion_type}")
            print(f"      原因: {s.reason[:50]}...")
    else:
        print("⚠️  未生成报告（可能是日志不足）")

    print("✅ 端到端分析流程测试通过")


def run_all_tests():
    """运行所有测试"""
    print("""
╔══════════════════════════════════════════════════════════╗
║  SkillOptimizationAgent v3.0 测试套件                   ║
║  高级智能优化器                                         ║
╚══════════════════════════════════════════════════════════╝
""")

    tests_passed = 0
    tests_failed = 0

    test_functions = [
        test_agent_initialization,
        test_frontmatter_parse_and_generate,
        test_report_save_and_load,
        test_voting_logic,
        test_log_summarization,
        test_trigger_mining_heuristic,
        test_description_improvement,
        test_deprecation_threshold,
        test_skill_modification,
        test_new_suggestion_types,
        test_with_db_logs,
        test_end_to_end_analysis,
    ]

    for test_func in test_functions:
        try:
            test_func()
            tests_passed += 1
        except Exception as e:
            print(f"❌ 测试失败: {test_func.__name__}")
            print(f"   错误: {e}")
            import traceback
            traceback.print_exc()
            tests_failed += 1

    print(f"""
╔══════════════════════════════════════════════════════════╗
║  测试完成！                                              ║
╠══════════════════════════════════════════════════════════╣
║  通过: {tests_passed:2d}                                       ║
║  失败: {tests_failed:2d}                                       ║
╚══════════════════════════════════════════════════════════╝
""")

    return tests_failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
