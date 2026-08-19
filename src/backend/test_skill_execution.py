"""
真正的验证测试：LLM 是否按照 Skill 指导执行？

验证方案：
1. 对照测试：同样的输入，测试"有Skill" vs "无Skill"
2. 验证点：
   - LLM 是否调用 Skill 推荐的工具
   - LLM 的决策逻辑是否受 Skill 影响
   - LLM 的输出是否体现 Skill 知识
"""
import sys
import json
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Tuple

sys.path.insert(0, str(Path(__file__).parent))


# 专门用于测试的 Skill - 我们可以控制它的内容
TEST_SKILL_CONTENT = """
[SKILL CONTEXT: test-skill v1.0.0]

## test-skill

### Overview
这是一个测试专用的 Skill，用于验证 LLM 是否真正按 Skill 指导执行。

### Special Instructions (关键验证点)
1. **必须调用** `keyword_check` 工具，即使文本看起来没问题
2. **必须检查** 以下关键词：测试、验证、Skill、LLM
3. **如果发现以上任意关键词**，必须将 violation_type 标记为 "test_detected"
4. **必须在 reasoning 中明确提到** "按照 test-skill 指导"
5. **置信度必须是 0.95**

### Example
输入: "这是一个测试文本"
输出: {"violation_type": "test_detected", "confidence": 0.95, "reasoning": "按照 test-skill 指导，检测到关键词: 测试"}
[/SKILL CONTEXT]
"""


class SkillExecutionValidator:
    """Skill 执行验证器"""

    def __init__(self):
        # 先获取基础组件
        from agent_moderation.skill_registry import get_skill_registry
        from agent_moderation.skill_router import get_skill_router
        from common.api_clients import get_deepseek_client, get_deepseek_model

        self.registry = get_skill_registry()
        self.router = get_skill_router()
        self.llm_client = get_deepseek_client()
        self.model = get_deepseek_model()

        # 测试用的文本
        self.test_texts = [
            "这是一个测试文本，用来验证 Skill",
            "正常文本，看起来没问题",
            "加微信赚钱，日赚千元",  # 触发 spam_detect
        ]

    def _build_base_prompt(self, text: str) -> str:
        """构建基础 prompt（不含 Skill）"""
        return f"""你是内容安全审核专家。请分析以下文本是否违规。

审核维度：
- 政治敏感
- 色情低俗
- 暴力恐怖
- 广告引流
- 辱骂骚扰

文本：
{text}

请只返回JSON：
{{
    "violation_type": "none|politics|porn|violence|advertisement|harassment",
    "confidence": 0.0-1.0,
    "reasoning": "完整的推理过程",
    "tools_to_call": ["keyword_check|history_search|rag_retrieve|..."]
}}
"""

    def _build_prompt_with_skill(self, text: str, skill_content: str) -> str:
        """构建包含 Skill 的 prompt"""
        base = self._build_base_prompt(text)
        return f"{base}\n\n{skill_content}"

    async def test_without_skill(self, text: str) -> Dict[str, Any]:
        """测试：无 Skill 情况"""
        print(f"\n{'='*60}")
        print(f"测试: 无 Skill")
        print(f"输入: {text[:60]}...")
        print(f"{'='*60}")

        prompt = self._build_base_prompt(text)

        response = await self.llm_client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=800,
        )

        result_text = response.choices[0].message.content
        result = self._parse_result(result_text)
        result["raw_output"] = result_text

        print(f"输出: violation_type={result.get('violation_type')}, "
              f"confidence={result.get('confidence')}")
        print(f"推理: {result.get('reasoning', '')[:100]}...")
        print(f"工具调用: {result.get('tools_to_call', [])}")

        return result

    async def test_with_skill(self, text: str) -> Dict[str, Any]:
        """测试：有 Skill 情况"""
        print(f"\n{'='*60}")
        print(f"测试: 有 Skill")
        print(f"输入: {text[:60]}...")
        print(f"{'='*60}")

        # 使用我们的测试专用 Skill
        prompt = self._build_prompt_with_skill(text, TEST_SKILL_CONTENT)

        response = await self.llm_client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=800,
        )

        result_text = response.choices[0].message.content
        result = self._parse_result(result_text)
        result["raw_output"] = result_text

        print(f"输出: violation_type={result.get('violation_type')}, "
              f"confidence={result.get('confidence')}")
        print(f"推理: {result.get('reasoning', '')[:100]}...")
        print(f"工具调用: {result.get('tools_to_call', [])}")

        return result

    def _parse_result(self, text: str) -> Dict[str, Any]:
        """解析 LLM 输出"""
        try:
            # 先尝试提取 JSON
            json_start = text.find("{")
            json_end = text.rfind("}")
            if json_start >= 0 and json_end > json_start:
                json_str = text[json_start:json_end+1]
                return json.loads(json_str)
        except Exception:
            pass
        # 如果解析失败，返回原始文本
        return {"raw": text}

    def _check_skill_followed(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """检查 Skill 是否被遵循"""
        checks = {
            "calls_keyword_check": False,
            "uses_test_violation_type": False,
            "mentions_skill_in_reasoning": False,
            "confidence_95": False,
        }

        tools = result.get("tools_to_call", [])
        if isinstance(tools, list) and any("keyword" in str(t).lower() for t in tools):
            checks["calls_keyword_check"] = True

        vt = str(result.get("violation_type", "")).lower()
        if "test" in vt:
            checks["uses_test_violation_type"] = True

        reasoning = str(result.get("reasoning", "")).lower()
        if "test-skill" in reasoning or "skill" in reasoning:
            checks["mentions_skill_in_reasoning"] = True

        conf = result.get("confidence", 0)
        if conf == 0.95 or (isinstance(conf, str) and "0.95" in conf):
            checks["confidence_95"] = True

        checks["total_passed"] = sum(1 for v in checks.values() if v)

        return checks

    async def run_comparison_test(self, text: str) -> Dict[str, Any]:
        """运行对照测试"""
        print(f"\n{'#'*60}")
        print(f"对照测试: {text[:50]}...")
        print(f"{'#'*60}")

        # 无 Skill 测试
        result_without = await self.test_without_skill(text)

        # 有 Skill 测试
        result_with = await self.test_with_skill(text)

        # 检查 Skill 是否被遵循
        skill_checks = self._check_skill_followed(result_with)

        # 对比结果
        comparison = {
            "text": text,
            "without_skill": {
                "violation_type": result_without.get("violation_type"),
                "confidence": result_without.get("confidence"),
            },
            "with_skill": {
                "violation_type": result_with.get("violation_type"),
                "confidence": result_with.get("confidence"),
            },
            "skill_checks": skill_checks,
            "skill_followed": skill_checks["total_passed"] >= 3,
        }

        print(f"\n{'▓'*60}")
        print(f"结果对比:")
        print(f"  无Skill: {result_without.get('violation_type')} @ {result_without.get('confidence')}")
        print(f"  有Skill: {result_with.get('violation_type')} @ {result_with.get('confidence')}")
        print(f"  Skill遵循度: {skill_checks['total_passed']}/4")
        print(f"    - 调用keyword_check: {'✅' if skill_checks['calls_keyword_check'] else '❌'}")
        print(f"    - 使用test_detected: {'✅' if skill_checks['uses_test_violation_type'] else '❌'}")
        print(f"    - 提到Skill: {'✅' if skill_checks['mentions_skill_in_reasoning'] else '❌'}")
        print(f"    - 置信度0.95: {'✅' if skill_checks['confidence_95'] else '❌'}")
        print(f"{'▓'*60}")

        return comparison

    async def test_text_agent_integration(self) -> Dict[str, Any]:
        """测试 TextAgent 的完整 Skill 集成"""
        print(f"\n{'*'*60}")
        print(f"测试: TextAgent 完整 Skill 集成")
        print(f"{'*'*60}")

        from agent_moderation.agents.text_agent import TextAgent
        from agent_moderation.state import ModerationState

        agent = TextAgent()

        # 创建测试 state
        state: ModerationState = {
            "content_id": "test-content-001",
            "content_type": "text",
            "content": {"text": "这是一个测试文本，验证Skill是否工作"},
            "messages": [],
        }

        # 我们需要检查 TextAgent 是否实际使用了 Skill
        # 通过查看 BaseAgent 的 _skill_routing_log 来验证
        # 先清空日志
        if hasattr(agent, "_skill_routing_log"):
            agent._skill_routing_log = []

        # 执行处理
        result_state = await agent.process(state)

        # 检查路由日志
        skill_used = False
        if hasattr(agent, "_skill_routing_log") and agent._skill_routing_log:
            log_entry = agent._skill_routing_log[-1]
            print(f"\n✅ Skill 路由日志:")
            print(f"   Filtered: {log_entry.get('filtered')}")
            print(f"   Ranked: {log_entry.get('ranked')}")
            print(f"   Selected: {log_entry.get('selected')}")
            if log_entry.get("selected"):
                skill_used = True

        text_result = result_state.get("text_result", {})
        print(f"\n✅ TextAgent 结果:")
        print(f"   Violation: {text_result.get('violation_type')}")
        print(f"   Confidence: {text_result.get('confidence')}")

        return {
            "skill_used": skill_used,
            "routing_log": agent._skill_routing_log if hasattr(agent, "_skill_routing_log") else [],
            "text_result": text_result,
        }

    async def run_all_tests(self) -> Dict[str, Any]:
        """运行所有测试"""
        results = {
            "comparison_tests": [],
            "text_agent_test": None,
            "summary": {},
        }

        print("\n" + "="*80)
        print("开始 Skill 执行验证测试")
        print("="*80)

        # 对照测试
        for text in self.test_texts:
            comparison = await self.run_comparison_test(text)
            results["comparison_tests"].append(comparison)

        # TextAgent 集成测试
        results["text_agent_test"] = await self.test_text_agent_integration()

        # 总结
        total_comparison = len(results["comparison_tests"])
        passed_comparison = sum(1 for t in results["comparison_tests"] if t["skill_followed"])

        results["summary"] = {
            "total_comparison_tests": total_comparison,
            "passed_comparison_tests": passed_comparison,
            "text_agent_skill_used": results["text_agent_test"]["skill_used"],
            "overall_success": passed_comparison >= 2 and results["text_agent_test"]["skill_used"],
        }

        return results


async def main():
    print("\n" + "="*80)
    print("LLM Skill 执行验证测试")
    print("="*80)

    validator = SkillExecutionValidator()
    results = await validator.run_all_tests()

    # 输出最终总结
    print("\n" + "="*80)
    print("最终验证总结")
    print("="*80)

    summary = results["summary"]
    print(f"\n对照测试: {summary['passed_comparison_tests']}/{summary['total_comparison_tests']} 通过")

    if results["text_agent_test"]["skill_used"]:
        print(f"\n✅ TextAgent 真正使用了 Skill (有路由日志)")
        for entry in results["text_agent_test"]["routing_log"]:
            print(f"   → 召回的 Skill: {entry.get('selected')}")
    else:
        print(f"\n❌ TextAgent 没有使用 Skill (无路由日志)")

    if summary["overall_success"]:
        print(f"\n🎉 验证通过: LLM 确实按照 Skill 指导执行！")
    else:
        print(f"\n⚠️ 验证失败: LLM 没有充分按照 Skill 指导执行")

    print("\n" + "="*80)
    return results


if __name__ == "__main__":
    asyncio.run(main())
