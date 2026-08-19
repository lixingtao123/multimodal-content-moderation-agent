"""检查当前报告的状态"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main():
    from optimization.skill_optimization_agent import get_skill_optimization_agent

    optimizer = get_skill_optimization_agent()

    print("=" * 80)
    print("检查当前报告状态")
    print("=" * 80)

    report = optimizer._get_latest_enhanced_report()

    if report is None:
        print("❌ 没有找到报告")
        return

    print(f"\n📄 报告路径: {report.report_path}")
    print(f"📋 建议总数: {len(report.suggestions)}")

    print(f"\n详细建议状态:")
    print("-" * 80)

    for suggestion in report.suggestions:
        status = "✅ 已应用" if suggestion.applied else "👍 已批准" if suggestion.approved else "⏳ 待审批"
        print(f"\n📍 建议 #{suggestion.id}: {suggestion.skill_name}")
        print(f"   类型: {suggestion.suggestion_type}")
        print(f"   状态: {status}")
        print(f"   当前值: {repr(suggestion.current_value or '(空)')}")
        print(f"   建议值: {repr(suggestion.suggested_value)}")

        if suggestion.current_value and suggestion.suggested_value:
            if suggestion.current_value.strip() == suggestion.suggested_value.strip():
                print(f"   ⚠️  当前值和建议值完全相同！")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()

