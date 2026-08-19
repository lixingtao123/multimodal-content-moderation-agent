"""
单元测试 — 违规类型统一枚举（D3，R1）
"""
from agent_moderation.violation_types import (
    OUTSAFE_CATEGORY_MAP,
    OUTSAFE_COVERED_TYPES,
    VIOLATION_CN,
    VIOLATION_TYPES,
    is_valid_violation_type,
    map_outsafe_category,
)


class TestViolationTypes:
    def test_enum_has_13_types(self):
        """枚举共 13 类（含 none）"""
        assert len(VIOLATION_TYPES) == 13

    def test_enum_contains_existing_7(self):
        """现有 7 类必须保留"""
        for vt in ["none", "politics", "porn", "violence", "false_info",
                   "harassment", "advertisement"]:
            assert vt in VIOLATION_TYPES

    def test_enum_contains_new_6(self):
        """新增 6 类（D3 需求）"""
        for vt in ["privacy", "discrimination", "crime", "ethics", "health", "copyright"]:
            assert vt in VIOLATION_TYPES

    def test_no_duplicates(self):
        """无重复项"""
        assert len(set(VIOLATION_TYPES)) == len(VIOLATION_TYPES)

    def test_cn_map_covers_all_types(self):
        """中文映射覆盖全部 13 类，且 none 映射为正常"""
        assert set(VIOLATION_CN.keys()) == set(VIOLATION_TYPES)
        assert VIOLATION_CN["none"] == "正常"

    def test_outsafe_map_covers_9_dirs(self):
        """OutSafe 9 类目录全部有映射"""
        assert len(OUTSAFE_CATEGORY_MAP) == 9

    def test_outsafe_map_values_are_valid(self):
        """映射目标全部是合法枚举"""
        for vt in OUTSAFE_CATEGORY_MAP.values():
            assert is_valid_violation_type(vt)

    def test_outsafe_covered_matches_violation_subset(self):
        """OutSafe 覆盖的 9 类应全部是违规类（不含 none）"""
        assert "none" not in OUTSAFE_COVERED_TYPES

    def test_map_outsafe_known_dir(self):
        """带数字前缀的目录名正确映射"""
        assert map_outsafe_category("1Privacy_and_Property") == "privacy"
        assert map_outsafe_category("5Violence_and_Hatred") == "violence"

    def test_map_outsafe_unknown_returns_none(self):
        """未知目录返回 none"""
        assert map_outsafe_category("Unknown_Dir") == "none"

    def test_is_valid_violation_type(self):
        """校验函数"""
        assert is_valid_violation_type("privacy")
        assert is_valid_violation_type("none")
        assert not is_valid_violation_type("not_a_type")
