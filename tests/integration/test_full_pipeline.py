"""
集成测试 — 多模态审核全链路
不依赖外部服务（Redis/FunASR/API）的纯逻辑测试
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
# 工作流路由测试
# ============================================================
class TestWorkflowRouting:
    """LangGraph 工作流路由测试"""

    def test_route_text(self):
        from agent_moderation.workflows.moderation import route_by_content_type
        state = {"content_type": "text", "content": {}, "messages": []}
        result = route_by_content_type(state)
        assert result == "text_agent"

    def test_route_image(self):
        from agent_moderation.workflows.moderation import route_by_content_type
        state = {"content_type": "image", "content": {}, "messages": []}
        result = route_by_content_type(state)
        assert result == "image_agent"

    def test_route_audio(self):
        from agent_moderation.workflows.moderation import route_by_content_type
        state = {"content_type": "audio", "content": {}, "messages": []}
        result = route_by_content_type(state)
        assert result == "audio_agent"

    def test_route_video(self):
        from agent_moderation.workflows.moderation import route_by_content_type
        state = {"content_type": "video", "content": {}, "messages": []}
        result = route_by_content_type(state)
        assert result == "video_agent"

    def test_route_unknown_defaults_to_text(self):
        from agent_moderation.workflows.moderation import route_by_content_type
        state = {"content_type": "unknown", "content": {}, "messages": []}
        result = route_by_content_type(state)
        assert result == "text_agent"

    def test_workflow_creation(self):
        from agent_moderation.workflows.moderation import create_moderation_workflow
        workflow = create_moderation_workflow()
        assert workflow is not None

    def test_workflow_has_all_nodes(self):
        from agent_moderation.workflows.moderation import create_moderation_workflow
        workflow = create_moderation_workflow()
        nodes = workflow.get_graph().nodes
        # v3.7 起 blackhat 不再独立成节点，由 _aggregate_blackhat_result 聚合；
        # 当前实际节点含 file_agent/planner/react_agent/human_in_loop
        expected = {"supervisor", "text_agent", "image_agent", "audio_agent",
                    "video_agent", "file_agent", "planner", "react_agent",
                    "risk_agent", "human_in_loop"}
        actual_nodes = set(nodes.keys())
        for node in expected:
            assert node in actual_nodes, f"Node '{node}' missing from workflow"


# ============================================================
# 状态管理测试
# ============================================================
class TestModerationState:
    """ModerationState 测试"""

    def test_create_initial_state_text(self):
        from agent_moderation.state import create_initial_state
        state = create_initial_state("test_001", "text", {"text": "你好"})
        assert state["content_id"] == "test_001"
        assert state["content_type"] == "text"
        assert state["content"]["text"] == "你好"
        assert state["messages"] == []
        assert state["final_decision"] == ""

    def test_create_initial_state_image(self):
        from agent_moderation.state import create_initial_state
        img_data = b"fake_image_data" * 10
        state = create_initial_state("test_img", "image", {"image": img_data})
        assert state["content_type"] == "image"
        assert isinstance(state["content"]["image"], bytes)

    def test_create_initial_state_audio(self):
        from agent_moderation.state import create_initial_state
        audio_data = b'\x00' * 1000
        state = create_initial_state("test_audio", "audio", {"audio": audio_data})
        assert state["content_type"] == "audio"

    def test_create_initial_state_video(self):
        from agent_moderation.state import create_initial_state
        video_data = b'\x00\x00\x00\x1c' + b'\x00' * 1000
        state = create_initial_state("test_vid", "video", {"video": video_data})
        assert state["content_type"] == "video"

    def test_create_initial_state_with_account(self):
        from agent_moderation.state import create_initial_state
        state = create_initial_state("test_001", "text", {"text": "你好"}, account_id="user_123")
        assert state["account_id"] == "user_123"

    def test_all_result_fields_empty_by_default(self):
        from agent_moderation.state import create_initial_state
        state = create_initial_state("test_001", "text", {"text": "你好"})
        # v3.x: result 字段初始化为空 dict（避免 .get() 报错），final_risk 为 None
        assert state["text_result"] == {}
        assert state["image_result"] == {}
        assert state["audio_result"] == {}
        assert state["video_result"] == {}
        assert state["blackhat_result"] == {}
        assert state["final_risk"] is None


# ============================================================
# Agent 逻辑测试（不依赖外部服务）
# ============================================================
class TestAgentLogic:
    """Agent 纯逻辑测试（不调 API，不连 Redis）"""

    def test_supervisor_auto_detect_type(self):
        from agent_moderation.agents.supervisor import SupervisorAgent
        agent = SupervisorAgent()
        assert agent._identify_content_type({"text": "hello"}) == "text"
        assert agent._identify_content_type({"image": b"data"}) == "image"
        assert agent._identify_content_type({"audio": b"data"}) == "audio"
        assert agent._identify_content_type({"video": b"data"}) == "video"

    def test_supervisor_preview(self):
        from agent_moderation.agents.supervisor import SupervisorAgent
        agent = SupervisorAgent()
        preview = agent._get_preview({"text": "hello world"}, "text")
        assert "hello world" in preview

        preview = agent._get_preview({"image": b"x" * 100}, "image")
        assert "image" in preview

    def test_text_agent_empty(self):
        from agent_moderation.agents.text_agent import TextAgent
        from agent_moderation.state import create_initial_state
        agent = TextAgent()
        state = create_initial_state("int_empty", "text", {"text": ""})
        result = _run_async(agent.process(state))
        assert result["text_result"]["error"] == "empty text"

    def test_text_agent_risk_score_calculation(self):
        from agent_moderation.agents.text_agent import TextAgent
        agent = TextAgent()

        class FakeKW:
            has_violation = False
            count = 0
            matches = []
        score = agent._calculate_risk_score(
            FakeKW(),
            {"violation_type": "none", "confidence": 0.0, "is_adversarial": False, "tags": []},
            []
        )
        assert score == 0.0

    def test_risk_agent_thresholds(self):
        from agent_moderation.agents.risk_agent import RiskAssessmentAgent
        agent = RiskAssessmentAgent()
        # v3.x: 阈值改为动态加载（策略缓存 + 回退默认值）
        assert agent.reject_threshold == 0.75
        assert agent.review_threshold == 0.35

    def test_risk_agent_calculate_overall(self):
        from agent_moderation.agents.risk_agent import RiskAssessmentAgent
        agent = RiskAssessmentAgent()
        components = {"text": 0.9}
        score = agent._calculate_overall_v2(components, [], "text")
        assert score > 0.7

    def test_risk_agent_no_components(self):
        from agent_moderation.agents.risk_agent import RiskAssessmentAgent
        agent = RiskAssessmentAgent()
        score = agent._calculate_overall_v2({}, [], "text")
        assert score == 0.0

    def test_blackhat_agent_extract_text(self):
        from agent_moderation.agents.blackhat_agent import BlackhatAgent
        from agent_moderation.state import create_initial_state
        agent = BlackhatAgent()

        # 文本类型
        state = create_initial_state("t1", "text", {"text": "测试内容"})
        assert agent._extract_text(state) == "测试内容"

        # 图片（无 OCR 结果）
        state = create_initial_state("t2", "image", {"image": b"data"})
        assert agent._extract_text(state) == ""

        # 语音（有转录结果）
        state = create_initial_state("t3", "audio", {"audio": b"data"})
        state["audio_result"] = {"transcribed_text": "这是音频内容"}
        assert agent._extract_text(state) == "这是音频内容"


# ============================================================
# MCP 工具纯逻辑测试
# ============================================================
class TestMCPTools:
    """MCP 工具纯逻辑测试"""

    def test_keyword_check_violation(self):
        from mcp_servers.tools.keyword_check import KeywordCheckTool
        tool = KeywordCheckTool()
        result = _run_async(tool.execute("加微信免费领取"))
        assert result.has_violation is True
        assert result.count > 0

    def test_keyword_check_clean(self):
        from mcp_servers.tools.keyword_check import KeywordCheckTool
        tool = KeywordCheckTool()
        result = _run_async(tool.execute("今天天气真好"))
        assert result.has_violation is False

    def test_keyword_check_empty(self):
        from mcp_servers.tools.keyword_check import KeywordCheckTool
        tool = KeywordCheckTool()
        result = _run_async(tool.execute(""))
        assert result.has_violation is False
        assert result.count == 0

    def test_tool_registry_has_all_tools(self):
        from mcp_servers.registry import get_tool_registry
        registry = get_tool_registry()
        tools = registry.list_tools()
        assert "keyword_check" in tools
        assert "history_search" in tools
        assert "image_hash" in tools

    def test_image_hash_store_and_detect(self):
        from mcp_servers.tools.image_hash import ImageHashTool
        from PIL import Image
        import io

        tool = ImageHashTool()
        tool.clear_store()

        # 存储一张图片
        buf = io.BytesIO()
        img = Image.new("RGB", (100, 100))
        for x in range(100):
            for y in range(100):
                img.putpixel((x, y), ((x * 3) % 256, (y * 7) % 256, 100))
        img.save(buf, format="PNG")
        img_data = buf.getvalue()

        tool.store_hash("img_001", img_data)

        # 查找相同图片
        result = _run_async(tool.execute(img_data, threshold=5))
        assert result.is_duplicate is True
        assert result.similarity > 0.9


# ============================================================
# Blackhat 集成测试（纯逻辑）
# ============================================================
class TestBlackhatIntegration:
    """黑灰产模块纯逻辑集成测试"""

    def test_pattern_all_types_exist(self):
        from agent_moderation.blackhat.pattern_detector import PatternDetector
        pd = PatternDetector()

        kw = pd.detect_keyword_variants("加薇信")
        assert hasattr(kw, "pattern_type")

        bulk = pd.detect_bulk_generation("免费福利限时特价正规专业联系微信")
        assert hasattr(bulk, "detected")

        phish = pd.detect_phishing("点击链接领取奖金")
        assert hasattr(phish, "confidence")

        ad = pd.detect_advertisement("关注公众号免费咨询")
        assert hasattr(ad, "risk_score")

    def test_adversarial_all_types_exist(self):
        from agent_moderation.blackhat.adversarial_detector import AdversarialDetector
        ad = AdversarialDetector()

        noise = ad.detect_char_noise("test​text")
        assert noise.technique == "CHAR_NOISE"

        split = ad.detect_word_split("这是一个测试句子")
        assert split.technique == "WORD_SPLIT"

        variant = ad.detect_synonym_variant("vjp 商品")
        assert variant.technique == "SYNONYM_VARIANT"

        semantic = ad.detect_semantic_inconsistency("表面文字")
        assert semantic.technique == "SEMANTIC_INCONSISTENCY"

    def test_complex_violation_text(self):
        """综合违规文本全面检测"""
        from agent_moderation.blackhat.pattern_detector import PatternDetector
        from agent_moderation.blackhat.adversarial_detector import AdversarialDetector

        text = "加薇信 xyz123 免～费领取红～包，点击链接 http://fake.com，输入账号密码确认"

        pd = PatternDetector()
        patterns = pd.detect_all(text)
        assert len(patterns) >= 2  # 关键词变体 + 钓鱼

        ad = AdversarialDetector()
        adv_results = ad.detect_all(text)
        assert isinstance(adv_results, list)
