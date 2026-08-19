"""
MCP Server v1.0 — 标准 MCP (Model Context Protocol) 协议实现

基于 Anthropic MCP 规范 (2024-2025):
  - JSON-RPC 2.0 消息格式
  - tools/list, tools/call 核心方法
  - resources/list, resources/read 资源访问
  - 动态工具发现 + 渐进式加载

架构:
  MCP Server (JSON-RPC over stdio/HTTP)
    ├── tools/       # 工具执行
    │   ├── keyword_check
    │   ├── history_search
    │   └── image_hash
    ├── resources/   # 数据资源
    │   ├── sensitive_words
    │   ├── violation_taxonomy
    │   └── moderation_policy
    └── prompts/     # Prompt 模板
        ├── text_moderation
        ├── image_moderation
        └── video_moderation

参考:
  - https://spec.modelcontextprotocol.io/
  - https://github.com/modelcontextprotocol/python-sdk
"""
import json
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# === MCP 协议数据结构 ===

@dataclass
class MCPTool:
    """MCP 工具定义"""
    name: str
    description: str
    inputSchema: dict  # JSON Schema
    handler: Callable  # async callable


@dataclass
class MCPResource:
    """MCP 资源定义"""
    uri: str
    name: str
    description: str
    mimeType: str = "application/json"
    content: Any = None
    handler: Optional[Callable] = None  # 动态加载资源的回调


@dataclass
class MCPPrompt:
    """MCP Prompt 模板定义"""
    name: str
    description: str
    arguments: List[Dict] = field(default_factory=list)  # 参数定义
    template: str = ""


class JSONRPCRequest:
    """JSON-RPC 2.0 请求"""
    def __init__(self, method: str, params: dict = None, request_id: Any = None):
        self.jsonrpc = "2.0"
        self.method = method
        self.params = params or {}
        self.id = request_id

    def to_dict(self) -> dict:
        return {
            "jsonrpc": self.jsonrpc,
            "method": self.method,
            "params": self.params,
            "id": self.id,
        }


class JSONRPCResponse:
    """JSON-RPC 2.0 响应"""
    def __init__(self, result: Any = None, error: dict = None, request_id: Any = None):
        self.jsonrpc = "2.0"
        self.result = result
        self.error = error
        self.id = request_id

    def to_dict(self) -> dict:
        d = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error:
            d["error"] = self.error
        else:
            d["result"] = self.result
        return d

    @classmethod
    def error_response(cls, code: int, message: str, request_id: Any = None) -> "JSONRPCResponse":
        return cls(
            error={"code": code, "message": message},
            request_id=request_id,
        )


STANDARD_ERRORS = {
    -32700: "Parse error",
    -32600: "Invalid Request",
    -32601: "Method not found",
    -32602: "Invalid params",
    -32603: "Internal error",
}


class MCPServer:
    """
    MCP 标准协议服务器

    支持:
    - tools/list: 列出所有可用工具 (含 JSON Schema 参数定义)
    - tools/call: 调用指定工具
    - resources/list: 列出所有可用资源
    - resources/read: 读取资源内容
    - prompts/list: 列出所有 Prompt 模板
    - prompts/get: 获取 Prompt 模板
    """

    def __init__(self, name: str = "content-moderation-mcp", version: str = "1.0.0"):
        self.name = name
        self.version = version
        self._tools: Dict[str, MCPTool] = {}
        self._resources: Dict[str, MCPResource] = {}
        self._prompts: Dict[str, MCPPrompt] = {}
        self._register_methods()

    def _register_methods(self):
        """注册 JSON-RPC 方法处理器"""
        self._method_handlers = {
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
            "prompts/list": self._handle_prompts_list,
            "prompts/get": self._handle_prompts_get,
            "initialize": self._handle_initialize,
        }

    # === 工具注册 ===

    def register_tool(self, name: str, description: str, input_schema: dict, handler: Callable):
        """注册工具"""
        self._tools[name] = MCPTool(
            name=name,
            description=description,
            inputSchema=input_schema,
            handler=handler,
        )
        logger.info(f"MCP tool registered: {name}")

    def register_resource(self, uri: str, name: str, description: str,
                          content: Any = None, handler: Callable = None,
                          mime_type: str = "application/json"):
        """注册资源"""
        self._resources[uri] = MCPResource(
            uri=uri, name=name, description=description,
            mimeType=mime_type, content=content, handler=handler,
        )

    def register_prompt(self, name: str, description: str,
                        arguments: List[Dict] = None, template: str = ""):
        """注册 Prompt 模板"""
        self._prompts[name] = MCPPrompt(
            name=name, description=description,
            arguments=arguments or [], template=template,
        )

    # === JSON-RPC 处理 ===

    async def handle_request(self, raw_request: dict) -> dict:
        """处理 JSON-RPC 请求"""
        method = raw_request.get("method", "")
        params = raw_request.get("params", {})
        req_id = raw_request.get("id")

        if not method:
            return JSONRPCResponse.error_response(-32600, "Invalid Request", req_id).to_dict()

        handler = self._method_handlers.get(method)
        if not handler:
            return JSONRPCResponse.error_response(
                -32601, f"Method not found: {method}", req_id
            ).to_dict()

        try:
            result = await handler(params)
            return JSONRPCResponse(result=result, request_id=req_id).to_dict()
        except Exception as e:
            logger.error(f"MCP method {method} failed: {e}")
            return JSONRPCResponse.error_response(
                -32603, f"Internal error: {str(e)}", req_id
            ).to_dict()

    # === 方法处理器 ===

    async def _handle_initialize(self, params: dict) -> dict:
        return {
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": self.name,
                "version": self.version,
            },
            "capabilities": {
                "tools": {},
                "resources": {},
                "prompts": {},
            },
        }

    async def _handle_tools_list(self, params: dict) -> dict:
        tools = []
        for name, tool in self._tools.items():
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema,
            })
        return {"tools": tools}

    async def _handle_tools_call(self, params: dict) -> dict:
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        tool = self._tools.get(tool_name)
        if not tool:
            raise ValueError(f"Unknown tool: {tool_name}")

        # 调用工具处理函数
        result = await tool.handler(**arguments)

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, default=str),
                }
            ]
        }

    async def _handle_resources_list(self, params: dict) -> dict:
        resources = []
        for uri, res in self._resources.items():
            resources.append({
                "uri": uri,
                "name": res.name,
                "description": res.description,
                "mimeType": res.mimeType,
            })
        return {"resources": resources}

    async def _handle_resources_read(self, params: dict) -> dict:
        uri = params.get("uri", "")
        resource = self._resources.get(uri)
        if not resource:
            raise ValueError(f"Unknown resource: {uri}")

        if resource.handler:
            content = await resource.handler()
        else:
            content = resource.content

        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": resource.mimeType,
                    "text": json.dumps(content, ensure_ascii=False) if isinstance(content, (dict, list)) else str(content),
                }
            ]
        }

    async def _handle_prompts_list(self, params: dict) -> dict:
        prompts = []
        for name, prompt in self._prompts.items():
            prompts.append({
                "name": name,
                "description": prompt.description,
                "arguments": prompt.arguments,
            })
        return {"prompts": prompts}

    async def _handle_prompts_get(self, params: dict) -> dict:
        prompt_name = params.get("name", "")
        prompt_args = params.get("arguments", {})

        prompt = self._prompts.get(prompt_name)
        if not prompt:
            raise ValueError(f"Unknown prompt: {prompt_name}")

        # 替换模板变量
        template = prompt.template
        for key, value in prompt_args.items():
            template = template.replace(f"{{{{{key}}}}}", str(value))

        return {
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": template},
                }
            ]
        }

    # === 初始化默认注册 ===

    def register_default_tools(self, keyword_tool, history_tool, image_hash_tool):
        """[DEPRECATED] 注册默认的审核工具 — 仅注册 3 个工具，请使用 register_tools_from_registry() 注册全部 8 个工具"""
        # 此方法保留用于向后兼容，但实际初始化应使用 register_tools_from_registry()
        logger.warning(
            "register_default_tools() is deprecated — only 3 of 8 tools registered. "
            "Use register_tools_from_registry() instead."
        )
        self._legacy_register_3_tools(keyword_tool, history_tool, image_hash_tool)

    def _legacy_register_3_tools(self, keyword_tool, history_tool, image_hash_tool):
        """旧版 3 工具注册逻辑（向后兼容）"""

        async def keyword_handler(text: str) -> dict:
            result = await keyword_tool.execute(text)
            return {
                "has_violation": result.has_violation,
                "matches": result.matches,
                "count": result.count,
            }

        self.register_tool(
            name="keyword_check",
            description="检测文本中的敏感词（基于 AC 自动机的本地匹配）",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "待检测的文本内容"}},
                "required": ["text"],
            },
            handler=keyword_handler,
        )

        async def history_handler(query: str, top_k: int = 5) -> dict:
            result = await history_tool.execute(query, top_k)
            return {"cases": result.cases, "has_match": result.has_match, "count": len(result.cases)}

        self.register_tool(
            name="history_search",
            description="检索相似的历史审核案例（ChromaDB 向量检索 + BM25 混合检索）",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索查询文本"},
                    "top_k": {"type": "integer", "description": "返回结果数量（默认 5）", "default": 5},
                },
                "required": ["query"],
            },
            handler=history_handler,
        )

        async def image_hash_handler(image_data: str = "", threshold: int = 10) -> dict:
            import base64
            data = base64.b64decode(image_data) if image_data else b""
            result = await image_hash_tool.execute(data, threshold)
            return {
                "hash_hex": result.hash_hex if result else "",
                "similarity": result.similarity if result else 0.0,
            }

        self.register_tool(
            name="image_hash",
            description="计算图片的 dHash 值并检测相似图片",
            input_schema={
                "type": "object",
                "properties": {
                    "image_data": {"type": "string", "description": "Base64 编码的图片数据"},
                    "threshold": {"type": "integer", "description": "汉明距离阈值（默认 10）", "default": 10},
                },
                "required": ["image_data"],
            },
            handler=image_hash_handler,
        )

    def _build_tool_handler(self, tool_name: str, tool_instance: object):
        """
        为指定工具构建泛用 handler 闭包。

        利用 Python 闭包捕获 tool_name 和 tool_instance，
        解决 for 循环中 lambda/闭包的晚期绑定问题。
        """
        import base64

        # 特殊参数转换映射（某些工具的 execute() 参数名与 schema 不同）
        PARAM_MAPPING = {
            "history_search": {"query": "query", "top_k": "top_k", "use_hybrid": "use_hybrid"},
        }

        async def handler(**kwargs):
            # 特殊处理：image_hash 的 schema 接收 base64 字符串，execute 接收 bytes
            if tool_name == "image_hash" and "image_data" in kwargs:
                kwargs["image_data"] = base64.b64decode(kwargs["image_data"]) if kwargs["image_data"] else b""

            # 调用 execute 方法
            result = await tool_instance.execute(**kwargs)

            # 将结果转为 dict
            if hasattr(result, 'model_dump'):
                return result.model_dump()
            elif hasattr(result, 'dict'):
                return result.dict()
            return result

        return handler

    def register_tools_from_registry(self, registry_tools: dict, registry_schemas: dict):
        """
        从 MCPToolRegistry 批量注册全部工具（替代旧版 register_default_tools）。

        为 registry 中的每个工具自动构建 handler 闭包并注册到 MCPServer。

        Args:
            registry_tools: {name: tool_instance} — 来自 MCPToolRegistry._tools
            registry_schemas: {name: schema_dict} — 来自 MCPToolRegistry._tool_schemas
        """
        import base64

        registered = 0
        for tool_name, tool_instance in registry_tools.items():
            schema = registry_schemas.get(tool_name, {})
            if not schema:
                logger.warning(f"No schema found for tool '{tool_name}', skipping")
                continue

            handler = self._build_tool_handler(tool_name, tool_instance)
            self.register_tool(
                name=schema.get("name", tool_name),
                description=schema.get("description", ""),
                input_schema=schema.get("inputSchema", {}),
                handler=handler,
            )
            registered += 1

        logger.info(f"MCP Server: registered {registered}/{len(registry_tools)} tools from registry")

    def register_default_resources(self):
        """注册默认资源"""
        # 敏感词列表资源
        self.register_resource(
            uri="moderation://sensitive_words",
            name="sensitive_words",
            description="敏感词列表",
            content={
                "political": ["违禁品", "管制刀具", "枪支", "弹药"],
                "adult": ["色情", "裸体", "淫秽"],
                "violence": ["暴力", "恐怖", "杀人"],
                "fraud": ["中奖", "转账", "汇款", "银行卡号"],
                "advertisement": ["加微信", "加QQ", "扫码", "兼职", "赚钱"],
            },
        )

        # 违规分类体系
        self.register_resource(
            uri="moderation://violation_taxonomy",
            name="violation_taxonomy",
            description="违规分类体系定义",
            content={
                "categories": [
                    {"id": "politics", "label": "政治敏感", "severity": "critical"},
                    {"id": "porn", "label": "色情低俗", "severity": "high"},
                    {"id": "violence", "label": "暴力恐怖", "severity": "critical"},
                    {"id": "false_info", "label": "虚假信息", "severity": "high"},
                    {"id": "harassment", "label": "辱骂骚扰", "severity": "medium"},
                    {"id": "advertisement", "label": "广告引流", "severity": "medium"},
                    {"id": "illegal", "label": "违法违规", "severity": "critical"},
                    {"id": "phishing", "label": "钓鱼诈骗", "severity": "high"},
                ],
                "decision_thresholds": {
                    "REVIEW": 0.35,
                    "REJECT": 0.75,
                },
            },
        )

        # 审核政策文档
        self.register_resource(
            uri="moderation://policy",
            name="moderation_policy",
            description="内容审核政策指南",
            content={
                "version": "1.0",
                "principles": [
                    "依法依规审核",
                    "保护未成年人",
                    "维护网络空间清朗",
                    "打击黑灰产行为",
                ],
            },
        )

    def register_default_prompts(self):
        """注册默认 Prompt 模板"""
        self.register_prompt(
            name="text_moderation",
            description="文本内容审核 Prompt",
            arguments=[
                {"name": "content", "description": "待审核文本", "required": True},
            ],
            template="""你是内容安全审核专家。分析以下文本是否违反社区规范。

审核维度：
1. 政治敏感 2. 色情低俗 3. 暴力恐怖 4. 虚假信息 5. 辱骂骚扰 6. 广告引流

待审核文本：
{{content}}

请以JSON格式返回分析结果：
{"violation_type": "none|politics|porn|violence|false_info|harassment|advertisement",
 "confidence": 0.0-1.0, "reason": "判断依据", "is_adversarial": false, "tags": []}""",
        )

        self.register_prompt(
            name="image_moderation",
            description="图片内容审核 Prompt",
            arguments=[
                {"name": "ocr_text", "description": "OCR提取的文字", "required": False},
                {"name": "scene_description", "description": "场景描述", "required": False},
            ],
            template="""你是严格的内容安全审核专家。分析从图片中提取的文字内容，判断是否违规。

OCR文字: {{ocr_text}}
场景描述: {{scene_description}}

审核标准：暴力恐怖 > 色情低俗 > 政治敏感 > 广告引流 > 虚假信息 > 辱骂骚扰
请以JSON格式返回。""",
        )


# 全局 MCP Server 实例
_mcp_server: Optional[MCPServer] = None


def get_mcp_server() -> MCPServer:
    global _mcp_server
    if _mcp_server is None:
        _mcp_server = MCPServer()
        # 延迟注册工具和资源（需要先初始化依赖）
    return _mcp_server


def init_mcp_server(keyword_tool, history_tool, image_hash_tool):
    """初始化 MCP Server (注册默认工具和资源)"""
    server = get_mcp_server()
    server.register_default_tools(keyword_tool, history_tool, image_hash_tool)
    server.register_default_resources()
    server.register_default_prompts()
    logger.info("MCP Server initialized with default tools/resources/prompts")
    return server
