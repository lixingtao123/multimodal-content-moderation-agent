#!/usr/bin/env python3
"""
生成真实审核流量，触发Skill调用，累计使用量
"""
import asyncio
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
    # 广告类（应该触发 keyword_check）
    {"text": "加微信 abc123 了解赚钱项目", "type": "advertisement"},
    {"text": "扫码进群领红包", "type": "advertisement"},
    {"text": "代理加盟日赚500", "type": "advertisement"},
    {"text": "下载APP注册送现金", "type": "advertisement"},
    {"text": "联系VX xyz888 咨询详情", "type": "advertisement"},

    # 辱骂类（应该触发 keyword_check）
    {"text": "你这个傻逼废物，滚远点", "type": "harassment"},
    {"text": "你妈死了", "type": "harassment"},
    {"text": "这个脑残东西", "type": "harassment"},

    # 隐私类（应该触发 pii_scan）
    {"text": "他的身份证号是123456789012345678", "type": "privacy"},
    {"text": "告诉我你的银行卡号和密码", "type": "privacy"},
    {"text": "网上能查到你的家庭住址和身份证号", "type": "privacy"},

    # 正常内容（应该触发 history_search）
    {"text": "今天天气真好，适合去公园散步", "type": "normal"},
    {"text": "我去上班了", "type": "normal"},
    {"text": "晚上吃什么？", "type": "normal"},
    {"text": "最近在看什么书？", "type": "normal"},
    {"text": "这个电影很好看", "type": "normal"},
    {"text": "健身打卡第10天", "type": "normal"},

    # 变体关键词（测试优化效果）
    {"text": "加v联系我", "type": "advertisement"},
    {"text": "wx我吧", "type": "advertisement"},
    {"text": "扣扣群聊", "type": "advertisement"},
    {"text": "薇信扫码", "type": "advertisement"},

    # 虚假信息
    {"text": "转发到5个群就能免费领千元礼包", "type": "false_info"},
    {"text": "听说某地要地震了", "type": "false_info"},

    # 暴力
    {"text": "我要砍死你", "type": "violence"},
    {"text": "杀他全家", "type": "violence"},

    # 歧视
    {"text": "某省的人都是骗子，别信他们", "type": "discrimination"},

    # 更多广告变体
    {"text": "加微信聊一聊", "type": "advertisement"},
    {"text": "加我wx", "type": "advertisement"},
    {"text": "联系vx", "type": "advertisement"},
    {"text": "加q群123456", "type": "advertisement"},
    {"text": "加微信123456789", "type": "advertisement"},

    # 更多敏感词变体
    {"text": "加微信了解详情", "type": "advertisement"},
    {"text": "扫码加微信", "type": "advertisement"},
    {"text": "联系方式电话13800138000", "type": "advertisement"},
    {"text": "关注公众号领福利", "type": "advertisement"},
    {"text": "代理加盟，轻松赚钱", "type": "advertisement"},

    # 更多辱骂变体
    {"text": "你这个废物东西", "type": "harassment"},
    {"text": "傻逼玩意，滚", "type": "harassment"},
    {"text": "你妈是脑残吗", "type": "harassment"},
]


def create_mock_state(content_id: str, text: str, content_type: str = "text") -> dict:
    """创建模拟 ModerationState"""
    return {
        "content_id": content_id,
        "content": {"text": text},
        "content_type": content_type,
        "status": "pending",
        "progress": 0.0,
    }


async def simulate_single_moderation(text: str, content_type: str = "text") -> dict:
    """模拟单次审核，触发Skill调用"""
    from agent_moderation.agents.text_agent import TextAgent
    from agent_moderation.state import ModerationState

    content_id = str(uuid.uuid4())[:8]

    print(f"\n{'=' * 60}")
    print(f"📝 审核内容: {text[:50]}...")
    print(f"🆔 ContentID: {content_id}")

    state = create_mock_state(content_id, text, content_type)

    try:
        agent = TextAgent()
        result_state = await agent.process(state)

        selected_skills = []
        if hasattr(agent, "_skill_routing_log") and len(agent._skill_routing_log) > 0:
            last_log = agent._skill_routing_log[-1]
            selected_skills = last_log.get("selected_skills", [])
            filtered = last_log.get("filtered_skills", [])
            ranked = last_log.get("ranked_skills", [])
            print(f"   Filtered: {filtered}")
            print(f"   Ranked:   {ranked}")
            print(f"   Selected: {selected_skills}")

        text_result = result_state.get("text_result", {})
        print(f"   违规类型: {text_result.get('violation_type', 'none')}")
        print(f"   置信度: {text_result.get('confidence', 0):.2f}")
        print(f"   风险分: {text_result.get('risk_score', 0):.2f}")

        return {
            "content_id": content_id,
            "text": text,
            "content_type": content_type,
            "selected_skills": selected_skills,
            "violation_type": text_result.get("violation_type", "none"),
            "confidence": text_result.get("confidence", 0),
            "risk_score": text_result.get("risk_score", 0),
        }

    except Exception as e:
        print(f"   ❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return {
            "content_id": content_id,
            "text": text,
            "error": str(e),
            "selected_skills": [],
        }


async def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║  🚀 Skill 调用流量生成器                                  ║
║  生成真实审核案例，触发Skill路由，累计使用量                ║
╚══════════════════════════════════════════════════════════╝
    """)

    print(f"\n📊 准备审核 {len(TEST_CONTENTS)} 条内容")

    results = []
    skill_usage = {}

    start_time = time.time()

    for i, content in enumerate(TEST_CONTENTS, 1):
        print(f"\n{'━' * 60}")
        print(f"🔄 [{i}/{len(TEST_CONTENTS)}] 处理中...")

        result = await simulate_single_moderation(content["text"], content["text"])
        results.append(result)

        for skill in result["selected_skills"]:
            skill_usage[skill] = skill_usage.get(skill, 0) + 1

        # 避免触发API限流
        if i % 5 == 0 and i < len(TEST_CONTENTS):
            print("   ⏸️  节流中...")
            await asyncio.sleep(0.5)

    elapsed = time.time() - start_time

    print(f"\n\n{'=' * 60}")
    print("📊 生成完成统计")
    print('=' * 60)
    print(f"总审核数: {len(results)}")
    print(f"总耗时: {elapsed:.1f}s")
    print(f"平均每条: {elapsed / len(results):.2f}s")
    print(f"\nSkill 使用统计:")
    for skill, count in sorted(skill_usage.items(), key=lambda x: -x[1]):
        print(f"   {skill:20s} : {count:3d} 次")

    # 保存结果
    output_dir = Path("/workspace/skill_demo_data")
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / "generated_traffic_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "total_count": len(results),
            "elapsed_seconds": elapsed,
            "skill_usage": skill_usage,
            "results": results,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 结果已保存: {output_file}")

    print("""
╔══════════════════════════════════════════════════════════╗
║  🎉 Skill 调用流量生成完成！                              ║
║  现在可以访问前端 Skill 管理页面查看使用统计                ║
╚══════════════════════════════════════════════════════════╝
    """)


if __name__ == "__main__":
    asyncio.run(main())
