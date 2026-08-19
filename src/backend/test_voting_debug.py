"""
调试投票功能问题
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

async def test_voting():
    from optimization.skill_optimization_agent import get_skill_optimization_agent

    agent = get_skill_optimization_agent()

    # 首先列出所有报告
    reports_dir = Path("/workspace/skills_backups/reports")
    report_files = sorted(reports_dir.glob("skill_opt_*.json"), reverse=True)

    print(f"找到 {len(report_files)} 个报告文件")

    if not report_files:
        print("没有报告文件，先生成一个测试报告")
        return

    # 用第一个报告
    report_path = str(report_files[0])
    print(f"\n使用报告: {report_path}")

    # 测试加载
    print("\n1. 测试加载报告...")
    report = agent._load_report(report_path)
    if not report:
        print(f"  ❌ 加载失败，只传文件名试试...")
        filename_only = report_files[0].name
        report = agent._load_report(filename_only)
        if report:
            print(f"  ✅ 使用文件名加载成功: {filename_only}")
        else:
            print(f"  ❌ 文件名也加载失败")
            return
    else:
        print(f"  ✅ 加载成功")

    print(f"  - 报告路径: {report.report_path}")
    print(f"  - 已批准: {report.approved}")
    print(f"  - 当前票数: {len(report.votes)}")

    # 测试投票
    print("\n2. 测试投票...")
    result = await agent.add_vote(report.report_path, "test_user_1", True, "测试投票1")
    print(f"  结果: {result}")

    # 再次加载确认
    print("\n3. 验证投票结果...")
    report2 = agent._load_report(report.report_path)
    print(f"  最新票数: {len(report2.votes) if report2 else 'N/A'}")
    if report2:
        for v in report2.votes:
            print(f"  - {v['voter']}: {'👍' if v['vote'] else '👎'} {v['comment']}")

    print("\n✅ 调试完成")

if __name__ == "__main__":
    asyncio.run(test_voting())
