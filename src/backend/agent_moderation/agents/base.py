"""
Agent 基类 v2.0 — 集成 PromptRegistry + Telemetry

升级内容:
  - 支持从 PromptRegistry 加载 System Prompt (而非硬编码)
  - 集成 OpenTelemetry 全链路追踪
  - 支持 DSPy 编译后的优化 Prompt
"""
import json
from abc import ABC, abstractmethod
from agent_moderation.state import ModerationState


class BaseAgent(ABC):
    """所有 Agent 的抽象基类 (v2.0)"""

    def __init__(self, name: str):
        self.name = name
        self._prompt_registry = None
        self._telemetry = None

    @abstractmethod
    async def process(self, state: ModerationState) -> ModerationState:
        """处理审核状态，返回更新后的状态"""
        pass

    def log_step(self, message: str):
        """记录 Agent 执行步骤 (v3.0: 同时输出到终端 FlowLogger)"""
        from common.logger import get_flow_logger
        fl = get_flow_logger()
        if fl:
            fl.box_step("→", "", message, "white")
        print(f"[{self.name}] {message}")

    def log_box_start(self, subtitle: str = ""):
        """打印 Agent 模块开始边界框"""
        from common.logger import get_flow_logger
        fl = get_flow_logger()
        if fl:
            fl.box_start(self.name.upper(), subtitle)

    def log_box_end(self, summary: str = ""):
        """打印 Agent 模块结束边界框"""
        from common.logger import get_flow_logger
        fl = get_flow_logger()
        if fl:
            fl.box_end(self.name.upper(), summary)

    def log_rag(self, query: str, results: list, duration_ms: float = 0):
        """打印 RAG 检索结果"""
        from common.logger import get_flow_logger
        fl = get_flow_logger()
        if fl:
            n = len(results) if results else 0
            top_score = results[0].get("similarity", results[0].get("score", 0)) if results else 0
            top_type = results[0].get("violation_type", "?") if results else "?"
            fl.box_step("🔍 RAG检索", f"查询\"{query[:50]}\"", f"→ {n}条 | top={top_score:.2f} | {top_type}", "blue")
            fl.box_rag_result(results, "blue")

    def log_llm(self, model: str, input_summary: str, output_summary: str, duration_ms: float = 0):
        """打印 LLM 调用结果"""
        from common.logger import get_flow_logger
        fl = get_flow_logger()
        if fl:
            fl.box_step("🧠 LLM调用", model, f"{output_summary} ({duration_ms:.0f}ms)", "magenta")

    def get_prompt(self, prompt_name: str, content: str, version: str = None) -> tuple:
        """
        从 PromptRegistry 获取 System Prompt

        代替硬编码的 PROMPT 常量:
          system_prompt, user_message = self.get_prompt("text_moderation", text)

        Args:
            prompt_name: Prompt 名称 (如 "text_moderation")
            content: 待审核内容
            version: 指定版本 (None = 使用活跃版本)

        Returns:
            (system_prompt, user_message)
        """
        if self._prompt_registry is None:
            from optimization.prompt_optimizer import get_prompt_registry
            self._prompt_registry = get_prompt_registry()
        return self._prompt_registry.build_full_prompt(prompt_name, content, version)

    def get_active_prompt_version(self, prompt_name: str) -> str:
        """获取当前活跃的 Prompt 版本号"""
        if self._prompt_registry is None:
            from optimization.prompt_optimizer import get_prompt_registry
            self._prompt_registry = get_prompt_registry()
        pv = self._prompt_registry.get_active(prompt_name)
        return pv.version if pv else "unknown"

    def trace(self, content_id: str, content_type: str):
        """
        获取 Telemetry 追踪上下文

        Usage:
            with self.trace(content_id, content_type):
                result = await self.process(state)
        """
        if self._telemetry is None:
            from common.telemetry import get_telemetry
            self._telemetry = get_telemetry()
        return self._telemetry.trace_agent(
            self.name, content_id, content_type,
        )

    def trace_llm(self, model: str, prompt_tokens: int, completion_tokens: int, duration_ms: float):
        """追踪 LLM API 调用"""
        if self._telemetry is None:
            from common.telemetry import get_telemetry
            self._telemetry = get_telemetry()
        self._telemetry.trace_llm_call(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
            agent_name=self.name,
        )

    # ===== v4.2: Skill 知识注入 =====

    _skill_registry = None

    def _load_skill_context(self, skill_names: list) -> str:
        """
        从 SkillRegistry 加载指定 Skill 的 Agent 上下文。

        Args:
            skill_names: Skill 名称列表（如 ["keyword-check", "history-search"]）

        Returns:
            格式化的上下文文本，可拼接到 system prompt 中。
            如果 SkillRegistry 不可用或 Skill 不存在，返回空字符串。
        """
        try:
            if self._skill_registry is None:
                from agent_moderation.skill_registry import get_skill_registry
                type(self)._skill_registry = get_skill_registry()

            parts = []
            for name in skill_names:
                ctx = self._skill_registry.get_skill_context(name)
                if ctx:
                    parts.append(ctx)
                    from common.logger import get_flow_logger
                    fl = get_flow_logger()
                    if fl:
                        fl.box_step("📚 Skill注入", name, "→ system prompt", "cyan")

            return "\n\n".join(parts) if parts else ""
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"Skill load skipped: {e}")
            return ""

    # ===== v4.3: MCP Gateway 工具调用（RBAC + 审计） =====

    async def _call_mcp_tool(self, tool_name: str, **kwargs) -> dict:
        """
        通过 MCP Gateway 调用工具（替代直接 tool.execute()）。

        经过 Gateway 流水线: RBAC → 参数校验 → 执行 → 审计日志

        Args:
            tool_name: 工具名称（如 "keyword_check"）
            **kwargs: 工具参数

        Returns:
            工具执行结果 dict，包裹为 SimpleNamespace 以支持属性访问。
            兼容旧的 tool.execute() 返回类型。
        """
        from types import SimpleNamespace
        from mcp_gateway import get_gateway
        import logging as _logging
        _logger = _logging.getLogger(__name__)

        gateway = get_gateway()
        try:
            result_dict = await gateway.call_tool(
                tool_name=tool_name,
                arguments=kwargs,
                agent_type=self.name,
                content_id=getattr(self, '_current_content_id', ''),
            )
            # 将 dict 包装为 SimpleNamespace 以兼容旧的 obj.attr 访问模式
            return self._dict_to_namespace(result_dict)
        except PermissionError as e:
            _logger.error(f"MCP Gateway access denied: {e}")
            raise
        except Exception as e:
            _logger.error(f"MCP Gateway call failed for '{tool_name}': {e}")
            raise

    @staticmethod
    def _dict_to_namespace(d):
        """递归将 dict 转换为 SimpleNamespace（支持嵌套对象和列表）"""
        from types import SimpleNamespace
        if isinstance(d, dict):
            return SimpleNamespace(**{k: BaseAgent._dict_to_namespace(v) for k, v in d.items()})
        elif isinstance(d, list):
            return [BaseAgent._dict_to_namespace(item) for item in d]
        return d

    @staticmethod
    def _to_dict_list(items) -> list:
        """将元素统一转为 dict（兼容 dict / SimpleNamespace / 其他对象）。

        MCP Gateway 返回 SimpleNamespace（_dict_to_namespace），下游若用
        ``case.get("similarity")`` 访问会抛 AttributeError。统一在此转 dict。
        """
        out = []
        for it in items or []:
            if isinstance(it, dict):
                out.append(dict(it))
            elif hasattr(it, "__dict__"):
                out.append(dict(it.__dict__))
            else:
                out.append({"content": str(it)})
        return out

    @staticmethod
    def _safe_json_parse(raw_content: str) -> dict:
        """多级容错解析 LLM/VL 的 JSON 响应（R22: 裸 json.loads 遇非 JSON 会静默降级，
        导致违规内容被误放行）。支持：
        1. 纯 JSON
        2. markdown ```json 代码块
        3. 文本中提取最后一个完整 JSON 对象
        4. json_repair 修复
        全部失败返回 None（由调用方决定降级策略并记日志）。
        """
        import re as _re
        text = (raw_content or "").strip()

        if text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

        json_match = _re.search(r"```(?:json)?\s*\n?(\{.*?\})\s*\n?```", text, _re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        json_matches = list(_re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, _re.DOTALL))
        if json_matches:
            try:
                return json.loads(json_matches[-1].group(0))
            except json.JSONDecodeError:
                pass

        try:
            from json_repair import repair_json
            brace_idx = text.rfind("{")
            if brace_idx >= 0:
                repaired = repair_json(text[brace_idx:])
                return json.loads(repaired)
        except Exception:
            pass

        return None

    # ===== v5.0: Skill 动态路由与自优化 =====

    _skill_router = None
    _skill_routing_log = []

    def _get_default_skills_for_agent(self) -> list:
        """
        返回当前 Agent 的默认 Skill 列表（兜底用）。
        当动态路由失败或无结果时使用。

        Returns:
            Skill 名称列表
        """
        agent_name = self.name if hasattr(self, 'name') else 'unknown'

        default_maps = {
            'text_agent': ['keyword-check', 'history-search'],
            'image_agent': ['image-hash'],
            'audio_agent': ['keyword-check'],
            'video_agent': ['image-hash'],
            'react_agent': ['history-search', 'keyword-check', 'rag_hybrid_query'],
            'risk_agent': ['risk_grade_check', 'evidence_fusion_check'],
            'blackhat_agent': ['adversarial-detect', 'account_risk_check'],
            'file_agent': ['keyword-check', 'pii_scan'],
            'planner': ['triage_check', 'cascade_routing'],
            'supervisor': ['skill_routing', 'policy_query'],
            'debate_panel': ['evidence_fusion_check'],
            'reflexion': ['regression_guard'],
        }

        return default_maps.get(agent_name, ['keyword-check'])

    def _get_content_tags(self, content_type: str = 'text') -> set:
        """
        根据内容类型获取对应的标签集合，用于 Skill Filter。

        Args:
            content_type: 内容类型

        Returns:
            标签集合
        """
        tag_maps = {
            'text': {'text', 'rag', 'retrieval'},
            'image': {'image', 'visual', 'retrieval'},
            'audio': {'audio', 'text'},
            'video': {'video', 'image', 'visual'},
            'file': {'text', 'document'},
        }
        return tag_maps.get(content_type, {'text'})

    def _log_skill_routing(self, content_id: str, query: str, content_type: str,
                           filtered: list, ranked: list, selected: list) -> None:
        """
        记录 Skill 路由日志，用于后续自优化分析。

        Args:
            content_id: 内容 ID
            query: 用于路由的查询文本
            content_type: 内容类型
            filtered: Filter 阶段结果
            ranked: Rank 阶段结果
            selected: Select 阶段结果（最终注入）
        """
        import time
        import logging
        import json
        from datetime import datetime, timezone

        agent_name = self.name if hasattr(self, 'name') else 'unknown'
        now_ts = time.time()
        now_dt = datetime.now(timezone.utc)

        log_entry = {
            "content_id": content_id,
            "agent": agent_name,
            "query": query[:500] if query else '',
            "content_type": content_type,
            "filtered": filtered,
            "ranked": ranked,
            "selected": selected,
            "timestamp": now_ts,
        }

        # 内存中保留最近 1000 条
        type(self)._skill_routing_log.append(log_entry)
        if len(type(self)._skill_routing_log) > 1000:
            type(self)._skill_routing_log = type(self)._skill_routing_log[-1000:]

        # 写入文件用于持久化分析
        try:
            from common.config import get_settings
            settings = get_settings()
            log_dir = getattr(settings, 'SKILL_LOG_DIR', '/tmp/skill_logs')
            import os
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, f'skill_routing_{int(now_ts)}.jsonl')
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        except Exception as e:
            logging.getLogger(__name__).debug(f"Failed to write skill routing log to file: {e}")

        # 同时写入数据库用于查询和分析（后台任务，不阻塞主流程）
        try:
            from db.connection import get_session_factory
            from db.models import SkillRoutingLog
            import asyncio

            async def _write_to_db():
                try:
                    session_factory = get_session_factory()
                    async with session_factory() as session:
                        log = SkillRoutingLog(
                            content_id=content_id,
                            agent=agent_name,
                            query=query[:500] if query else None,
                            content_type=content_type,
                            filtered_skills=filtered,
                            ranked_skills=ranked,
                            selected_skills=selected,
                            timestamp=now_dt,
                            created_at=now_dt,
                        )
                        session.add(log)
                        await session.commit()
                except Exception as e:
                    logging.getLogger(__name__).debug(f"Failed to write skill routing log to DB: {e}")

            # 尝试获取当前的事件循环并在后台运行
            try:
                loop = asyncio.get_running_loop()
                if loop and not loop.is_closed():
                    loop.create_task(_write_to_db())
            except RuntimeError:
                # 没有运行中的事件循环，忽略（不阻塞主流程）
                pass
        except Exception as e:
            logging.getLogger(__name__).debug(f"Failed to queue skill routing DB write: {e}")

    def _load_relevant_skills(self, query: str, content_type: str = 'text',
                              max_inject: int = 3, content_id: str = '') -> str:
        """
        动态加载与当前内容相关的 Skills。

        使用 SkillRouter 三级路由（Filter → Rank → Select）：
        1. Filter: 按标签/触发词/描述关键词粗筛
        2. Rank: 语义相似度精排
        3. Select: 取 top N 注入

        向下兼容：路由失败时回退到 Agent 默认 Skill 列表。

        Args:
            query: 用于路由的查询文本（通常是待审核内容）
            content_type: 内容类型
            max_inject: 最多注入的 Skill 数量
            content_id: 内容 ID（用于日志记录）

        Returns:
            格式化的 Skill 上下文文本，可拼接到 system prompt 中
        """
        import logging
        logger = logging.getLogger(__name__)

        filtered_names = []
        ranked_names = []
        selected_names = []

        try:
            # 1. 初始化 Router 和 Registry（懒加载）
            if self._skill_registry is None:
                from agent_moderation.skill_registry import get_skill_registry
                type(self)._skill_registry = get_skill_registry()

            if self._skill_router is None:
                from agent_moderation.skill_router import get_skill_router
                type(self)._skill_router = get_skill_router()

            # 2. 调用三级路由
            tags = self._get_content_tags(content_type)
            router_result = self._skill_router.route(
                query=query,
                tags=tags,
                top_n=20,
                top_k=8,
                max_inject=max_inject,
            )

            filtered_names = router_result.get('filtered', [])
            ranked_names = router_result.get('ranked', [])
            selected_names = router_result.get('selected', [])

            logger.debug(f"SkillRouter: filtered={len(filtered_names)}, ranked={len(ranked_names)}, selected={selected_names}")

        except Exception as e:
            logger.warning(f"SkillRouter failed, falling back to default skills: {e}")
            # 路由失败时回退到默认 Skill
            selected_names = self._get_default_skills_for_agent()

        # 3. 如果没有选中任何 Skill，使用默认 Skill 兜底
        if not selected_names:
            selected_names = self._get_default_skills_for_agent()
            logger.debug(f"SkillRouter: no skills selected, using defaults: {selected_names}")

        # 4. 记录路由日志
        self._log_skill_routing(
            content_id=content_id,
            query=query,
            content_type=content_type,
            filtered=filtered_names,
            ranked=ranked_names,
            selected=selected_names,
        )

        # 5. 加载并返回 Skill 上下文
        return self._load_skill_context(selected_names)
