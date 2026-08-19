"""
完整测试增强版 Skill 优化流程：
1. 清理旧报告
2. 生成新报告（增强格式）
3. 对单个建议投票批准
4. 预览优化效果
5. 应用选中的建议
"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def main():
    from optimization.skill_optimization_agent import get_skill_optimization_agent

    optimizer = get_skill_optimization_agent()

    print("=" * 80)
    print("增强版 Skill 自优化完整流程测试")
    print("=" * 80)

    # 1. 清理旧报告
    print("\n【1/5】清理旧报告...")
    reports_dir = Path("/workspace/skills_backups/reports")
    old_reports = list(reports_dir.glob("*.json"))
    for report_file in old_reports:
        print(f"  删除: {report_file.name}")
        report_file.unlink()
    print(f"  ✅ 已清理 {len(old_reports)} 份旧报告")

    # 2. 生成新报告
    print("\n【2/5】分析路由日志并生成优化建议...")
    report = await optimizer.analyze_and_suggest(min_logs=10, force=True)

    if report is None:
        print("❌ 未能生成报告")
        return

    print(f"✅ 报告已生成: {report.report_path}")
    print(f"📋 建议数: {len(report.suggestions)}")
    print(f"📝 摘要: {report.analysis_summary}")

    if not report.suggestions:
        print("❌ 没有建议，测试结束")
        return

    # 3. 展示建议
    print("\n【3/5】优化建议详情:")
    for i, s in enumerate(report.suggestions):
        print(f"\n  ┌───────────────────────────────────────┐")
        print(f"  │  建议 #{s.id}: {s.skill_name}")
        print(f"  └───────────────────────────────────────┘")
        print(f"  📊 类型: {s.suggestion_type}")
        print(f"  📈 置信度: {s.confidence}")
        if s.current_value:
            print(f"  📝 当前值: {s.current_value}")
        print(f"  ✅ 建议值: {s.suggested_value}")
        print(f"  🎯 原因: {s.reason}")
        if s.impact:
            print(f"  📈 影响: {s.impact}")

    # 4. 对单个建议投票
    print("\n【4/5】对单个建议投票批准...")
    if report.suggestions:
        first_suggestion = report.suggestions[0]
        print(f"\n选择建议 #{first_suggestion.id} 进行投票...")
        result = await optimizer.vote_suggestion(
            report.report_path, first_suggestion.id, "admin", True, "批准优化"
        )
        print(f"✅ 投票结果: {result}")

    # 5. 预览优化效果
    print("\n【5/5】预览优化效果...")
    if report.suggestions:
        preview = optimizer.get_preview_diff(report.report_path, first_suggestion.id)
        if preview:
            print(f"\n  预览获取成功！")
            print(f"\n  📄 原文件内容 (前 300 字符):")
            print(f"    {preview['original'][:300]}...")
            print(f"\n  ✅ 优化后内容 (前 300 字符):")
            print(f"    {preview['optimized'][:300]}...")
            if preview['diff']:
                print(f"\n  📊 差异:")
                for line in preview['diff'][:10]:
                    print(f"    {line}")
                if len(preview['diff']) > 10:
                    print(f"    ...还有 {len(preview['diff']) - 10} 行")
        else:
            print(f"  ⚠️  没有获取到预览")

    # 6. 应用部分建议
    print("\n【6/6】应用部分建议...")
    # 重新加载报告查看状态
    updated_report = optimizer._load_enhanced_report(report.report_path)
    if updated_report:
        approved_ids = [s.id for s in updated_report.suggestions if s.approved]
        if approved_ids:
            print(f"\n已批准的建议 ID: {approved_ids}")
            print(f"应用建议 {approved_ids[:1]}...")
            result = await optimizer.apply_selected(report.report_path, approved_ids[:1])
            print(f"\n应用结果: {result}")
            print("\n✅ 流程测试完成！")
        else:
            print("\n⚠️ 没有已批准的建议可应用")
    else:
        print("\n⚠️ 重新加载报告失败")


if __name__ == "__main__":
    asyncio.run(main())
