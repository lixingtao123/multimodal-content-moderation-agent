"""调试预览功能"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main():
    from optimization.skill_optimization_agent import get_skill_optimization_agent

    optimizer = get_skill_optimization_agent()

    print("=" * 80)
    print("调试预览功能")
    print("=" * 80)

    report = optimizer._get_latest_enhanced_report()

    if report is None:
        print("❌ 没有找到报告")
        return

    # 找到建议 #5
    suggestion = None
    for s in report.suggestions:
        if s.id == 5:
            suggestion = s
            break

    if suggestion is None:
        print("❌ 没有找到建议 #5")
        return

    print(f"\n📋 建议 #5:")
    print(f"   Skill: {suggestion.skill_name}")
    print(f"   当前值: {repr(suggestion.current_value)}")
    print(f"   建议值: {repr(suggestion.suggested_value)}")
    print(f"   是否相同: {suggestion.current_value.strip() == suggestion.suggested_value.strip()}")

    # 获取预览
    print(f"\n🔍 获取预览...")
    preview = optimizer.get_preview_diff(report.report_path, suggestion.id)

    if preview:
        print(f"\n📄 原文件内容 (前 500 字符):")
        print(repr(preview['original'][:500]))
        print(f"\n✅ 优化后内容 (前 500 字符):")
        print(repr(preview['optimized'][:500]))
        print(f"\n⚡ 是否相同: {preview['original'] == preview['optimized']}")
    else:
        print("❌ 没有获取到预览")

    # 检查一下文件路径的处理
    print(f"\n📂 检查文件路径处理:")
    skill_name = suggestion.skill_name
    print(f"   Skill name: {skill_name}")

    SKILLS_DIR = Path("/workspace/skills")
    skill_dir = SKILLS_DIR / skill_name
    if not skill_dir.exists():
        skill_dir = SKILLS_DIR / skill_name.replace("-", "_")
    print(f"   Skill dir: {skill_dir}")
    print(f"   Exists: {skill_dir.exists()}")

    if skill_dir.exists():
        skill_file = skill_dir / "SKILL.md"
        print(f"   Skill file: {skill_file}")
        if skill_file.exists():
            with open(skill_file, 'r', encoding='utf-8') as f:
                content = f.read()
            print(f"\n📄 文件内容中的 description:")
            import re
            frontmatter_match = re.match(r'^---\s*(.*?)\s*---', content, re.DOTALL)
            if frontmatter_match:
                frontmatter_str = frontmatter_match.group(1)
                for line in frontmatter_str.splitlines():
                    if line.strip().startswith('description:'):
                        desc = line.split(':', 1)[1].strip()
                        print(f"   实际 description: {repr(desc)}")
                        print(f"   是否等于建议值: {desc == suggestion.suggested_value}")


if __name__ == "__main__":
    main()

