"""
快速测试 SkillOptimizationAgent v3.0
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def main():
    from optimization.skill_optimization_agent import get_skill_optimization_agent

    agent = get_skill_optimization_agent()

    print("""
╔══════════════════════════════════════════════════════════╗
║  SkillOptimizationAgent v3.0 快速测试                    ║
╚══════════════════════════════════════════════════════════╝
""")

    # 1. 测试日志加载
    print("\n1️⃣  加载日志...")
    db_logs = await agent._load_routing_logs_from_db()
    file_logs = agent._load_routing_logs_from_file("/tmp")
    print(f"   - DB 日志: {len(db_logs)} 条")
    print(f"   - 文件日志: {len(file_logs)} 条")

    all_logs = db_logs + file_logs
    print(f"   - 总计: {len(all_logs)} 条")

    if len(all_logs) < 10:
        print("   ⚠️  日志不足，使用 demo 日志")

    # 2. 分析建议
    print("\n2️⃣  运行分析...")
    report = await agent.analyze_and_suggest(min_logs=5)

    if not report:
        print("   ❌ 未生成报告")
        return

    print(f"   ✅ 分析成功！")
    print(f"   - 建议数量: {report.suggestion_count}")
    print(f"   - 摘要: {report.analysis_summary}")

    # 3. 列出建议
    print("\n3️⃣  建议详情:")
    if report.suggestions:
        for i, s in enumerate(report.suggestions):
            print(f"\n   [{i+1}] {s.skill_name} - {s.suggestion_type}")
            print(f"       置信度: {s.confidence:.2f}")
            if s.suggested_value:
                print(f"       建议值: {s.suggested_value}")
            print(f"       原因: {s.reason}")
            if s.analysis_detail:
                print(f"       分析: {s.analysis_detail[:80]}...")
            if s.impact:
                print(f"       影响: {s.impact}")
            if s.supporting_examples:
                print(f"       示例: {s.supporting_examples}")
    else:
        print("   ⚠️  没有建议")

    # 4. 测试投票
    print("\n4️⃣  测试投票...")
    print(f"   报告文件: {report.report_path}")

    result = await agent.add_vote(report.report_path, "tester1", True, "测试投票1")
    print(f"   - 投票1: {'已批准' if result['approved'] else '未批准'}")

    result = await agent.add_vote(report.report_path, "tester2", True, "测试投票2")
    print(f"   - 投票2: {'已批准' if result['approved'] else '未批准'}")

    result = await agent.add_vote(report.report_path, "tester3", True, "测试投票3")
    print(f"   - 投票3: {'已批准' if result['approved'] else '未批准'}")

    # 5. 重新加载验证
    print("\n5️⃣  重新加载验证...")
    reloaded = agent._load_report(report.report_path)
    print(f"   - 重新加载 OK: {reloaded is not None}")
    if reloaded:
        print(f"   - 已批准: {reloaded.approved}")
        print(f"   - 票数: {len(reloaded.votes)}")
        for v in reloaded.votes:
            print(f"     - {v['voter']}: {'👍' if v['vote'] else '👎'} {v['comment']}")

    print("""
╔══════════════════════════════════════════════════════════╗
║  ✅ v3.0 快速测试完成！                                  ║
╚══════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    asyncio.run(main())
