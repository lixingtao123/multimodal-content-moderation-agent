"""生成最终的优化报告"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def main():
    from optimization.skill_optimization_agent import get_skill_optimization_agent

    agent = get_skill_optimization_agent()

    print("清除旧报告...")
    reports_dir = Path("/workspace/skills_backups/reports")
    for f in reports_dir.glob("skill_opt_*.json"):
        f.unlink()

    print("分析并生成新报告...")
    report = await agent.analyze_and_suggest(min_logs=5)

    if report:
        print(f"✅ 成功生成报告：{report.report_path}")
        print(f"📊 共 {report.suggestion_count} 条建议")
        print(f"📝 摘要：{report.analysis_summary}")

        # 打印前几条建议预览
        for i, s in enumerate(report.suggestions[:5]):
            print(f"\n[{i+1}] {s.skill_name} - {s.suggestion_type}")
            print(f"    {s.suggested_value}")
            print(f"    {s.reason[:50]}...")
    else:
        print("❌ 未能生成报告")


if __name__ == "__main__":
    asyncio.run(main())
