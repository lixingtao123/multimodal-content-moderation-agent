#!/usr/bin/env python3
"""
轻量级Skill调用流量生成器
直接使用Skill Router 生成路由日志
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

    # 更多广告变体
    {"text": "加微信聊一聊", "type": "advertisement"},
    {"text": "加我wx", "type": "advertisement"},
    {"text": "联系vx", "type": "advertisement"},
    {"text": "加q群123456", "type": "advertisement"},
    {"text": "加微信123456789", "type": "advertisement"},
    {"text": "加微信了解详情", "type": "advertisement"},
    {"text": "扫码加微信", "type": "advertisement"},
    {"text": "联系方式电话13800138000", "type": "advertisement"},
    {"text": "关注公众号领福利", "type": "advertisement"},
    {"text": "代理加盟，轻松赚钱", "type": "advertisement"},
    {"text": "你这个废物东西", "type": "harassment"},
    {"text": "傻逼玩意，滚", "type": "harassment"},
    {"text": "你妈是脑残吗", "type": "harassment"},
    {"text": "转发到5个群就能免费领千元礼包", "type": "false_info"},
    {"text": "我要砍死你", "type": "violence"},
    {"text": "杀他全家", "type": "violence"},
    {"text": "某省的人都是骗子，别信他们", "type": "discrimination"},
]


class SimpleTrafficGenerator:
    def __init__(self):
        self.skill_registry = None
        self.skill_router = None
        self._init_components()

    def _init_components(self):
        try:
            from agent_moderation.skill_registry import get_skill_registry
            from agent_moderation.skill_router import get_skill_router
            from agent_moderation.agents.base import BaseAgent

            self.skill_registry = get_skill_registry()
            self.skill_router = get_skill_router()

            self.agent = BaseAgent("traffic_generator")

            skills = self.skill_registry.list_skills()
            print(f"✅ 已加载 {len(skills)} 个Skill")
        except Exception as e:
            print(f"⚠️  组件初始化失败: {e}")
            import traceback
            traceback.print_exc()

    def generate_single(self, text: str) -> dict:
        content_id = str(uuid.uuid4())[:8]

        print(f"\n{'=' * 60}")
        print(f"📝 [{content_id}] {text[:50]}...")

        try:
            result = self.agent._load_relevant_skills(
                query=text,
                content_type='text',
                max_inject=3,
                content_id=content_id
            )

            logs = self.agent._skill_routing_log
            if logs:
                last_log = logs[-1]
                print(f"    Filtered: {last_log.get('filtered_skills', [])}")
                print(f"    Ranked:   {last_log.get('ranked_skills', [])}")
                print(f"    Selected: {last_log.get('selected_skills', [])}")

                return {
                    "content_id": content_id,
                    "text": text,
                    "filtered": last_log.get('filtered_skills', []),
                    "ranked": last_log.get('ranked_skills', []),
                    "selected": last_log.get('selected_skills', []),
                }
            else:
                print("    ⚠️  无日志")
                return {
                    "content_id": content_id,
                    "text": text,
                    "selected": [],
                }
        except Exception as e:
            print(f"    ❌ 错误: {e}")
            return {
                "content_id": content_id,
                "text": text,
                "error": str(e),
                "selected": [],
            }


def main():
    print("""
╔══════════════════════════════════════════════════════════╗
║  🚀 Skill 调用流量生成器（轻量版）                      ║
║  直接调用Skill路由，生成日志，累计使用量                        ║
╚══════════════════════════════════════════════════════════╝
    """)

    print(f"\n📊 准备处理 {len(TEST_CONTENTS)} 条内容")

    generator = SimpleTrafficTrafficGenerator()

    results = []
    skill_usage = {}

    start_time = time.time()

    for i, content in enumerate(TEST_CONTENTS, 1):
        print(f"\n{'━' * 60}")
        print(f"🔄 [{i}/{len(TEST_CONTENTS)}] 处理中...")

        result = generator.generate_single(content["text"])
        results.append(result)

        for skill in result.get("selected", []):
            skill_usage[skill] = skill_usage.get(skill, 0) + 1

    elapsed = time.time() - start_time

    print(f"\n\n{'=' * 60}")
    print("📊 生成完成统计")
    print('=' * 60)
    print(f"总处理数: {len(results)}")
    print(f"总耗时: {elapsed:.1f}s")
    print(f"平均每条: {elapsed / len(results):.2f}s")
    print(f"\nSkill 使用统计:")

    if skill_usage:
        for skill, count in sorted(skill_usage.items(), key=lambda x: -x[1]):
            print(f"   {skill:20s} : {count:3d} 次")
    else:
        print("    (无)")

    output_dir = Path("/workspace/skill_demo_data")
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / "simple_traffic_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "total_count": len(results),
            "elapsed_seconds": elapsed,
            "skill_usage": skill_usage,
            "results": results,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 结果已保存: {output_file}")

    total_logs = len(getattr(generator.agent, '_skill_routing_log', []))
    print(f"\n📝 内存中已保存 {total_logs} 条路由日志")

    print("""
╔══════════════════════════════════════════════════════════╗
║  🎉 Skill 调用流量生成完成！                            ║
╚══════════════════════════════════════════════════════════╝
    """)


if __name__ == "__main__":
    main()
