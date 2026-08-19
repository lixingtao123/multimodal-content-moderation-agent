"""测试已应用建议的归档功能"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def main():
    from optimization.skill_optimization_agent import get_skill_optimization_agent

    optimizer = get_skill_optimization_agent()

    print("=" * 80)
    print("已应用建议归档功能测试")
    print("=" * 80)

    # 1. 生成新报告
    print("\n【1/4】生成优化报告...")
    report = await optimizer.analyze_and_suggest(min_logs=10, force=True)

    if report is None:
        print("❌ 未能生成报告")
        return

    print(f"✅ 报告已生成: {report.report_path}")
    print(f"📋 建议数: {len(report.suggestions)}")

    # 2. 批准前两条建议
    print("\n【2/4】批准前两条建议...")
    for i in range(min(2, len(report.suggestions))):
        suggestion = report.suggestions[i]
        print(f"  批准建议 #{suggestion.id}: {suggestion.skill_name} - {suggestion.suggestion_type}")
        await optimizer.vote_suggestion(
            report.report_path, suggestion.id, "admin", True
        )

    # 3. 应用第一条建议
    print("\n【3/4】应用第一条建议...")
    updated_report = optimizer._load_enhanced_report(report.report_path)
    if updated_report:
        approved_ids = [s.id for s in updated_report.suggestions if s.approved]
        if approved_ids:
            result = await optimizer.apply_selected(report.report_path, approved_ids[:1])
            print(f"✅ 应用结果: {result}")

    # 4. 检查最终状态
    print("\n【4/4】检查最终状态...")
    final_report = optimizer._load_enhanced_report(report.report_path)
    if final_report:
        pending_count = sum(1 for s in final_report.suggestions if not s.applied)
        applied_count = sum(1 for s in final_report.suggestions if s.applied)

        print(f"\n📊 建议状态统计:")
        print(f"  待处理: {pending_count} 条")
        print(f"  已应用: {applied_count} 条")

        print(f"\n📝 已应用的建议:")
        for s in final_report.suggestions:
            if s.applied:
                print(f"  ✅ #{s.id}: {s.skill_name} - {s.suggestion_type}")

        print(f"\n📋 待处理的建议:")
        for s in final_report.suggestions:
            if not s.applied:
                status = "  ⏳ 待审批" if not s.approved else "  ✅ 已批准"
                print(f"{status}: #{s.id}: {s.skill_name} - {s.suggestion_type}")

    print("\n" + "=" * 80)
    print("✅ 归档功能测试完成！")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
