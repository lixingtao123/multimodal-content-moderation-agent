"""
单元测试 — 标签同步（R1 B2）：TEXT_MODERATION_PROMPT 必须与 13 类枚举一致
"""
from agent_moderation.agents.text_agent import TEXT_MODERATION_PROMPT
from agent_moderation.violation_types import VIOLATION_CN, VIOLATION_TYPES


class TestPromptLabelSync:
    def test_prompt_contains_all_12_violation_dims(self):
        """prompt 审核维度覆盖全部 12 个违规类（排除 none）"""
        for vt, cn in VIOLATION_CN.items():
            if vt == "none":
                continue
            assert cn in TEXT_MODERATION_PROMPT, f"维度描述缺失: {vt}({cn})"

    def test_prompt_enum_string_contains_all_types(self):
        """prompt JSON 枚举串包含全部 13 类"""
        # 枚举串是管道符连接
        enum_line = [l for l in TEXT_MODERATION_PROMPT.splitlines() if "violation_type" in l]
        assert enum_line, "找不到 violation_type 枚举行"
        enum_str = enum_line[0]
        for vt in VIOLATION_TYPES:
            assert vt in enum_str, f"枚举串缺失类型: {vt}"

    def test_prompt_no_longer_says_6_dims(self):
        """旧的"对6个审核维度"表述必须已更新"""
        assert "对6个审核维度" not in TEXT_MODERATION_PROMPT
