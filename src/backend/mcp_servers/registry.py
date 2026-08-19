"""
MCP 工具注册中心 v2.0 — 支持标准 MCP 协议 + 动态工具发现

升级内容:
  - 注册为 MCP Server (JSON-RPC 2.0 协议)
  - tools/list 和 tools/call 方法
  - 工具 Schema 自动生成
  - 渐进式加载 (Skill 系统集成)
"""
from typing import Dict, Optional
from .tools.keyword_check import KeywordCheckTool
from .tools.history_search import HistorySearchTool
from .tools.image_hash import ImageHashTool
from .tools.account_risk import AccountRiskTool
from .tools.adversarial_detect import AdversarialDetectTool
from .tools.url_check import URLCheckTool
from .tools.content_dedup import ContentDedupTool
from .tools.regex_rule import RegexRuleTool


class MCPToolRegistry:
    """MCP 工具注册中心 v2.0"""

    def __init__(self):
        self._tools: Dict[str, object] = {}
        self._tool_schemas: Dict[str, dict] = {}
        self._mcp_server = None
        self._register_defaults()

    def _register_defaults(self):
        """注册默认工具"""
        keyword_tool = KeywordCheckTool()
        history_tool = HistorySearchTool()
        image_hash_tool = ImageHashTool()
        account_risk_tool = AccountRiskTool()
        adversarial_tool = AdversarialDetectTool()
        url_check_tool = URLCheckTool()
        dedup_tool = ContentDedupTool()
        regex_rule_tool = RegexRuleTool()

        self.register("keyword_check", keyword_tool)
        self.register("history_search", history_tool)
        self.register("image_hash", image_hash_tool)
        self.register("account_risk_check", account_risk_tool)
        self.register("adversarial_detect", adversarial_tool)
        self.register("url_check", url_check_tool)
        self.register("content_dedup", dedup_tool)
        self.register("regex_rule_check", regex_rule_tool)

        self._tool_schemas = {
            "keyword_check": {
                "name": "keyword_check",
                "description": "检测文本中的敏感词（本地AC自动机，不调API）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "待检测的文本内容"},
                    },
                    "required": ["text"],
                },
            },
            "history_search": {
                "name": "history_search",
                "description": "检索相似的历史审核案例（BM25+向量混合检索+CrossEncoder重排序）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "检索查询文本"},
                        "top_k": {"type": "integer", "description": "返回结果数", "default": 5},
                        "use_hybrid": {"type": "boolean", "description": "是否使用混合检索", "default": True},
                    },
                    "required": ["query"],
                },
            },
            "image_hash": {
                "name": "image_hash",
                "description": "计算图片dHash值并检测相似图片",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "image_data": {"type": "string", "description": "Base64编码的图片数据"},
                        "threshold": {"type": "integer", "description": "汉明距离阈值", "default": 10},
                    },
                    "required": ["image_data"],
                },
            },
            "account_risk_check": {
                "name": "account_risk_check",
                "description": "查询账号的历史违规记录和风险画像（查PostgreSQL）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "account_id": {"type": "string", "description": "账号ID"},
                    },
                    "required": ["account_id"],
                },
            },
            "adversarial_detect": {
                "name": "adversarial_detect",
                "description": "检测文本中的对抗攻击模式（同音字/字符分割/Unicode混淆/变体词）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "待检测的文本内容"},
                    },
                    "required": ["text"],
                },
            },
            "url_check": {
                "name": "url_check",
                "description": "检测文本中的恶意URL/钓鱼链接/可疑域名",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "待检测的文本内容"},
                    },
                    "required": ["text"],
                },
            },
            "content_dedup": {
                "name": "content_dedup",
                "description": "检查内容是否已审核过（MD5 hash → Redis查重，避免重复审核）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "待检测的文本内容"},
                    },
                    "required": ["text"],
                },
            },
            "regex_rule_check": {
                "name": "regex_rule_check",
                "description": "使用正则规则检测特定格式的违规模式（手机号/银行卡/黑话/自定义规则）",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "待检测的文本内容"},
                        "rule_names": {"type": "array", "items": {"type": "string"}, "description": "指定规则名称列表（可选，默认全部）"},
                    },
                    "required": ["text"],
                },
            },
        }

        # R19: 批量注册 37 个扩展工具（总计 45 个）
        from mcp_servers.registry_extended import register_extended
        self._extended_count = register_extended(self)

        # 初始化 MCP Server
        self._init_mcp_server(keyword_tool, history_tool, image_hash_tool)

    def _init_mcp_server(self, keyword_tool, history_tool, image_hash_tool):
        """初始化 MCP Server — 注册全部 8 个工具（修复旧版仅注册 3 个的 bug）"""
        try:
            from mcp_servers.mcp_server import MCPServer, get_mcp_server
            # 获取或创建 MCPServer 实例
            server = get_mcp_server()
            # 注册默认资源和 prompts（保持向后兼容）
            server.register_default_resources()
            server.register_default_prompts()
            # 从 Registry 动态注册全部 8 个工具（替代旧版 init_mcp_server()）
            server.register_tools_from_registry(self._tools, self._tool_schemas)
            self._mcp_server = server
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"MCP Server init deferred: {e}")

    def register(self, name: str, tool: object, schema: dict = None):
        """注册工具 (含 JSON Schema 定义)"""
        self._tools[name] = tool
        if schema:
            self._tool_schemas[name] = schema

    def get(self, name: str) -> Optional[object]:
        """获取工具实例"""
        return self._tools.get(name)

    def get_schema(self, name: str) -> Optional[dict]:
        """获取工具 JSON Schema（R9·T2 可靠性层使用）"""
        return self._tool_schemas.get(name)

    def get_keyword_check(self) -> KeywordCheckTool:
        return self._tools["keyword_check"]

    def get_history_search(self) -> HistorySearchTool:
        return self._tools["history_search"]

    def get_image_hash(self) -> ImageHashTool:
        return self._tools["image_hash"]

    def get_account_risk(self) -> AccountRiskTool:
        return self._tools["account_risk_check"]

    def get_adversarial_detect(self) -> AdversarialDetectTool:
        return self._tools["adversarial_detect"]

    def get_url_check(self) -> URLCheckTool:
        return self._tools["url_check"]

    def get_content_dedup(self) -> ContentDedupTool:
        return self._tools["content_dedup"]

    def get_regex_rule(self) -> RegexRuleTool:
        return self._tools["regex_rule_check"]

    def list_tools(self) -> Dict[str, str]:
        """列出所有已注册工具 (名称→类名)"""
        return {name: type(tool).__name__ for name, tool in self._tools.items()}

    def get_tool_schemas(self) -> list:
        """获取所有工具的 JSON Schema (符合 MCP tools/list 规范)"""
        return list(self._tool_schemas.values())

    def get_mcp_server(self):
        """获取 MCP Server 实例"""
        return self._mcp_server

    async def call_tool(self, name: str, arguments: dict) -> dict:
        """
        通过 MCP 协议调用工具（reflect 方式，不再硬编码 if/elif 分支）。

        委托给 MCPServer._handle_tools_call() 处理，
        自动利用 _build_tool_handler 构建的泛用 handler。

        Args:
            name: 工具名称
            arguments: 工具参数 (dict，keys 对应 inputSchema properties)

        Returns:
            工具执行结果 (dict)
        """
        if not self._mcp_server:
            raise RuntimeError("MCP Server not initialized")

        # 参数校验：利用 JSON Schema 验证
        schema = self._tool_schemas.get(name, {})
        input_schema = schema.get("inputSchema", {})
        if input_schema:
            required_fields = input_schema.get("required", [])
            missing = [f for f in required_fields if f not in arguments]
            if missing:
                raise ValueError(f"Missing required params for '{name}': {missing}")

        # 委托给 MCPServer 的通用 dispatch
        result = await self._mcp_server._handle_tools_call({
            "name": name,
            "arguments": arguments,
        })
        # 解析 MCP content 格式 → 提取实际数据
        content = result.get("content", [])
        if content and len(content) > 0:
            text = content[0].get("text", "{}")
            import json
            return json.loads(text)
        return result


# 全局单例
_registry: Optional[MCPToolRegistry] = None


def get_tool_registry() -> MCPToolRegistry:
    global _registry
    if _registry is None:
        _registry = MCPToolRegistry()
    return _registry
