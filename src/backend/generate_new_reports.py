"""生成新的优化报告用于测试"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def main():
    from optimization.skill_optimization_agent import get_skill_optimization_agent

    optimizer = get_skill_optimization_agent()

    print("=" * 80)
    print("生成新的优化报告")
    print("=" * 80)

    # 生成新报告
    print("\n📊 分析路由日志并生成优化建议...")
    report = await optimizer.analyze_and_suggest(min_logs=50, force=True)

    if report is None:
        print("❌ 未能生成报告")
        return

    print(f"\n✅ 报告已生成: {report.report_path}")
    print(f"📋 建议数: {len(report.suggestions)}")
    print(f"📝 分析摘要: {report.analysis_summary}")

    print("\n" + "=" * 80)
    print("详细建议列表:")
    print("=" * 80)

    for i, suggestion in enumerate(report.suggestions):
        print(f"\n📍 建议 #{i+1} (ID: {suggestion.id})")
        print(f"   Skill: {suggestion.skill_name}")
        print(f"   类型: {suggestion.suggestion_type}")
        print(f"   置信度: {suggestion.confidence * 100:.0f}%")
        print(f"   理由: {suggestion.reason}")
        print(f"   当前值: {suggestion.current_value or '(空)'}")
        print(f"   建议值: {suggestion.suggested_value}")
        print(f"   状态: {'已批准' if suggestion.approved else '待审批'}")

    print("\n" + "=" * 80)
    print("✅ 新报告生成完成！")
    print("=" * 80)
    print("\n现在可以在前端测试以下功能：")
    print("  1. 对每条建议进行投票（👎拒绝 / 👍批准）")
    print("  2. 在建议值上方看到 '🚀 应用此建议' 按钮")
    print("  3. 单独应用每条优化建议")
    print("  4. 已应用的建议会归档显示")


if __name__ == "__main__":
    asyncio.run(main())

