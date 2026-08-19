"""
单元测试 — 安全负样本构造器（R1 B4）
"""
from eval.datasets.negative_samples import (
    generate_negative_samples,
    is_safe_negative,
)


class TestNegativeSamples:
    def test_count_at_least_1000(self):
        """负样本量 ≥1000（D3 验收门槛）"""
        samples = generate_negative_samples(count=1200)
        assert len(samples) >= 1000

    def test_no_duplicates(self):
        """无重复样本"""
        samples = generate_negative_samples(count=1200)
        assert len(set(samples)) == len(samples)

    def test_all_safe(self):
        """全部样本不含敏感词"""
        samples = generate_negative_samples(count=1200)
        unsafe = [s for s in samples if not is_safe_negative(s)]
        assert not unsafe, f"发现疑似不安全样本: {unsafe[:5]}"

    def test_reproducible_with_seed(self):
        """相同种子可复现"""
        a = generate_negative_samples(count=200, seed=7)
        b = generate_negative_samples(count=200, seed=7)
        assert a == b

    def test_count_respected(self):
        """count 参数生效"""
        samples = generate_negative_samples(count=100)
        assert len(samples) == 100

    def test_is_safe_negative_detects_sensitive(self):
        """敏感词粗检能识别不安全文本"""
        assert not is_safe_negative("加微信转账返利")
        assert not is_safe_negative("这个人真是傻逼")
        assert is_safe_negative("请问怎么去火车站？")
