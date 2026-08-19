#!/usr/bin/env python3
"""
生成更多Skill路由日志
丰富数据量，覆盖更多场景
"""
import json
import time
import uuid
import sys
import os
from pathlib import Path
from datetime import datetime
from collections import Counter

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'backend'))

# 更多测试内容
MORE_TEST_CONTENTS = [
    # 广告类（更多变体）
    {"text": "加微信 a1b2c3 轻松赚钱", "type": "advertisement"},
    {"text": "扫码进微信群领福利", "type": "advertisement"},
    {"text": "代理项目日入千元", "type": "advertisement"},
    {"text": "下载APP注册送红包", "type": "advertisement"},
    {"text": "联系微信 xyz999 咨询", "type": "advertisement"},
    {"text": "加我微信了解详情", "type": "advertisement"},
    {"text": "扫码加入我们", "type": "advertisement"},
    {"text": "微信联系我", "type": "advertisement"},
    {"text": "VX: abc123", "type": "advertisement"},
    {"text": "WX: 123456", "type": "advertisement"},

    # 辱骂类（更多变体）
    {"text": "你这个废物，滚", "type": "harassment"},
    {"text": "你妈有病吧", "type": "harassment"},
    {"text": "你这个脑残", "type": "harassment"},
    {"text": "傻逼啊你", "type": "harassment"},
    {"text": "你是不是傻", "type": "harassment"},
    {"text": "你妈死了滚", "type": "harassment"},
    {"text": "废物一个", "type": "harassment"},
    {"text": "你他妈闭嘴", "type": "harassment"},
    {"text": "傻逼玩意儿", "type": "harassment"},
    {"text": "你真是个脑残", "type": "harassment"},

    # 隐私类（更多变体）
    {"text": "身份证号是 110101199001011234", "type": "privacy"},
    {"text": "银行卡号是 6222021234567890", "type": "privacy"},
    {"text": "手机号是 13800138000", "type": "privacy"},
    {"text": "我家住北京市朝阳区xxx街道", "type": "privacy"},
    {"text": "告诉我你密码", "type": "privacy"},
    {"text": "你身份证号多少", "type": "privacy"},
    {"text": "银行卡密码是什么", "type": "privacy"},
    {"text": "个人信息泄露了", "type": "privacy"},

    # 正常内容（更多样化）
    {"text": "今天天气不错", "type": "normal"},
    {"text": "我要去上班了", "type": "normal"},
    {"text": "晚上吃火锅吧", "type": "normal"},
    {"text": "最近在看什么剧", "type": "normal"},
    {"text": "这部电影很好看", "type": "normal"},
    {"text": "健身打卡第15天", "type": "normal"},
    {"text": "周末去爬山", "type": "normal"},
    {"text": "学习Python编程", "type": "normal"},
    {"text": "这个代码有bug", "type": "normal"},
    {"text": "明天开会", "type": "normal"},

    # 变体关键词
    {"text": "加v聊", "type": "advertisement"},
    {"text": "wx联系", "type": "advertisement"},
    {"text": "扣扣加我", "type": "advertisement"},
    {"text": "微信扫码", "type": "advertisement"},
    {"text": "vx聊", "type": "advertisement"},
    {"text": "加微", "type": "advertisement"},

    # 暴力类
    {"text": "我要杀了你", "type": "violence"},
    {"text": "打死你", "type": "violence"},
    {"text": "砍死你全家", "type": "violence"},
    {"text": "你等着", "type": "violence"},
    {"text": "我弄死你", "type": "violence"},

    # 色情类
    {"text": "裸聊吗", "type": "porn"},
    {"text": "约炮吗", "type": "porn"},
    {"text": "找小姐", "type": "porn"},

    # 诈骗类
    {"text": "中奖了500万", "type": "scam"},
    {"text": "我是银行客服", "type": "scam"},
    {"text": "你的账户有风险", "type": "scam"},
    {"text": "我是公安局的", "type": "scam"},

    # 更多正常内容
    {"text": "今天真开心", "type": "normal"},
    {"text": "工作顺利吗", "type": "normal"},
    {"text": "周末去看电影", "type": "normal"},
    {"text": "我想养宠物", "type": "normal"},
    {"text": "今天饭很好吃", "type": "normal"},
    {"text": "我要去健身房", "type": "normal"},
    {"text": "买东西去", "type": "normal"},
    {"text": "取快递", "type": "normal"},
    {"text": "快递到了", "type": "normal"},
    {"text": "帮我拿一下", "type": "normal"},
]


def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║  🚀 Skill 路由日志 - 批量生成 v3                         ║
║  生成更多数据，丰富统计场景                                  ║
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

    print(f"\n📊 准备处理 {len(MORE_TEST_CONTENTS)} 条内容")

    results = []
    skill_usage = Counter()

    start_time = time.time()

    for i, content in enumerate(MORE_TEST_CONTENTS, 1):
        content_id = str(uuid.uuid4())[:8]
        text = content["text"]

        print(f"\n{'━' * 60}")
        print(f"🔄 [{i}/{len(MORE_TEST_CONTENTS)}] {text[:50]}...")

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

            print(f"    ID: {content_id}")
            print(f"    Selected: {selected}")

            results.append({
                "content_id": content_id,
                "text": text,
                "type": content["type"],
                "selected": selected,
            })

            for skill in selected:
                skill_usage[skill] += 1

    elapsed = time.time() - start_time

    print(f"\n\n{'=' * 60}")
    print("📊 生成完成统计")
    print('=' * 60)
    print(f"总处理数: {len(results)}")
    print(f"总耗时: {elapsed:.1f}s")
    print(f"总日志数: {len(getattr(agent, '_skill_routing_log', []))}")
    print(f"\nSkill 使用统计:")

    if skill_usage:
        for skill, count in skill_usage.most_common():
            print(f"   {skill:25s} : {count:3d} 次")
    else:
        print("    (无)")

    # 保存结果
    output_dir = Path("/workspace/skill_demo_data")
    output_dir.mkdir(exist_ok=True)

    # 1. 保存流量结果
    output_file = output_dir / "more_traffic_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "total_count": len(results),
            "elapsed_seconds": elapsed,
            "skill_usage": dict(skill_usage),
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 结果已保存: {output_file}")

    # 2. 追加保存路由日志
    logs_file = output_dir / "skill_routing_logs.jsonl"
    all_logs = getattr(agent, '_skill_routing_log', [])

    # 如果文件已存在，追加写入
    mode = "a" if logs_file.exists() else "w"
    with open(logs_file, mode, encoding="utf-8") as f:
        for log in all_logs[-len(results):]:  # 只追加新生成的
            f.write(json.dumps(log, ensure_ascii=False) + "\n")
    print(f"✅ 路由日志已追加: {logs_file}")

    # 3. 统计总数据
    total_logs = 0
    if logs_file.exists():
        with open(logs_file, "r", encoding="utf-8") as f:
            total_logs = sum(1 for line in f)

    print("""

╔══════════════════════════════════════════════════════════╗
║  🎉 Skill 调用流量批量生成完成！                          ║
║                                                            ║
║  📊 数据统计:                                           ║
║     - 本次处理: {len_results:3d} 条                       ║
║     - 总日志数: {total_logs:3d} 条                       ║
║     - Skill类型: {len_usage:2d} 种                       ║
║                                                            ║
║  📁 数据文件:                                           ║
║     - more_traffic_results.json: 本次结果                  ║
║     - skill_routing_logs.jsonl: 完整日志 (累计)           ║
║                                                            ║
║  现在可以访问前端 Skill 管理页面查看使用统计了！            ║
╚══════════════════════════════════════════════════════════╝
    """.format(len_results=len(results), total_logs=total_logs, len_usage=len(skill_usage)))


if __name__ == "__main__":
    main()
