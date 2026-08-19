"""恢复所有技能到原始状态"""
import shutil
from pathlib import Path


def restore_skill_from_backup(skill_name: str, backup_dir: Path):
    """从备份恢复单个技能"""
    # 处理 skill_name 的变体（可能有连字符或下划线）
    possible_names = [skill_name, skill_name.replace("-", "_"), skill_name.replace("_", "-")]

    for name in possible_names:
        skill_dir = Path("/workspace/skills") / name
        if skill_dir.exists():
            break
    else:
        print(f"⚠️ 找不到技能目录: {skill_name}")
        return False

    # 查找最新的备份
    backups = list(Path("/workspace/skills_backups").glob(f"{skill_name.replace('-', '_')}_v*.md"))
    if backups:
        # 找到最早的备份（数字最小的）
        backups.sort(key=lambda x: int(x.stem.split("_v")[-1]))
        oldest_backup = backups[0]
        print(f"📋 从备份恢复: {skill_name} ← {oldest_backup.name}")
        shutil.copy(oldest_backup, skill_dir / "SKILL.md")
        return True

    # 如果没有找到备份，尝试从 demo_data 恢复
    demo_backup_dir = Path("/workspace/skill_demo_data/skill_backups")
    if demo_backup_dir.exists():
        backup_name = skill_name.replace("-", "_")
        for backup in demo_backup_dir.glob(f"{backup_name}*"):
            if backup.is_dir():
                backup_file = backup / "SKILL.md"
                if backup_file.exists():
                    print(f"📋 从 demo_data 恢复: {skill_name} ← {backup.name}")
                    shutil.copy(backup_file, skill_dir / "SKILL.md")
                    return True

    print(f"⚠️ 找不到备份: {skill_name}")
    return False


def clear_all_optimization_data():
    """清除所有优化数据"""
    # 清除报告
    reports_dir = Path("/workspace/skills_backups/reports")
    count = 0
    if reports_dir.exists():
        for report_file in reports_dir.glob("skill_opt_*.json"):
            print(f"🗑️ 删除报告: {report_file.name}")
            report_file.unlink()
            count += 1

    # 清除备份文件（保留最早的作为参考）
    skill_backups_dir = Path("/workspace/skills_backups")
    for skill_backups in skill_backups_dir.glob("*.md"):
        # 跳过最早的备份
        skill_name = skill_backups.stem.split("_v")[0]
        all_backups = list(skill_backups_dir.glob(f"{skill_name}_v*.md"))
        if len(all_backups) > 1:
            all_backups.sort(key=lambda x: int(x.stem.split("_v")[-1]))
            for backup in all_backups[1:]:
                print(f"🗑️ 删除备份: {backup.name}")
                backup.unlink()
                count += 1

    return count


def main():
    print("=" * 80)
    print("恢复所有技能到原始状态")
    print("=" * 80)

    # 需要恢复的技能列表
    skills_to_restore = [
        "keyword-check",
        "spam_detect",
        "blackmarket_detect",
        "download_risk_check",
        "pii_scan",
    ]

    restored_count = 0
    for skill_name in skills_to_restore:
        if restore_skill_from_backup(skill_name, Path("/workspace/skill_demo_data/skill_backups")):
            restored_count += 1

    # 清除优化数据
    cleared_count = clear_all_optimization_data()

    print("\n" + "=" * 80)
    print(f"✅ 恢复完成: {restored_count} 个技能, 清除 {cleared_count} 个文件")
    print("=" * 80)


if __name__ == "__main__":
    main()
