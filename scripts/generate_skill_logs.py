#!/usr/bin/env python3
"""
最简单的Skill调用日志生成器
"""
import json
import time
import uuid
import sys
import os
from pathlib import Path
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'backend'))

# 测试内容
TEST_CONTENTS = [
    # 广告类
    {"text": "加微信 abc123 了解赚钱项目", "type": "advertisement"},
    {"text": "扫码进群领红包", "type": "advertisement"},
    {"text": "代理加盟日赚500", "type": "advertisement"},
    {"text": "下载APP注册送现金", "type": "advertisement"},
    {"text": "联系VX xyz888 咨询详情", "type": "advertisement"},

    # 辱骂类
    {"text": "你这个傻逼废物，滚远点", "type": "harassment"},
    {"text": "你妈死了", "type": "harassment"},
    {"text": "这个脑残东西", "type": "harassment"},

    # 隐私类
    {"text": "他的身份证号是123456789012345678", "type": "privacy"},
    {"text": "告诉我你的银行卡号和密码", "type": "privacy"},
    {"text": "网上能查到你的家庭住址和身份证号", "type": "privacy"},

    # 正常内容
    {"text": "今天天气真好，适合去公园散步", "type": "normal"},
    {"text": "我去上班了", "type": "normal"},
    {"text": "晚上吃什么？", "type": "normal"},
    {"text": "最近在看什么书？", "type": "normal"},
    {"text": "这个电影很好看", "type": "normal"},
    {"text": "健身打卡第10天", "type": "normal"},

    # 变体关键词
    {"text": "加v联系我", "type": "advertisement"},
    {"text": "wx我吧", "type": "advertisement"},
    {"text": "扣扣群聊", "type": "advertisement"},
    {"text": "薇信扫码", "type": "advertisement"},
]


def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║  🚀 Skill 路由日志生成器                            ║
║  模拟Skill路由过程，生成日志，累计使用量                   ║
╚══════════════════════════════════════════════════════════╝
    """)

    # 初始化 BaseAgent
    from agent_moderation.agents.base import BaseAgent
    from agent_moderation.skill_registry import get_skill_registry

    agent = BaseAgent("demo_agent")

    # 列出可用Skills
    registry = get_skill_registry()
    skills = registry.list_skills()
    skill_names = [s.name for s in skills]
    print(f"✅ 已加载 {len(skill_names)} 个Skills")
    print(f"   Skills: {', '.join(skill_names[:5])}...")

    print(f"\n📊 准备处理 {len(TEST_CONTENTS)} 条内容")

    results = []
    skill_usage = {}

    start_time = time.time()

    for i, content in enumerate(TEST_CONTENTS, 1):
        content_id = str(uuid.uuid4())[:8]
        text = content["text"]

        print(f"\n{'━' * 60}")
        print(f"🔄 [{i}/{len(TEST_CONTENTS)}] {text[:50]}...")
        print(f"    ID: {content_id}")

        # 触发Skill路由和日志记录
        skill_context = agent._load_relevant_skills(
            query=text,
            content_type='text',
            max_inject=3,
            content_id=content_id
        )

        # 获取最后一条日志
        logs = getattr(agent, '_skill_routing_log', [])
        if logs:
            last_log = logs[-1]
            selected = last_log.get('selected_skills', [])
            filtered = last_log.get('filtered_skills', [])
            ranked = last_log.get('ranked_skills', [])

            print(f"    Filtered: {filtered}")
            print(f"    Ranked:   {ranked}")
            print(f"    Selected: {selected}")

            results.append({
                "content_id": content_id,
                "text": text,
                "type": content["type"],
                "filtered": filtered,
                "ranked": ranked,
                "selected": selected,
            })

            for skill in selected:
                skill_usage[skill] = skill_usage.get(skill, 0) + 1
        else:
            print(f"    ⚠️  无路由日志")
            results.append({
                "content_id": content_id,
                "text": text,
                "type": content["type"],
                "selected": [],
            })

    elapsed = time.time() - start_time

    print(f"\n\n{'=' * 60}")
    print("📊 生成完成统计")
    print('=' * 60)
    print(f"总处理数: {len(results)}")
    print(f"总耗时: {elapsed:.1f}s")
    print(f"平均每条: {elapsed / len(results):.2f}s")
    print(f"总日志数: {len(getattr(agent, '_skill_routing_log', []))}")
    print(f"\nSkill 使用统计:")

    if skill_usage:
        for skill, count in sorted(skill_usage.items(), key=lambda x: -x[1]):
            print(f"   {skill:20s} : {count:3d} 次")
    else:
        print("    (无)")

    # 保存结果
    output_dir = Path("/workspace/skill_demo_data")
    output_dir.mkdir(exist_ok=True)

    # 1. 保存流量结果
    output_file = output_dir / "skill_traffic_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "total_count": len(results),
            "elapsed_seconds": elapsed,
            "skill_usage": skill_usage,
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 结果已保存: {output_file}")

    # 2. 保存所有路由日志（JSONL格式）
    logs_file = output_dir / "skill_routing_logs.jsonl"
    all_logs = getattr(agent, '_skill_routing_log', [])
    with open(logs_file, "w", encoding="utf-8") as f:
        for log in all_logs:
            f.write(json.dumps(log, ensure_ascii=False) + "\n")
    print(f"✅ 路由日志已保存: {logs_file} ({len(all_logs)} 条)")

    # 3. 保存模拟数据库记录
    db_records = []
    for log in all_logs:
        db_records.append({
            "content_id": log.get("content_id"),
            "agent": log.get("agent"),
            "query": log.get("query"),
            "content_type": log.get("content_type"),
            "filtered_skills": log.get("filtered_skills", []),
            "ranked_skills": log.get("ranked_skills", []),
            "selected_skills": log.get("selected_skills", []),
            "timestamp": datetime.now().isoformat(),
        })

    db_file = output_dir / "skill_routing_db_records.json"
    with open(db_file, "w", encoding="utf-8") as f:
        json.dump(db_records, f, ensure_ascii=False, indent=2)
    print(f"✅ 模拟DB记录已保存: {db_file}")

    print("""

╔══════════════════════════════════════════════════════════╗
║  🎉 Skill 调用流量生成完成！                           ║
║                                                            ║
║  📊 数据统计:                                          ║
║     - 处理内容: {len(results):3d} 条                        ║
║     - 路由日志: {len(all_logs):3d} 条                        ║
║     - Skill类型: {len(skill_usage):2d} 种                        ║
║                                                            ║
║  📁 数据文件:                                          ║
║     - skill_traffic_results.json: 汇总结果                  ║
║     - skill_routing_logs.jsonl: 原始日志 (可导入数据库)     ║
║     - skill_routing_db_records.json: 模拟数据库记录         ║
║                                                            ║
║  现在可以访问前端 Skill 管理页面查看使用统计了！             ║
╚══════════════════════════════════════════════════════════╝
    """.format(len(results), len(all_logs), len(skill_usage)))


if __name__ == "__main__":
    main()
