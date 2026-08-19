"""
测试单人审核模式
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def main():
    from optimization.skill_optimization_agent import get_skill_optimization_agent

    agent = get_skill_optimization_agent()

    print("=" * 70)
    print("测试单人审核模式")
    print("=" * 70)

    # 1. 测试投票（单人通过）
    print("\n1. 测试单人投票...")
    report_file = "skill_opt_1786641537.json"

    result = await agent.add_vote(report_file, "tester", True, "测试单人通过")
    print(f"   ✓ 投票结果: {'已批准' if result['approved'] else '未批准'}")

    if result['approved']:
        print(f"   ✓ 单人审核模式工作正常！")

    # 2. 重新加载报告验证
    print("\n2. 重新加载报告验证...")
    report = agent._load_report(report_file)
    if report:
        print(f"   ✓ 报告加载成功")
        print(f"   ✓ 已批准: {report.approved}")
        print(f"   ✓ 建议数: {report.suggestion_count}")

        # 3. 测试应用建议（只做预览，不实际修改）
        print("\n3. 建议预览（前3条）:")
        for i, s in enumerate(report.suggestions[:3]):
            print(f"\n   [{i+1}] {s.skill_name} - {s.suggestion_type}")
            print(f"       当前: {s.current_value}")
            print(f"       建议: {s.suggested_value}")
            print(f"       理由: {s.reason}")

    print("\n" + "=" * 70)
    print("✓ 单人审核模式测试完成！")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())

