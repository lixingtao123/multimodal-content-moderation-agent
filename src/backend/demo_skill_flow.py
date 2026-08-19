#!/usr/bin/env python3
"""
演示 Skill 使用流程演示

展示：
1. Skill 召回
2. Skill 加载
3. Skill 注入到 System Prompt
4. 路由日志记录
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))


async def demo_skill_flow():
    """演示完整的 Skill 流程"""
    print("="*80)
    print("Skill 使用流程演示")
    print("="*80)

    # 1. 初始化组件
    print("\n[1/5] 初始化组件...")
    from agent_moderation.skill_registry import get_skill_registry
    from agent_moderation.skill_router import get_skill_router

    registry = get_skill_registry()
    router = get_skill_router()

    print(f"   ✅ SkillRegistry: 加载了 {len(registry.list_skills())} 个 Skill")
    print(f"   ✅ SkillRouter: 已初始化")

    # 2. 测试内容
    test_content = "加微信赚钱，日赚3000，扫码进群"
    print(f"\n[2/5] 测试内容: \"{test_content}\"")

    # 3. Skill 路由
    print("\n[3/5] Skill 三级路由...")
    result = router.route(
        query=test_content,
        tags={'text', 'rag', 'retrieval'},
        max_inject=3
    )

    print(f"   Filter 粗筛: {result.get('filtered', [])}")
    print(f"   Rank 精排: {result.get('ranked', [])}")
    print(f"   Select 注入: {result.get('selected', [])}")

    # 4. 加载 Skill 内容
    print("\n[4/5] 加载 Skill 内容...")
    skill_names = result.get('selected', [])
    skill_context = registry.get_skill_context(skill_names[0]) if skill_names else ''

    if skill_context:
        print(f"   ✅ 加载了 {len(skill_names)} 个 Skill")
        print("\nSkill 内容示例（spam_detect）:")
        print("-"*80)
        print(skill_context[:500] if skill_context else "(无)")
        print("-"*80)

    # 5. 演示在 Agent 中的使用
    print("\n[5/5] 演示在 Agent 中的使用...")
    from agent_moderation.agents.text_agent import TextAgent

    agent = TextAgent()

    # 清空之前的日志
    agent._skill_routing_log = []

    # 调用 Skill 加载
    skill_context = agent._load_relevant_skills(
        query=test_content,
        content_type='text',
        max_inject=3,
        content_id='demo-001'
    )

    print(f"   ✅ Skill 上下文长度: {len(skill_context)} 字符")

    # 检查日志
    if agent._skill_routing_log:
        log = agent._skill_routing_log[-1]
        print(f"\n   ✅ 路由日志已记录:")
        print(f"      content_id: {log.get('content_id')}")
        print(f"      agent: {log.get('agent')}")
        print(f"      selected: {log.get('selected')}")

    # 总结
    print("\n" + "="*80)
    print("流程演示完成!")
    print("="*80)

    print("""
总结：
╔══════════════════════════════════════════════════════════════╗
║  LLM 如何按照 Skill 指导执行：                             ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  1. 内容输入 → SkillRouter 召回相关 Skill                  ║
║     ↓                                                       ║
║  2. SkillRegistry 加载 Skill 完整内容                        ║
║     ↓                                                       ║
║  3. Skill 内容拼接到 System Prompt                         ║
║     ↓                                                       ║
║  4. LLM 收到带 Skill 的 System Prompt                   ║
║     ↓                                                       ║
║  5. LLM 按照 Skill 中的指导执行:                              ║
║     - 使用推荐的工具                                         ║
║     - 遵循判断标准                                          ║
║     - 参考示例输出格式                                          ║
║                                                              ║
║  验证方式：                                                 ║
║  - 路由日志记录每次 Skill 使用                              ║
║  - 对照测试验证输出差异                                      ║
║  - 端到端测试完整流程                                        ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
    """)

    return {
        "skill_recall_worked": len(result.get('selected', [])) > 0,
        "skill_loaded": len(skill_context) > 0,
        "log_recorded": len(agent._skill_routing_log) > 0,
    }


if __name__ == "__main__":
    import asyncio
    asyncio.run(demo_skill_flow())
