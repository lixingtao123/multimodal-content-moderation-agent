"""
MCP 工具级访问控制 v1.0

定义 Agent→Tool 的访问策略，实现最小权限原则。
每个 Agent 只能调用其 Profile 中授权的工具。

策略定义:
  AGENT_TOOL_PROFILES = {
      "text_agent":       ["keyword_check", "history_search", ...],
      "image_agent":      ["image_hash", "history_search", ...],
      ...
  }

使用方式:
  from mcp_servers.access_control import AccessController

  acl = AccessController()
  if acl.is_allowed("text_agent", "keyword_check"):
      await client.call_tool("keyword_check", ...)
"""
import logging
from typing import Dict, List, Set

logger = logging.getLogger(__name__)

# Agent → 允许的工具列表
AGENT_TOOL_PROFILES: Dict[str, List[str]] = {
    "text_agent": [
        "keyword_check",
        "history_search",
        "adversarial_detect",
        "url_check",
        "content_dedup",
        "regex_rule_check",
    ],
    "image_agent": [
        "image_hash",
        "history_search",
        "content_dedup",
    ],
    "audio_agent": [
        "keyword_check",
        "history_search",
        "content_dedup",
    ],
    "video_agent": [
        "image_hash",
        "history_search",
        "content_dedup",
        "keyword_check",
    ],
    "blackhat_agent": [
        "account_risk_check",
        "adversarial_detect",
        "regex_rule_check",
    ],
    "react_agent": [
        "keyword_check",
        "history_search",
        "account_risk_check",
    ],
    "supervisor": [],
    "risk_agent": [],
    "debate_panel": [],
    "planner": [
        "keyword_check",
        "history_search",
    ],
}

# 构建反向查找索引: tool → [allowed_agents]
TOOL_AGENT_INDEX: Dict[str, Set[str]] = {}
for _agent, _tools in AGENT_TOOL_PROFILES.items():
    for _tool in _tools:
        if _tool not in TOOL_AGENT_INDEX:
            TOOL_AGENT_INDEX[_tool] = set()
        TOOL_AGENT_INDEX[_tool].add(_agent)


class AccessController:
    """MCP 工具访问控制器"""

    def __init__(self, profiles: Dict[str, List[str]] = None):
        self._profiles = profiles or AGENT_TOOL_PROFILES
        self._rebuild_index()

    def _rebuild_index(self):
        """重建 tool → agents 反向索引"""
        self._tool_agents: Dict[str, Set[str]] = {}
        for agent, tools in self._profiles.items():
            for tool in tools:
                if tool not in self._tool_agents:
                    self._tool_agents[tool] = set()
                self._tool_agents[tool].add(agent)

    def is_allowed(self, agent_type: str, tool_name: str) -> bool:
        """
        检查指定 Agent 是否有权调用指定工具。

        Args:
            agent_type: Agent 类型 (如 "text_agent")
            tool_name: 工具名称 (如 "keyword_check")

        Returns:
            True 如果允许调用
        """
        if agent_type not in self._profiles:
            logger.warning(f"Unknown agent type: {agent_type}, denying access")
            return False

        allowed_tools = self._profiles[agent_type]
        is_ok = tool_name in allowed_tools
        if not is_ok:
            logger.warning(
                f"Access denied: agent={agent_type} tool={tool_name} "
                f"(allowed={allowed_tools})"
            )
        return is_ok

    def get_allowed_tools(self, agent_type: str) -> List[str]:
        """获取指定 Agent 可调用的工具列表"""
        return list(self._profiles.get(agent_type, []))

    def get_tool_agents(self, tool_name: str) -> List[str]:
        """获取有权调用指定工具的 Agent 列表"""
        return list(self._tool_agents.get(tool_name, set()))

    def filter_tools(self, agent_type: str, tools: List[dict]) -> List[dict]:
        """
        过滤工具列表，仅返回指定 Agent 有权使用的工具。
        用于 tools/list 端点返回个性化工具清单。
        """
        allowed = set(self._profiles.get(agent_type, []))
        return [t for t in tools if t.get("name") in allowed]

    def add_profile(self, agent_type: str, tools: List[str]):
        """动态添加 Agent Profile"""
        self._profiles[agent_type] = tools
        self._rebuild_index()
        logger.info(f"Added ACL profile: {agent_type} → {tools}")

    def remove_profile(self, agent_type: str):
        """移除 Agent Profile"""
        self._profiles.pop(agent_type, None)
        self._rebuild_index()


# 全局单例
_access_controller: AccessController = None


def get_access_controller() -> AccessController:
    global _access_controller
    if _access_controller is None:
        _access_controller = AccessController()
    return _access_controller
