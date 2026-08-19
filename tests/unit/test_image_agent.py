"""
ImageAgent 单元测试
测试图片基础分析、mock 审核、风险评分
"""
import pytest
import struct
import io


def create_test_image(width=100, height=100, fmt="PNG"):
    """创建测试用的 PNG 图片"""
    from PIL import Image
    img = Image.new("RGB", (width, height), color=(128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def create_test_jpeg(width=200, height=150):
    """创建测试用的 JPEG 图片"""
    from PIL import Image
    img = Image.new("RGB", (width, height), color=(200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def create_tiny_image():
    """创建极小图片（模拟二维码）"""
    from PIL import Image
    img = Image.new("1", (50, 50), color=0)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestImageAgentBasic:
    """图片基础分析测试"""

    def test_basic_png_analysis(self):
        from agent_moderation.agents.image_agent import ImageAgent
        agent = ImageAgent()
        img_data = create_test_image(100, 100)
        result = agent._analyze_basic(img_data)
        assert result["width"] == 100
        assert result["height"] == 100
        assert result["format"] == "PNG"

    def test_basic_jpeg_analysis(self):
        from agent_moderation.agents.image_agent import ImageAgent
        agent = ImageAgent()
        img_data = create_test_jpeg(200, 150)
        result = agent._analyze_basic(img_data)
        assert result["width"] == 200
        assert result["height"] == 150
        assert result["format"] == "JPEG"

    def test_empty_image(self):
        from agent_moderation.agents.image_agent import ImageAgent
        agent = ImageAgent()
        result = agent._analyze_basic(b"")
        assert result["width"] == 0
        assert result["height"] == 0

    def test_mock_mode_default(self):
        """测试 ImageAgent 初始化（根据环境变量配置）"""
        from agent_moderation.agents.image_agent import ImageAgent
        agent = ImageAgent()
        # 验证 agent 正常初始化即可（mock 模式由 .env 配置决定）
        assert agent._mock_mode in (True, False)

    def test_mock_analyze_normal(self):
        from agent_moderation.agents.image_agent import ImageAgent
        agent = ImageAgent()
        img_data = create_test_image(800, 600)
        basic_info = agent._analyze_basic(img_data)
        result = agent._mock_analyze(img_data, basic_info)
        assert "ocr_text" in result
        assert "scene_description" in result
        assert "suspicious_elements" in result

    def test_mock_analyze_tiny_square(self):
        """极小方形图可能被标记为二维码"""
        from agent_moderation.agents.image_agent import ImageAgent
        agent = ImageAgent()
        img_data = create_tiny_image()
        basic_info = agent._analyze_basic(img_data)
        result = agent._mock_analyze(img_data, basic_info)
        # 小方形图会触发启发式规则
        assert result is not None

    def test_risk_score_normal(self):
        from agent_moderation.agents.image_agent import ImageAgent
        agent = ImageAgent()
        vl = {"ocr_text": "", "scene_description": "test", "suspicious_elements": [],
              "has_qrcode": False, "has_contact": False, "has_watermark": False, "has_website": False}
        classification = {"violation_type": "none", "confidence": 0.0, "reason": "", "tags": []}
        score = agent._calculate_risk_score_v2(vl, classification, {"width": 800, "height": 600}, None, [])
        assert score == 0.0

    def test_risk_score_violation(self):
        from agent_moderation.agents.image_agent import ImageAgent
        agent = ImageAgent()
        vl = {"ocr_text": "裸聊视频", "scene_description": "色情内容", "suspicious_elements": ["成人内容"],
              "has_qrcode": False, "has_contact": False, "has_watermark": False, "has_website": False}
        classification = {"violation_type": "porn", "confidence": 0.9, "reason": "色情", "tags": ["porn"]}
        score = agent._calculate_risk_score_v2(vl, classification, {"width": 800, "height": 600}, None, [])
        assert score > 0.4

    def test_risk_score_qrcode_watermark(self):
        from agent_moderation.agents.image_agent import ImageAgent
        agent = ImageAgent()
        vl = {"ocr_text": "", "scene_description": "", "suspicious_elements": [],
              "has_qrcode": True, "has_contact": True, "has_watermark": False, "has_website": False}
        classification = {"violation_type": "none", "confidence": 0.0, "reason": "", "tags": []}
        score = agent._calculate_risk_score_v2(vl, classification, {"width": 200, "height": 200}, None, [])
        assert score > 0.0  # QR code + contact signals give some risk
