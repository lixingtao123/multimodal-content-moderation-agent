"""展示优化后 Skill 文件的变更"""
from pathlib import Path


def main():
    skills_dir = Path("/workspace/skills")
    backups_dir = Path("/workspace/skills_backups")

    print("=" * 80)
    print("优化后 Skill 文件变更检查")
    print("=" * 80)

    # 检查哪些 Skill 有备份
    backup_skills = set()
    for backup in backups_dir.glob("*_v*.md"):
        parts = backup.stem.split("_")
        skill_name = "_".join(parts[:-2])
        if skill_name:
            backup_skills.add(skill_name)

    print(f"\n📋 已备份的 Skill: {sorted(backup_skills)}")

    # 检查实际修改的文件
    print("\n" + "=" * 80)
    print("实际 Skill 文件修改检查")
    print("=" * 80)

    # 检查可能被修改的 Skill
    check_skills = [
        "keyword-check", "keyword_check",
        "spam-detect", "spam_detect",
        "blackmarket-detect", "blackmarket_detect",
        "download-risk-check", "download_risk_check"
    ]

    for skill_name in check_skills:
        skill_dir = skills_dir / skill_name
        if not skill_dir.exists():
            continue

        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        print(f"\n📂 {skill_name}")
        print("  " + "-" * 70)

        with open(skill_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # 只展示 frontmatter 部分
        import re
        frontmatch = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
        if frontmatch:
            print(f"  --- Frontmatter ---")
            print(frontmatch.group(1).rstrip())
            print("  ---")

            # 检查是否有新增的触发词
            if "triggers:" in frontmatch.group(1):
                print("  ✅ 发现触发词定义")
            if "description:" in frontmatch.group(1):
                print("  ✅ 发现描述定义")


if __name__ == "__main__":
    main()
