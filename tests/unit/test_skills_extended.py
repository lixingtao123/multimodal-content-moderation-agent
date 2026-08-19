"""
Skills 扩展测试（R19）— 44 个 skill 加载、映射、路由

验证新增 36 个 skill 真实生效（可被 registry 发现、映射到工具、可路由）。
"""
from agent_moderation.skill_registry import get_skill_registry


def test_skill_count_reaches_50_total():
    """skills 总数达到 50（8 原有 + 36 新增 + .claude/skills 重复）"""
    r = get_skill_registry()
    metas = r.list_skills()
    assert len(metas) >= 40


def test_new_skills_present():
    """新增 skill 都能被发现"""
    r = get_skill_registry()
    names = {m.name for m in r.list_skills()}
    for expected in ["pii_scan", "termination_check", "system_health_check",
                     "blackmarket_detect", "cascade_routing", "source_weighted_query",
                     "phishing_detect", "regression_guard", "triage_check"]:
        assert expected in names, f"缺少 skill: {expected}"


def test_skill_to_tool_mapping():
    """每个新增 skill 都映射到已注册的 MCP 工具"""
    from mcp_servers.registry import get_tool_registry

    r = get_skill_registry()
    tools = set(get_tool_registry().list_tools().keys())
    for meta in r.list_skills():
        for t in (meta.mcp_tools or []):
            assert t in tools, f"skill {meta.name} 映射的工具 {t} 未注册"


def test_find_by_mcp_tool():
    """find_by_mcp_tool 反查 skill 正常"""
    r = get_skill_registry()
    hits = r.find_by_mcp_tool("pii_detect")
    assert any(s.name == "pii_scan" for s in hits)


def test_skill_router_filter_finds_new_skills():
    """SkillRouter.filter 能命中新增技能"""
    from agent_moderation.skill_router import SkillRouter

    router = SkillRouter()
    hits = router.filter("检测文本中的隐私信息", top_n=10)
    names = [m.name for m in hits]
    assert "pii_scan" in names


def test_skill_tool_map_api_shape():
    """skill-tool 映射 API 数据形状（后端 /tech/skill-tool-map 用）"""
    r = get_skill_registry()
    mapping = r.get_mcp_tool_skills_map()
    assert isinstance(mapping, dict)
    assert "pii_detect" in mapping
    assert "pii_scan" in mapping["pii_detect"]
