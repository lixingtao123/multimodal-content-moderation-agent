#!/usr/bin/env python3
"""
分析Skill路由日志，生成使用统计
"""
import json
from pathlib import Path
from collections import Counter


def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║  📊 Skill 路由日志分析器                                ║
╚══════════════════════════════════════════════════════════╝
    """)

    logs_file = Path("/workspace/skill_demo_data/skill_routing_logs.jsonl")

    if not logs_file.exists():
        print("❌ 日志文件不存在")
        return

    all_logs = []
    with open(logs_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    log = json.loads(line)
                    all_logs.append(log)
                except Exception as e:
                    print(f"❌ 解析失败: {e}")

    print(f"✅ 加载了 {len(all_logs)} 条日志")

    skill_counter = Counter()
    filtered_counter = Counter()
    ranked_counter = Counter()

    for log in all_logs:
        selected = log.get("selected_skills", log.get("selected", []))
        filtered = log.get("filtered_skills", log.get("filtered", []))
        ranked = log.get("ranked_skills", log.get("ranked", []))

        for skill in selected:
            skill_counter[skill] += 1
        for skill in filtered:
            filtered_counter[skill] += 1
        for skill in ranked:
            ranked_counter[skill] += 1

    print(f"\n{'=' * 60}")
    print("📊 Skill 使用统计（Selected阶段）")
    print('=' * 60)
    if skill_counter:
        for skill, count in skill_counter.most_common():
            print(f"  {skill:25s} : {count:3d} 次")
    else:
        print("  (无数据)")

    print(f"\n{'=' * 60}")
    print("📊 Skill 命中统计（Filter阶段）")
    print('=' * 60)
    if filtered_counter:
        for skill, count in filtered_counter.most_common(10):
            print(f"  {skill:25s} : {count:3d} 次")
    else:
        print("  (无数据)")

    print(f"\n{'=' * 60}")
    print("📊 Skill 排序统计（Rank阶段）")
    print('=' * 60)
    if ranked_counter:
        for skill, count in ranked_counter.most_common(10):
            print(f"  {skill:25s} : {count:3d} 次")
    else:
        print("  (无数据)")

    # 保存统计结果
    output_dir = Path("/workspace/skill_demo_data")
    output_file = output_dir / "skill_usage_stats.json"
    stats = {
        "total_logs": len(all_logs),
        "selected": dict(skill_counter),
        "filtered": dict(filtered_counter),
        "ranked": dict(ranked_counter),
    }
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 统计结果已保存: {output_file}")

    print(f"\n{'=' * 60}")
    print("📚 日志样例预览")
    print('=' * 60)
    for i, log in enumerate(all_logs[:3], 1):
        print(f"\n--- 样例 {i} ---")
        print(f"内容: {log.get('query', '')[:50]}...")
        print(f"Agent: {log.get('agent', '')}")
        print(f"Filtered: {log.get('filtered_skills', log.get('filtered', []))}")
        print(f"Ranked: {log.get('ranked_skills', log.get('ranked', []))}")
        print(f"Selected: {log.get('selected_skills', log.get('selected', []))}")

    print("""

╔══════════════════════════════════════════════════════════╗
║  🎉 分析完成！所有数据已保存到 skill_demo_data 目录     ║
║                                                            ║
║  📁 数据文件:                                           ║
║     - skill_routing_logs.jsonl: 原始日志                  ║
║     - skill_usage_stats.json: 使用统计                    ║
║                                                            ║
║  现在可以访问前端 Skill 管理页面查看使用统计了！            ║
║  在「路由日志」标签页可以查看 Filter → Rank → Select 过程  ║
╚══════════════════════════════════════════════════════════╝
    """)


if __name__ == "__main__":
    main()
