"""
Pytest 配置文件 — 共享 fixtures
"""
import os
import sys
import pytest

# 确保 backend 代码在 sys.path 中
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_SRC = os.path.join(PROJECT_ROOT, "src", "backend")
sys.path.insert(0, BACKEND_SRC)

# 使用 .env.example 避免真实 API 调用
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("QWEN_VL_API_KEY", "test-key")
os.environ.setdefault("QWEN_VL_MODEL", "qwen3-vl-plus")
os.environ.setdefault("REDIS_URL", "redis://localhost:16379/0")
os.environ.setdefault("CHROMA_URL", "http://localhost:18001")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:15432/moderation")


@pytest.fixture
def sample_text_normal():
    """正常文本样本"""
    return "今天天气真好，适合去公园散步"


@pytest.fixture
def sample_text_violation():
    """违规文本样本"""
    return "加微信转账汇款，中奖了请联系我们"


@pytest.fixture
def sample_text_adversarial():
    """对抗样本 — 同音字替换"""
    return "加V信zhuan账，中jiang了请联系我们"


@pytest.fixture
def mock_moderation_state():
    """模拟审核状态"""
    return {
        "content_id": "test_001",
        "content_type": "text",
        "content": {"text": "测试内容"},
        "account_id": None,
        "messages": [],
        "text_result": None,
        "image_result": None,
        "audio_result": None,
        "video_result": None,
        "blackhat_result": None,
        "final_risk": None,
        "final_decision": "",
    }
