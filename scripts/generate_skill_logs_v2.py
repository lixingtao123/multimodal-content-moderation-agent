#!/usr/bin/env python3
"""
Skill调用日志生成器 v2
使用TextAgent来生成流量
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

    # 辱骂类
    {"text": "你这个傻逼废物，滚远点", "type": "harassment"},
    {"text": "你妈死了", "type": "harassment"},
    {"text": "这个脑残东西", "type": "harassment"},

    # 隐私类
    {"text": "他的身份证号是123456789012345678", "type": "privacy"},
    {"text": "告诉我你的银行卡号和密码", "type": "privacy"},

    # 正常内容
    {"text": "今天天气真好，适合去公园散步", "type": "normal"},
    {"text": "我去上班了", "type": "normal"},
    {"text": "晚上吃什么？", "type": "normal"},

    # 变体关键词
    {"text": "加v联系我", "type": "advertisement"},
    {"text": "wx我吧", "type": "advertisement"},
    {"text": "扣扣群聊", "type": "advertisement"},

    # 更多
    {"text": "加微信聊一聊", "type": "advertisement"},
    {"text": "加我wx", "type": "advertisement"},
    {"text": "联系vx", "type": "advertisement"},
    {"text": "加q群123456", "type": "advertisement"},
    {"text": "加微信123456789", "type": "advertisement"},
]


def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║  🚀 Skill 路由日志生成器 v2                             ║
║  使用TextAgent生成真实流量                               ║
╚══════════════════════════════════════════════════════════╝
    """)

    from agent_moderation.agents.text_agent import TextAgent
    from agent_moderation.skill_registry import get_skill_registry

    agent = TextAgent()

    registry = get_skill_registry()
    skills = registry.list_skills()
    skill_names = [s.name for s in skills]
    print(f"✅ 已加载 {len(skill_names)} 个Skills")
    print(f"   Skills: {', '.join(skill_names[:8])}...")

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

        # 直接调用 _load_relevant_skills 来触发路由和日志
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

    elapsed = time.time() - start_time

    print(f"\n\n{'=' * 60}")
    print("📊 生成完成统计")
    print('=' * 60)
    print(f"总处理数: {len(results)}")
    print(f"总耗时: {elapsed:.1f}s")
    print(f"总日志数: {len(getattr(agent, '_skill_routing_log', []))}")
    print(f"\nSkill 使用统计:")

    if skill_usage:
        for skill, count in sorted(skill_usage.items(), key=lambda x: -x[1]):
            print(f"   {skill:20s} : {count:3d} 次")
    else:
        print("    (无)")

    output_dir = Path("/workspace/skill_demo_data")
    output_dir.mkdir(exist_ok=True)

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

    logs_file = output_dir / "skill_routing_logs.jsonl"
    all_logs = getattr(agent, '_skill_routing_log', [])
    with open(logs_file, "w", encoding="utf-8") as f:
        for log in all_logs:
            f.write(json.dumps(log, ensure_ascii=False) + "\n")
    print(f"✅ 路由日志已保存: {logs_file} ({len(all_logs)} 条)")

    print("""

╔══════════════════════════════════════════════════════════╗
║  🎉 Skill 调用流量生成完成！                           ║
║                                                            ║
║  📊 数据统计:                                          ║
║     - 处理内容: {len_results:3d} 条                         ║
║     - 路由日志: {len_logs:3d} 条                         ║
║     - Skill类型: {len_usage:2d} 种                         ║
║                                                            ║
║  现在可以访问前端 Skill 管理页面查看使用统计了！             ║
╚══════════════════════════════════════════════════════════╝
    """.format(len_results=len(results), len_logs=len(all_logs), len_usage=len(skill_usage)))


if __name__ == "__main__":
    main()
