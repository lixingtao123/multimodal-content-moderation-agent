"""
Risk Assessment Agent v2.0 — 综合风险评估与决策判定
- 模态感知的自适应阈值
- 多维度协同评分
- 违规类型强制升级规则
"""
import json
import time
import logging
from agent_moderation.state import ModerationState
from agent_moderation.agents.base import BaseAgent
from agent_moderation.violation_types import FORCE_REVIEW_TYPES, FORCE_REJECT_TYPES
from memory.manager import get_memory_manager

logger = logging.getLogger(__name__)


class RiskAssessmentAgent(BaseAgent):
    """风险评估 Agent v2.0 — 阈值支持策略配置动态加载"""

    # 默认阈值（策略缓存不可用时的回退值）
    DEFAULT_REJECT_THRESHOLD = 0.75
    DEFAULT_REVIEW_THRESHOLD = 0.35

    # 强制升级违规类型（R20：统一引用 violation_types.py，含 crime）
    FORCE_REVIEW_TYPES = FORCE_REVIEW_TYPES
    FORCE_REJECT_TYPES = FORCE_REJECT_TYPES

    def __init__(self):
        super().__init__("risk_agent")
        self.memory = get_memory_manager()

    @property
    def reject_threshold(self) -> float:
        """从策略缓存加载 REJECT 阈值，回退到默认值"""
        try:
            from api.routes.policies import get_active_threshold_config
            return get_active_threshold_config()["reject_threshold"]
        except Exception:
            return self.DEFAULT_REJECT_THRESHOLD

    @property
    def review_threshold(self) -> float:
        """从策略缓存加载 REVIEW 阈值，回退到默认值"""
        try:
            from api.routes.policies import get_active_threshold_config
            return get_active_threshold_config()["review_threshold"]
        except Exception:
            return self.DEFAULT_REVIEW_THRESHOLD

    async def process(self, state: ModerationState) -> ModerationState:
        """综合风险评估 v2.0"""
        content_id = state.get("content_id", "unknown")
        await self.memory.update_task_step(content_id, "risk_agent")

        content_type = state.get("content_type", "text")

        # v5.0: 动态注入 Skill 知识用于风险评估
        content = state.get("content", {})
        text_content = content.get("text", "")
        skill_context = self._load_relevant_skills(
            query=text_content,
            content_type=content_type,
            max_inject=3,
            content_id=content_id,
        )

        # 1. 收集各维度风险分量
        risk_components = self._collect_components(state)
        self.log_step(f"Components: {list(risk_components.keys())} → {risk_components}")

        # 2. 违规类型汇总
        violation_types = self._collect_violation_types(state)

        # 3. 综合评分（模态感知）
        overall_score = self._calculate_overall_v2(risk_components, violation_types, content_type)

        # 4. 决策判定（含强制升级规则）
        decision = self._make_decision(overall_score, violation_types)

        # v3.2: 中低置信度 → 标记需要人工审核 (已人工处理过的跳过)
        existing_review = (state.get("_human_review") or {})
        already_resolved = existing_review.get("status") == "RESOLVED" if isinstance(existing_review, dict) else False
        # 当 decision=REVIEW 且风险分不在极端高/低时，标记人工复核
        if 0.25 <= overall_score < 0.70 and decision != "PASS" and not already_resolved:
            state["_human_review"] = {
                "required": True,
                "reason": f"模糊边界: risk_score={overall_score:.3f}, decision={decision}",
                "status": "PENDING",
            }
            print(f"[risk_agent] FLAGGED for human review! score={overall_score:.4f}, decision={decision}")

        # 5. 生成修复建议
        suggestions = self._generate_suggestions(state, decision, violation_types)

        # 6. 保存到长期记忆 (v3.1: 重要性评分分层存储)
        content_preview = self._get_content_preview(state)
        try:
            # 收集重要性评分参数 (用 or {} 防止 TypedDict 中显式 None 值)
            def _sget(d, key):
                """安全获取 state 中可能为 None 的 dict 值"""
                return d.get(key) or {}
            conf = max(
                _sget(state, "text_result").get("confidence", 0),
                _sget(state, "image_result").get("confidence", 0),
                _sget(state, "audio_result").get("confidence", 0),
                _sget(state, "video_result").get("confidence", 0),
            )
            is_adv = (
                _sget(state, "text_result").get("is_adversarial", False)
                or _sget(state, "image_result").get("is_adversarial", False)
            )
            main_vt = violation_types[0] if violation_types else "none"
            await self.memory.save_case(
                case_id=state["content_id"],
                content=content_preview,
                violation_type=main_vt,
                decision=decision,
                confidence=conf,
                risk_score=overall_score,
                is_adversarial=is_adv,
                frequency=0,
            )
        except Exception as e:
            logger.warning(f"Failed to save case to ChromaDB: {e}")

        # v3.6: 异步保存 GraphRAG 状态 (fire-and-forget, 不阻塞)
        try:
            import asyncio
            from memory.graph_rag import get_graph_rag
            graph_rag = get_graph_rag()
            asyncio.ensure_future(graph_rag.save())
        except Exception:
            pass

        # v3.7: 账号风险画像更新 (从 BlackhatAgent 迁移) — fire-and-forget
        account_id = state.get("account_id")
        if account_id and violation_types:
            try:
                from agent_moderation.blackhat.account_risk import get_account_profiler
                profiler = get_account_profiler()
                # 收集所有黑灰产模式类型
                bh_result = state.get("blackhat_result") or {}
                bh_patterns = [p.get("type", "") for p in bh_result.get("pattern_detected", [])]
                adv_techniques = [a.get("technique", "") for a in bh_result.get("adversarial_detected", [])]
                profiler.record_violation(
                    account_id=account_id,
                    violation_type=violation_types[0] if violation_types else "none",
                    risk_score=overall_score,
                    patterns=list(set(bh_patterns + adv_techniques)),
                )
                # 更新 blackhat_result 的 account_risk (供 risk_components 使用)
                profile = profiler.get_profile(account_id).to_dict()
                if bh_result:
                    bh_result["account_risk"] = profile
                    state["blackhat_result"] = bh_result
            except Exception as e:
                logger.warning(f"Account risk profiling failed (non-blocking): {e}")

        # v3.6: FlowLogger 输出风险评估结果
        try:
            from common.logger import get_flow_logger
            fl = get_flow_logger()
            if fl:
                fl.box_start("⚖️ 综合评估 (RiskAgent)")
                for key in ("text", "image", "audio", "video", "blackhat"):
                    score = risk_components.get(key, 0)
                    if isinstance(score, dict):
                        score = score.get("risk_score", 0)
                    if score > 0:
                        icon_map = {"text": "📝", "image": "🖼️", "audio": "🎤", "video": "🎬", "blackhat": "🕵️"}
                        icon = icon_map.get(key, "→")
                        fl.box_step(icon, f"{key}分析", f"risk={score:.2f}")
                fl.box_step("📊", "综合评分", f"{overall_score:.2f} → 决策: {decision}", "cyan")
                fl.box_step("💾", "案例入库", f"importance计算 → ChromaDB", "dim")
                if decision in ("REJECT", "REVIEW") and violation_types:
                    fl.box_step("🔗", "GraphRAG注册", f"类型={violation_types[0]} → 知识图谱关联", "green")
                fl.box_end("⚖️ 综合评估", f"decision={decision} | score={overall_score:.2f}")
        except Exception:
            pass

        process_time = round((time.time() - state.get("start_time", time.time())) * 1000, 2)

        state["final_risk"] = {
            "components": risk_components,
            "overall_score": overall_score,
            "decision": decision,
            "violation_types": violation_types,
            "suggestions": suggestions,
            "processing_time_ms": process_time,
        }
        state["final_decision"] = decision

        await self.memory.complete_task(state["content_id"], {
            "final_decision": decision,
            "overall_score": overall_score,
            "violation_types": violation_types,
            "violation_details": {
                "components": risk_components,
                "overall_score": overall_score,
                "decision": decision,
                "violation_types": violation_types,
                "suggestions": suggestions,
                "processing_time_ms": process_time,
            },
        })

        self.log_step(f"Decision: {decision}, Score: {overall_score:.3f}, "
                       f"Types: {violation_types}, Time: {process_time}ms")
        return state

    def _collect_components(self, state: ModerationState) -> dict:
        """收集各模态风险分量"""
        components = {}
        for key, result_key in [
            ("text", "text_result"),
            ("image", "image_result"),
            ("audio", "audio_result"),
            ("video", "video_result"),
            ("blackhat", "blackhat_result"),
        ]:
            result = state.get(result_key)
            if result:
                if key == "video":
                    score = result.get("overall_risk_score", 0.0)
                elif key == "blackhat":
                    score = result.get("blackhat_risk_score", 0.0)
                else:
                    score = result.get("risk_score", 0.0)
                if score > 0:
                    components[key] = score
        return components

    def _calculate_overall_v2(
        self, components: dict, violation_types: list, content_type: str
    ) -> float:
        """加权计算总风险分 v2.0 — 模态感知"""
        if not components:
            return 0.0

        values = list(components.values())

        # 策略：max + 类型惩罚
        max_risk = max(values)
        avg_risk = sum(values) / len(values)

        # 基础分数
        overall = max_risk * 0.6 + avg_risk * 0.4

        # 多模态协同：多个维度同时检测到风险时为强信号
        if len(values) >= 2:
            overall *= 1.1  # 10% boost for multi-modality

        # 违规类型升级
        force_types = [t for t in violation_types if t in self.FORCE_REVIEW_TYPES]
        if force_types:
            overall = max(overall, self.review_threshold)  # at least REVIEW
        force_reject = [t for t in violation_types if t in self.FORCE_REJECT_TYPES]
        if force_reject and max_risk > 0.5:
            overall = max(overall, self.reject_threshold)

        return round(min(overall, 1.0), 4)

    def _make_decision(self, score: float, violation_types: list) -> str:
        """决策判定（含强制规则）"""
        # 强制拒绝规则
        if any(t in self.FORCE_REJECT_TYPES for t in violation_types) and score >= 0.65:
            return "REJECT"

        if score >= self.reject_threshold:
            return "REJECT"
        elif score >= self.review_threshold:
            return "REVIEW"
        else:
            return "PASS"

    def _collect_violation_types(self, state: ModerationState) -> list:
        """汇总违规类型（含子类型展开）"""
        types = []

        for key in ["text_result", "image_result", "audio_result", "video_result"]:
            result = state.get(key)
            if result:
                vt = result.get("violation_type", "none")
                if vt and vt != "none":
                    types.append(vt)
                # 收集 tags 中的额外类型
                tags = result.get("tags", [])
                for tag in tags:
                    if tag in self.FORCE_REVIEW_TYPES and tag not in types:
                        types.append(tag)

        # 黑灰产模式类型（排除检测方法类模式，仅计入真正的违规类型）
        NON_VIOLATION_PATTERNS = {"BULK_GENERATION", "KEYWORD_VARIANT", "FORMAT_SPOOFING"}
        blackhat = state.get("blackhat_result")
        if blackhat:
            patterns = blackhat.get("pattern_detected", [])
            for p in patterns:
                ptype = p.get("type", "")
                if ptype and ptype not in types and ptype not in NON_VIOLATION_PATTERNS:
                    types.append(ptype)

        # 去重
        seen = set()
        return [t for t in types if not (t in seen or seen.add(t))]

    def _generate_suggestions(self, state: ModerationState, decision: str, violation_types: list) -> list:
        """生成修复建议 v2.0"""
        suggestions = []

        if decision == "PASS":
            return suggestions

        if decision == "REJECT":
            suggestions.append({
                "action": "DELETE",
                "reason": f"内容严重违规 [{', '.join(violation_types)}]，建议立即删除",
                "priority": "HIGH",
            })

        if decision == "REVIEW":
            suggestions.append({
                "action": "MANUAL_REVIEW",
                "reason": f"内容存在风险 [{', '.join(violation_types)}]，需人工复核",
                "priority": "MEDIUM",
            })

        # 类型特化建议 — v5.0: 覆盖全部 12 个违规类（含新增 6 类）
        type_suggestions = {
            "advertisement": {"action": "WARN", "reason": "疑似广告引流内容", "priority": "LOW"},
            "porn": {"action": "DELETE", "reason": "色情低俗内容", "priority": "HIGH"},
            "violence": {"action": "DELETE", "reason": "暴力威胁内容", "priority": "HIGH"},
            "politics": {"action": "ESCALATE", "reason": "政治敏感内容，需高级审核", "priority": "HIGH"},
            "harassment": {"action": "WARN", "reason": "辱骂骚扰内容", "priority": "MEDIUM"},
            "false_info": {"action": "FLAG", "reason": "疑似虚假信息，需核实", "priority": "MEDIUM"},
            "privacy": {"action": "FLAG", "reason": "疑似隐私窃取内容", "priority": "MEDIUM"},
            "discrimination": {"action": "WARN", "reason": "歧视性言论", "priority": "MEDIUM"},
            "crime": {"action": "DELETE", "reason": "违法犯罪引导", "priority": "HIGH"},
            "ethics": {"action": "FLAG", "reason": "道德伦理失范", "priority": "MEDIUM"},
            "health": {"action": "ESCALATE", "reason": "身心健康危害，需重点关注", "priority": "HIGH"},
            "copyright": {"action": "WARN", "reason": "疑似侵权内容", "priority": "LOW"},
        }
        for vt in violation_types:
            if vt in type_suggestions:
                s = type_suggestions[vt].copy()
                if s not in suggestions:
                    suggestions.append(s)

        return suggestions

    def _get_content_preview(self, state: ModerationState) -> str:
        """获取内容摘要"""
        content_type = state.get("content_type", "text")
        content = state.get("content", {})

        if content_type == "text":
            return content.get("text", "")[:500]
        elif content_type == "image":
            ocr = ""
            if state.get("image_result"):
                ocr = state["image_result"].get("ocr_text", "")
            return f"[image] {ocr[:200]}" if ocr else f"[image: {state.get('image_result', {}).get('basic_info', {}).get('size_bytes', 0)} bytes]"
        elif content_type == "audio":
            text = ""
            if state.get("audio_result"):
                text = state["audio_result"].get("transcribed_text", "")
            return f"[audio] {text[:300]}" if text else "[audio]"
        elif content_type == "video":
            text = ""
            if state.get("video_result"):
                text = state["video_result"].get("audio_text", "")
            return f"[video] {text[:300]}" if text else "[video]"
        return f"[{content_type}]"
