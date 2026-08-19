"""
单元测试 — KeywordCheckTool
"""
import pytest
import asyncio
from mcp_servers.tools.keyword_check import KeywordCheckTool


@pytest.fixture
def checker():
    return KeywordCheckTool()


def _run(coro):
    """Helper: run async in sync test"""
    return asyncio.run(coro)


class TestKeywordCheck:
    def test_empty_text(self, checker):
        """空文本应返回无违规"""
        result = _run(checker.execute(""))
        assert result.has_violation is False
        assert result.count == 0

    def test_normal_text(self, checker):
        """正常文本不应触发敏感词"""
        result = _run(checker.execute("今天天气很好，适合出去玩"))
        assert result.has_violation is False

    def test_single_keyword(self, checker):
        """单个敏感词应被检测到"""
        result = _run(checker.execute("这是一段包含色情的内容"))
        assert result.has_violation is True
        assert result.count >= 1

    def test_multiple_keywords(self, checker):
        """多个敏感词应全部检测"""
        result = _run(checker.execute("色情暴力恐怖内容"))
        assert result.has_violation is True
        assert result.count >= 3

    def test_advertisement_detection(self, checker):
        """广告类敏感词检测"""
        result = _run(checker.execute("加微信兼职赚钱，扫码联系"))
        assert result.has_violation is True
        assert result.count >= 2

    def test_fraud_detection(self, checker):
        """诈骗类敏感词检测"""
        result = _run(checker.execute("恭喜中奖，请转账汇款到银行卡号"))
        assert result.has_violation is True
        assert result.count >= 2

    def test_clean_text_no_false_positive(self, checker):
        """正常文本不应有误报"""
        result = _run(checker.execute("学习编程需要耐心和实践"))
        assert result.has_violation is False

    def test_match_positions(self, checker):
        """匹配位置应正确"""
        result = _run(checker.execute("前面文字加微信后面文字"))
        assert result.has_violation is True
        if result.matches:
            match = result.matches[0]
            assert "keyword" in match
            assert "position" in match
