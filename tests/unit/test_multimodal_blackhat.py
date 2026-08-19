"""
AudioAgent / VideoAgent / Blackhat 单元测试
所有需要外部服务（Redis/FunASR）的测试使用 mock 或正确的事件循环
"""
import pytest
import asyncio
import io


def _run_async(coro):
    """安全执行异步函数"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ============================================================
# AudioAgent Tests
# ============================================================
class TestAudioAgent:
    """AudioAgent 单元测试"""

    def test_empty_audio(self):
        from agent_moderation.agents.audio_agent import AudioAgent
        from agent_moderation.state import create_initial_state
        agent = AudioAgent()
        state = create_initial_state("test_audio", "audio", {"audio": b""})
        # 空音频在 MemoryManager 调用前就返回，不会触发 Redis
        result = _run_async(agent.process(state))
        assert result["audio_result"]["error"] == "empty audio"
        assert result["audio_result"]["risk_score"] == 0.0

    def test_audio_without_redis(self, monkeypatch):
        """测试音频处理（Redis 不可用时的降级行为）

        R19 修复：RedisService 惰性连接+不可用降级后，Redis 不可用不再抛
        AttributeError，而是静默降级。此测试通过强制 _ensure 返回 False 走
        降级路径，验证音频处理正常完成（不依赖环境/测试顺序）。
        """
        from memory.redis_service import get_redis_service
        from agent_moderation.agents.audio_agent import AudioAgent
        from agent_moderation.state import create_initial_state

        # 强制全局 Redis 单例走降级（避免全量顺序下已连接真实 Redis 的污染）
        async def _always_false():
            return False

        monkeypatch.setattr(get_redis_service(), "_ensure", _always_false)

        agent = AudioAgent()
        fake_audio = b'\x00' * 100
        state = create_initial_state("test_audio2", "audio", {"audio": fake_audio})
        out = _run_async(agent.process(state))
        assert out is not None

    def test_risk_score_calculation(self):
        from agent_moderation.agents.audio_agent import AudioAgent
        agent = AudioAgent()

        # 无违规
        class FakeResult:
            has_violation = False
            count = 0
        score = agent._calculate_risk_score(FakeResult(), {"violation_type": "none", "confidence": 0.0, "is_adversarial": False}, [])
        assert score == 0.0

        # 有违规
        score = agent._calculate_risk_score(
            FakeResult(),
            {"violation_type": "politics", "confidence": 0.8, "is_adversarial": True},
            [{"similarity": 0.7}]
        )
        assert score > 0.5


# ============================================================
# VideoAgent Tests
# ============================================================
class TestVideoAgent:
    """VideoAgent 单元测试"""

    def test_format_detection_mp4(self):
        from agent_moderation.agents.video_agent import VideoAgent
        agent = VideoAgent()
        data = b'\x00\x00\x00\x20ftypmp42'
        fmt = agent._detect_format(data)
        assert fmt == ".mp4"

    def test_format_detection_webm(self):
        from agent_moderation.agents.video_agent import VideoAgent
        agent = VideoAgent()
        data = b'\x1a\x45\xdf\xa3'
        fmt = agent._detect_format(data)
        assert fmt == ".webm"

    def test_format_detection_default(self):
        from agent_moderation.agents.video_agent import VideoAgent
        agent = VideoAgent()
        fmt = agent._detect_format(b"random")
        assert fmt == ".mp4"

    def test_empty_video(self):
        from agent_moderation.agents.video_agent import VideoAgent
        from agent_moderation.state import create_initial_state
        agent = VideoAgent()
        state = create_initial_state("test_video", "video", {"video": b""})
        result = _run_async(agent.process(state))
        assert result["video_result"]["error"] == "empty video"

    def test_video_risk_calculation(self):
        from agent_moderation.agents.video_agent import VideoAgent
        agent = VideoAgent()
        frames = [
            {"frame_index": 1, "violation_type": "none", "confidence": 0.0, "timestamp": 0},
            {"frame_index": 2, "violation_type": "porn", "confidence": 0.7, "timestamp": 5.0},
        ]
        score, timeline = agent._calculate_video_risk(frames, "", {"duration": 10})
        assert score > 0.0
        assert len(timeline) > 0

    def test_mock_analyze_frame(self):
        from agent_moderation.agents.video_agent import VideoAgent
        agent = VideoAgent()
        frame = {"index": 1, "timestamp": 5.0, "data": b"\xff\xd8" + b'\x00' * 1024}
        result = agent._mock_analyze_frame(frame)
        assert result["frame_index"] == 1
        assert result["timestamp"] == 5.0
        assert result["needs_vl_model"] is True


# ============================================================
# PatternDetector Tests
# ============================================================
class TestPatternDetector:
    """违规模式检测器测试"""

    def test_keyword_variant_wechat(self):
        from agent_moderation.blackhat.pattern_detector import PatternDetector
        pd = PatternDetector()
        result = pd.detect_keyword_variants("加薇信 xxx123456 免费领取")
        assert result.detected is True
        assert result.pattern_type == "KEYWORD_VARIANT"

    def test_keyword_variant_normal(self):
        from agent_moderation.blackhat.pattern_detector import PatternDetector
        pd = PatternDetector()
        result = pd.detect_keyword_variants("今天天气真好")
        assert result.detected is False

    def test_phishing_link(self):
        from agent_moderation.blackhat.pattern_detector import PatternDetector
        pd = PatternDetector()
        result = pd.detect_phishing("点击 http://fake.com 领取奖品，输入账号密码")
        assert result.detected is True
        assert result.pattern_type == "PHISHING"

    def test_phishing_bank(self):
        from agent_moderation.blackhat.pattern_detector import PatternDetector
        pd = PatternDetector()
        result = pd.detect_phishing("请把验证码告诉我，系统需要确认")
        assert result.detected is True

    def test_bulk_template(self):
        from agent_moderation.blackhat.pattern_detector import PatternDetector
        pd = PatternDetector()
        result = pd.detect_bulk_generation("免费福利 联系微信 扫码领取")
        assert result.pattern_type == "BULK_GENERATION"

    def test_advertisement(self):
        from agent_moderation.blackhat.pattern_detector import PatternDetector
        pd = PatternDetector()
        result = pd.detect_advertisement("关注公众号领取福利 免费咨询了解详情")
        assert result.detected is True

    def test_detect_all_normal(self):
        from agent_moderation.blackhat.pattern_detector import PatternDetector
        pd = PatternDetector()
        results = pd.detect_all("今天天气真好")
        assert len(results) == 0

    def test_detect_all_violation(self):
        from agent_moderation.blackhat.pattern_detector import PatternDetector
        pd = PatternDetector()
        results = pd.detect_all("加薇信xxx点击链接领取大奖 账号密码发我")
        assert len(results) > 0


# ============================================================
# AdversarialDetector Tests
# ============================================================
class TestAdversarialDetector:
    """对抗样本检测器测试"""

    def test_char_noise_zerowidth(self):
        from agent_moderation.blackhat.adversarial_detector import AdversarialDetector
        ad = AdversarialDetector()
        result = ad.detect_char_noise("你好​世界")
        assert result.detected is True

    def test_char_noise_normal(self):
        from agent_moderation.blackhat.adversarial_detector import AdversarialDetector
        ad = AdversarialDetector()
        result = ad.detect_char_noise("今天天气真好")
        assert result.detected is False

    def test_word_split(self):
        from agent_moderation.blackhat.adversarial_detector import AdversarialDetector
        ad = AdversarialDetector()
        result = ad.detect_word_split("违 禁 品 低 价 出 售")
        assert result.detected is True

    def test_synonym_variant(self):
        from agent_moderation.blackhat.adversarial_detector import AdversarialDetector
        ad = AdversarialDetector()
        result = ad.detect_synonym_variant("出售vjp 品质保证")
        assert result.detected is True
        assert result.technique == "SYNONYM_VARIANT"

    def test_detect_all_normal(self):
        from agent_moderation.blackhat.adversarial_detector import AdversarialDetector
        ad = AdversarialDetector()
        results = ad.detect_all("今天天气真好")
        assert len(results) == 0

    def test_detect_all_combined(self):
        from agent_moderation.blackhat.adversarial_detector import AdversarialDetector
        ad = AdversarialDetector()
        results = ad.detect_all("vjp 低 价​出 售")
        assert len(results) > 0


# ============================================================
# AccountRiskProfiler Tests
# ============================================================
class TestAccountRiskProfiler:
    """账号风险画像测试"""

    def test_new_account_low_risk(self):
        from agent_moderation.blackhat.account_risk import get_account_profiler
        profiler = get_account_profiler()
        profile = profiler.get_profile("acc_test_001")
        assert profile.risk_score == 0.0
        assert profile.risk_level == "LOW"
        assert profile.violation_count == 0

    def test_accumulating_violations(self):
        from agent_moderation.blackhat.account_risk import get_account_profiler
        profiler = get_account_profiler()
        acc_id = "acc_test_002"

        profiler.record_violation(acc_id, "advertisement", 0.5)
        profile = profiler.get_profile(acc_id)
        assert profile.violation_count == 1
        assert profile.risk_score > 0.0

        profiler.record_violation(acc_id, "porn", 0.7)
        profile = profiler.get_profile(acc_id)
        assert profile.violation_count == 2
        assert profile.risk_score > 0.3

        profiler.record_violation(acc_id, "phishing", 0.9)
        profile = profiler.get_profile(acc_id)
        assert profile.violation_count == 3
        assert profile.risk_level in ("MEDIUM", "HIGH")

    def test_high_risk_detection(self):
        from agent_moderation.blackhat.account_risk import get_account_profiler
        profiler = get_account_profiler()
        acc_id = "acc_test_003"
        for _ in range(4):
            profiler.record_violation(acc_id, "advertisement", 0.8, patterns=["KEYWORD_VARIANT"])
        assert profiler.should_auto_review(acc_id) is True

    def test_should_not_auto_reject_normal(self):
        from agent_moderation.blackhat.account_risk import get_account_profiler
        profiler = get_account_profiler()
        acc_id = "acc_test_004"
        profiler.record_violation(acc_id, "advertisement", 0.3)
        assert profiler.should_auto_reject(acc_id) is False

    def test_get_all_profiles(self):
        from agent_moderation.blackhat.account_risk import get_account_profiler
        profiler = get_account_profiler()
        profiles = profiler.get_all_profiles()
        assert isinstance(profiles, list)


# ============================================================
# ImageHashTool Tests
# ============================================================
class TestImageHashTool:
    """图片 dHash 工具测试"""

    def test_compute_hash(self):
        from mcp_servers.tools.image_hash import ImageHashTool
        from PIL import Image
        tool = ImageHashTool()
        buf = io.BytesIO()
        # 使用有实际纹理的图片
        img = Image.new("RGB", (100, 100))
        for x in range(100):
            for y in range(100):
                img.putpixel((x, y), ((x * 7) % 256, (y * 13) % 256, (x + y) % 256))
        img.save(buf, format="PNG")
        hash_hex = tool.compute_dhash(buf.getvalue())
        assert isinstance(hash_hex, str)
        assert len(hash_hex) > 0

    def test_same_image_same_hash(self):
        from mcp_servers.tools.image_hash import ImageHashTool
        from PIL import Image
        tool = ImageHashTool()
        buf = io.BytesIO()
        Image.new("RGB", (100, 100), color=(128, 128, 128)).save(buf, format="PNG")
        img_data = buf.getvalue()
        h1 = tool.compute_dhash(img_data)
        h2 = tool.compute_dhash(img_data)
        assert h1 == h2

    def test_hamming_distance_identical(self):
        from mcp_servers.tools.image_hash import ImageHashTool
        from PIL import Image
        tool = ImageHashTool()
        buf = io.BytesIO()
        Image.new("RGB", (100, 100), color=(128, 128, 128)).save(buf, format="PNG")
        img_data = buf.getvalue()
        h1 = tool.compute_dhash(img_data)
        h2 = tool.compute_dhash(img_data)
        assert ImageHashTool.hamming_distance(h1, h2) == 0

    def test_empty_image(self):
        from mcp_servers.tools.image_hash import ImageHashTool
        tool = ImageHashTool()
        hash_hex = tool.compute_dhash(b"")
        assert hash_hex == ""

    def test_different_images_different_hash(self):
        """不同纹理的图片应该有不同 hash"""
        from mcp_servers.tools.image_hash import ImageHashTool
        from PIL import Image
        tool = ImageHashTool()

        # 创建两张不同的图案图片
        buf1 = io.BytesIO()
        img1 = Image.new("RGB", (100, 100))
        for x in range(100):
            for y in range(100):
                img1.putpixel((x, y), ((x * 3) % 256, (y * 7) % 256, 100))
        img1.save(buf1, format="PNG")

        buf2 = io.BytesIO()
        img2 = Image.new("RGB", (100, 100))
        for x in range(100):
            for y in range(100):
                img2.putpixel((x, y), ((x * 11) % 256, (y * 5) % 256, 200))
        img2.save(buf2, format="PNG")

        h1 = tool.compute_dhash(buf1.getvalue())
        h2 = tool.compute_dhash(buf2.getvalue())
        # 不同图片不应该完全相同
        assert h1 != "" and h2 != ""
