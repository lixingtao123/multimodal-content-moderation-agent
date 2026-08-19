#!/usr/bin/env python3
"""
测试 SkillOptimizationAgent — LLM-driven Skill Optimizer
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / ".." / "src" / "backend"))


async def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║  测试 SkillOptimizationAgent (LLM-driven)               ║
╚══════════════════════════════════════════════════════════╝
""")

    # 1. 初始化 Agent
    from optimization.skill_optimization_agent import get_skill_optimization_agent
    agent = get_skill_optimization_agent()

    print("✅ SkillOptimizationAgent 已初始化")

    # 2. 测试加载日志
    logs = await agent._load_routing_logs_from_db()
    print(f"✅ 从数据库加载了 {len(logs)} 条路由日志")

    if len(logs) > 0:
        print(f"📊 最近一条日志: {logs[0].get('query', '')[:50]}...")

    # 3. 检查 API Key
    import os
    from common.config import get_settings
    settings = get_settings()

    api_key = settings.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key or api_key == "sk-your-key-here":
        print("""
⚠️  警告: 未配置有效的 DeepSeek API Key

请设置环境变量:
    export DEEPSEEK_API_KEY=sk-your-actual-key

或者修改 .env 文件

========== 不调用 LLM 的测试模式 ==========
""")
        # 在不调用 LLM 的情况下测试其他部分
        await test_without_llm(agent, logs)
        return

    # 4. 测试完整分析
    print("🚀 开始 LLM 分析（可能需要 10-30 秒）...")
    report = await agent.analyze_and_suggest(min_logs=10)

    if report:
        print(f"""
✅ 分析完成！

分析摘要: {report.analysis_summary}
建议数量: {report.suggestion_count}

生成的优化建议:
""")
        for i, suggestion in enumerate(report.suggestions, 1):
            print(f"{i}. [{suggestion.suggestion_type}] {suggestion.skill_name}")
            print(f"   理由: {suggestion.reason[:80]}...")
            print(f"   置信度: {suggestion.confidence}")
            print()

        print(f"""
✅ 报告已保存到: {report.report_path}

现在可以:
1. 访问前端 SkillManager 查看建议
2. 投票表决建议
3. 应用优化（需要 2/3 投票通过）
""")
    else:
        print("❌ 未生成报告（可能日志不足）")


async def test_without_llm(agent, logs):
    """不调用 LLM 的测试模式"""
    # 测试日志摘要
    summary = agent._summarize_logs(logs)
    print(f"📊 日志摘要:")
    print(f"   总日志: {summary['total_logs']}")
    print(f"   Skill统计: {summary['skill_stats']}")

    # 测试 frontmatter 解析
    from agent_moderation.skill_registry import get_skill_registry
    registry = get_skill_registry()
    print(f"✅ 已加载 {len(registry.list_skills())} 个 Skills")

    # 测试报告保存/加载
    from optimization.skill_optimization_agent import SkillOptimizationReport, SkillOptimizationSuggestion
    test_report = SkillOptimizationReport(
        generated_at=123456789,
        suggestion_count=1,
        suggestions=[SkillOptimizationSuggestion(
            skill_name="test-skill",
            suggestion_type="description_update",
            current_value="旧描述",
            suggested_value="新描述",
            reason="测试理由",
            confidence=0.8,
        )],
        analysis_summary="测试报告摘要",
    )

    saved_path = agent._save_report(test_report)
    print(f"✅ 测试报告已保存到: {saved_path}")

    loaded_report = agent._load_report(saved_path)
    if loaded_report:
        print("✅ 测试报告加载成功")
        print(f"   摘要: {loaded_report.analysis_summary}")

    print("""
✅ 无 LLM 测试通过！

提示: 如果你想测试完整的 LLM 分析功能，
请配置有效的 DEEPSEEK_API_KEY
""")


if __name__ == "__main__":
    asyncio.run(main())
