"""
运行Skill自优化分析的脚本
1. 导入demo数据到数据库
2. 运行SkillOptimizationAgent进行分析
"""
import sys
import asyncio
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

async def import_demo_data():
    """导入demo数据到数据库"""
    from datetime import datetime
    from db.connection import get_session_factory, init_db
    from db.models import SkillRoutingLog
    import json

    # 初始化数据库
    await init_db()

    demo_logs_path = Path(__file__).parent.parent.parent / "skill_demo_data" / "skill_routing_logs.jsonl"
    if not demo_logs_path.exists():
        print(f"Demo logs not found at {demo_logs_path}")
        return 0

    logs_to_import = []
    with open(demo_logs_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                data = json.loads(line)
                logs_to_import.append(data)

    session_factory = get_session_factory()
    imported_count = 0

    async with session_factory() as session:
        # 检查是否已导入
        from sqlalchemy import select, func
        count_result = await session.execute(select(func.count(SkillRoutingLog.id)))
        existing_count = count_result.scalar() or 0
        print(f"数据库中已有 {existing_count} 条路由日志")

        # 导入新数据
        for data in logs_to_import:
            # 检查是否已存在
            check_stmt = select(SkillRoutingLog).where(SkillRoutingLog.content_id == data["content_id"])
            check_result = await session.execute(check_stmt)
            existing_log = check_result.scalar_one_or_none()

            if existing_log:
                continue

            log = SkillRoutingLog(
                content_id=data["content_id"],
                agent=data["agent"],
                query=data["query"],
                content_type=data["content_type"],
                filtered_skills=data["filtered"],
                ranked_skills=data["ranked"],
                selected_skills=data["selected"],
                timestamp=datetime.fromtimestamp(data["timestamp"])
            )
            session.add(log)
            imported_count += 1

        await session.commit()

    return imported_count


async def run_analysis():
    """运行Skill优化分析"""
    from optimization.skill_optimization_agent import get_skill_optimization_agent

    print("正在初始化SkillOptimizationAgent...")
    agent = get_skill_optimization_agent()

    print("正在分析路由日志...")
    report = await agent.analyze_and_suggest(min_logs=10)

    if report is None:
        print("分析失败，日志数不足或其他问题")
        return None

    return report


def print_report(report):
    """打印分析报告"""
    print("\n" + "="*80)
    print("SKILL OPTIMIZATION ANALYSIS REPORT")
    print("="*80)
    print(f"生成时间: {report.generated_at}")
    print(f"建议总数: {report.suggestion_count}")
    print(f"摘要: {report.analysis_summary}")
    print(f"是否已批准: {report.approved}")
    print(f"报告路径: {report.report_path}")
    print("\n" + "="*80)
    print("DETAILED SUGGESTIONS")
    print("="*80)

    for i, suggestion in enumerate(report.suggestions, 1):
        print(f"\n【{i}】 {suggestion.skill_name} - {suggestion.suggestion_type.upper()}")
        print(f"置信度: {suggestion.confidence}")
        print(f"影响级别: {suggestion.impact}")
        print(f"理由: {suggestion.reason}")
        if suggestion.analysis_detail:
            print(f"详细分析: {suggestion.analysis_detail}")
        if suggestion.current_value:
            print(f"当前值: {suggestion.current_value}")
        if suggestion.suggested_value:
            print(f"建议值: {suggestion.suggested_value}")
        if suggestion.supporting_examples:
            print(f"相关示例: {', '.join(suggestion.supporting_examples[:3])}")
        if hasattr(suggestion, "related_skill_names") and suggestion.related_skill_names:
            print(f"相关技能: {suggestion.related_skill_names}")
        if hasattr(suggestion, "suggested_skill_names") and suggestion.suggested_skill_names:
            print(f"建议的新技能: {suggestion.suggested_skill_names}")
        print("-"*80)


async def main():
    print("="*80)
    print("SKILL SELF-OPTIMIZATION ANALYSIS")
    print("="*80)

    # 1. 导入demo数据
    print("\n步骤1: 导入demo数据到数据库")
    imported = await import_demo_data()
    print(f"导入了 {imported} 条新日志")

    # 2. 运行分析
    print("\n步骤2: 运行优化分析")
    report = await run_analysis()

    if report is None:
        print("未生成报告，分析失败")
        return

    # 3. 打印报告
    print_report(report)

    print("\n✅ 分析完成！")


if __name__ == "__main__":
    asyncio.run(main())
