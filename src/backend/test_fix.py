"""测试修复后的功能"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def main():
    from optimization.skill_optimization_agent import get_skill_optimization_agent

    optimizer = get_skill_optimization_agent()

    print("=" * 80)
    print("测试修复后的功能")
    print("=" * 80)

    # 获取最新报告
    print("\n📋 获取最新报告...")
    report = optimizer._get_latest_enhanced_report()

    if report is None:
        print("❌ 没有找到报告")
        return

    print(f"✅ 获取到报告: {report.report_path}")
    print(f"📊 建议数量: {len(report.suggestions)}")
    print(f"📊 suggestion_count 属性: {report.suggestion_count}")

    print("\n✅ 测试通过！EnhancedOptimizationReport 现在有 suggestion_count 属性了！")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

