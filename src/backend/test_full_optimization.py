"""完整测试 Skill 优化流程：生成 → 投票 → 应用 → 展示效果"""
import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def main():
    from optimization.skill_optimization_agent import get_skill_optimization_agent

    optimizer = get_skill_optimization_agent()

    print("=" * 80)
    print("Skill 自优化完整流程测试")
    print("=" * 80)

    # 1. 生成新报告
    print("\n【1/5】分析路由日志并生成优化建议...")
    report = await optimizer.analyze_and_suggest(min_logs=10, force=True)

    if report is None:
        print("❌ 未能生成报告（日志不足）")
        return

    print(f"✅ 报告已生成: {report.report_path}")
    print(f"📊 建议数: {report.suggestion_count}")
    print(f"📝 摘要: {report.analysis_summary}")

    # 2. 展示建议
    print("\n【2/5】优化建议详情:")
    for i, s in enumerate(report.suggestions):
        print(f"\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  [{i+1}] {s.skill_name} - {s.suggestion_type}")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  📊 置信度: {s.confidence}")
        if s.current_value:
            print(f"  📝 当前值: {s.current_value}")
        if s.suggested_value:
            print(f"  ✅ 建议值: {s.suggested_value}")
        print(f"  🎯 原因: {s.reason}")
        if s.analysis_detail:
            print(f"  🔍 分析: {s.analysis_detail}")
        if s.impact:
            print(f"  📈 影响: {s.impact}")
        if s.supporting_examples:
            print(f"  📌 示例: {s.supporting_examples}")

    # 3. 单人投票批准
    print("\n【3/5】单人投票批准（任何一票通过即批准）...")
    result = await optimizer.add_vote(report.report_path, "admin", True, "同意所有优化")
    print(f"✅ 投票结果: {'已批准' if result['approved'] else '未批准'}")

    # 4. 备份当前 Skill 并展示对比
    print("\n【4/5】对比优化前后的 Skill（先备份）...")
    skills_dir = Path("/workspace/skills")
    print(f"\n当前 Skill 目录文件:")
    for skill_dir in sorted(skills_dir.iterdir()):
        if skill_dir.is_dir():
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                print(f"  📂 {skill_dir.name}")

    # 5. 应用优化
    print("\n【5/5】应用优化建议...")
    # 先重新加载报告（确认已批准）
    report = optimizer._load_report(report.report_path)
    result = await optimizer.apply_suggestions(report)

    print(f"\n应用结果:")
    print(f"  ✅ 成功: {result['success']}")
    print(f"  📊 已应用: {result['applied_count']} 条")
    print(f"  ⏭️  已跳过: {result['skipped_count']} 条")

    if result.get('errors'):
        print(f"  ❌ 错误: {result['errors']}")

    # 6. 展示优化后的 Skill 文件对比
    print("\n" + "=" * 80)
    print("优化后的 Skill 文件变更")
    print("=" * 80)

    # 检查哪些 Skill 被修改了
    backups_dir = Path("/workspace/skills_backups")
    modified_skills = set()

    for backup in backups_dir.glob("*_v*.md"):
        skill_name = "_".join(backup.stem.split("_")[:-2])
        if skill_name:
            modified_skills.add(skill_name)

    # 展示修改后的 Skill
    for skill_name in sorted(modified_skills):
        skill_dir = skills_dir / skill_name
        if not skill_dir.exists():
            skill_dir = skills_dir / skill_name.replace("-", "_")
        if not skill_dir.exists():
            continue

        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            print(f"\n📂 {skill_name}")
            print("  " + "-" * 70)
            with open(skill_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            for line in lines[:30]:  # 只展示前30行
                print(f"  {line.rstrip()}")
            if len(lines) > 30:
                print(f"  ... (还有 {len(lines)-30} 行)")

    print("\n" + "=" * 80)
    print("✅ 完整流程测试完成")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
