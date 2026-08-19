"""
TaskPlanner v2.0 — ReAct驱动的 Plan-and-Execute Agent

不是一次规划静态执行，而是:
  Plan → THINK → ACT → OBSERVE → THINK(RePlan?) → ACT → ... → DONE

ReAct 循环控制:
  THINK:   LLM分析当前执行状态, 决定继续/重规划/深潜/结束
  ACT:     执行一个步骤 (调用对应Agent分析)
  OBSERVE: 收集步骤结果, 评估置信度, 判断是否需要调整计划

终止条件:
  - 所有步骤完成且置信度达标
  - 达到最大步数 (MAX_STEPS=8)
  - LLM判定 DONE

技术参考:
  - Plan-and-Solve (Wang et al., 2024)
  - ReWOO (Xu et al., 2023): Reason Without Observation
  - LLMCompiler (Kim et al., 2024): Parallel Function Calling
  - ReAct (Yao et al., ICLR 2023): Reasoning + Acting
"""
import json
import time
import logging
import asyncio
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from common.api_clients import get_deepseek_model

logger = logging.getLogger(__name__)


class PlanStatus(Enum):
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    REPLAN = "REPLAN"
    DEEP_DIVE = "DEEP_DIVE"
    DONE = "DONE"
    FAILED = "FAILED"


class LoopAction(Enum):
    CONTINUE = "CONTINUE"
    REPLAN = "REPLAN"
    DEEP_DIVE = "DEEP_DIVE"
    DONE = "DONE"


@dataclass
class PlanStep:
    step_id: str
    agent: str
    action: str
    description: str
    input_key: str
    depends_on: list = field(default_factory=list)
    can_parallelize: bool = True
    priority: int = 5


@dataclass
class StepResult:
    step_id: str
    agent: str
    confidence: float
    violation_type: str
    risk_score: float
    reasoning: str = ""
    duration_ms: float = 0.0
    success: bool = True
    error: str = ""


THINK_PROMPT = """你是 Plan-and-Execute 内容审核系统的决策引擎。

你的任务是分析当前执行状态，决定下一步动作。

## 可用动作
- CONTINUE step_X: 当前置信度充足, 按计划执行下一个步骤
- REPLAN: 某步骤置信度过低(<0.5), 需要针对薄弱环节追加深度分析
- DONE: 所有必要步骤已完成, 可以输出最终结果

## 决策规则
1. 如果所有步骤置信度都 > 0.6 → DONE
2. 如果某步骤置信度 < 0.5 且该步骤 priority >= 7 → REPLAN
3. 如果还有待执行步骤 → CONTINUE
4. 如果已达最大步数 → DONE

## 当前计划状态
总步数: {total_steps}, 已完成: {completed_count}, 当前步: {current_step}
已完成步骤:
{completed_summary}

待执行步骤:
{pending_summary}

请只返回 JSON:
{{"action":"CONTINUE|REPLAN|DONE","target":"step_X","reason":"简短理由(30字内)"}}
"""

REPLAN_PROMPT = """你是内容审核系统的补救规划专家。

薄弱步骤: {weak_step_id} ({weak_agent})
置信度: {weak_confidence:.2f}, 阈值: 0.5
原因: {reason}

## 可用的补救手段
- react_agent: ReAct多步推理 (Thought→Action→Observation循环)
- deep_analysis: 深层语义分析 (LLM超长Prompt, 2000 tokens)
- cross_modal: 跨模态复核 (调用其他模态Agent交叉验证)
- more_rag: 扩充RAG检索 (top_k=10, 扩大检索范围)

## 任务
为此薄弱步骤设计1-2个补救步骤，步骤ID格式: {weak_step_id}_replan_1

只返回 JSON:
{{"steps":[{{"step_id":"...","agent":"...","action":"...","description":"...","input_key":"...","priority":9}}]}}
"""


class PlanAgent:
    """
    ReAct驱动的 Plan-and-Execute Agent

    内部循环:
      _think() → _act() → _observe() → 循环或结束

    使用示例:
      agent = PlanAgent()
      agent.set_llm_client(client)
      state = await agent.run(state)
    """

    MAX_STEPS = 8
    REPLAN_THRESHOLD = 0.5
    CONFIDENCE_TARGET = 0.6
    MAX_REPLANS = 2

    def __init__(self):
        self._llm_client = None

    def set_llm_client(self, client):
        self._llm_client = client

    # ================================================================
    # 主循环: run()
    # ================================================================

    async def run(self, state: dict) -> dict:
        """
        主 ReAct 循环入口 — 被 planner_node 调用

        Args:
            state: ModerationState (含 content, files, content_type等)

        Returns:
            更新后的 state (含 _plan_context)
        """
        t_start = time.time()

        # 1. 创建初始计划
        plan = self._create_heuristic_plan(state)
        ctx = self._init_context(plan)
        state["_plan_context"] = ctx

        logger.info(
            f"[PlanAgent] Starting ReAct loop: {len(plan)} steps, "
            f"max_steps={self.MAX_STEPS}"
        )

        # 2. ReAct 主循环
        loop_log = []

        for iteration in range(self.MAX_STEPS):
            ctx["current_iteration"] = iteration + 1

            # PHASE 1: THINK — 分析状态, 决定下一步
            action, target, reason = await self._think(state, ctx)

            loop_log.append({
                "iteration": iteration + 1,
                "phase": "THINK",
                "action": action.value if isinstance(action, LoopAction) else action,
                "target": target,
                "reason": reason,
            })
            logger.info(f"[PlanAgent] THINK #{iteration+1}: {action} → {target} ({reason})")

            if action == LoopAction.DONE:
                ctx["status"] = PlanStatus.DONE.value
                break

            elif action == LoopAction.REPLAN:
                ctx["status"] = PlanStatus.REPLAN.value
                if ctx.get("replan_count", 0) >= self.MAX_REPLANS:
                    logger.warning(f"[PlanAgent] Max replans ({self.MAX_REPLANS}) reached, forcing DONE")
                    ctx["status"] = PlanStatus.DONE.value
                    break
                ctx = await self._replan(state, ctx, reason)
                loop_log[-1]["replan_count"] = ctx.get("replan_count", 0)
                continue

            elif action == LoopAction.CONTINUE:
                ctx["status"] = PlanStatus.EXECUTING.value

                # PHASE 2: ACT — 执行目标步骤
                step_result = await self._act(state, ctx, target)

                loop_log.append({
                    "iteration": iteration + 1,
                    "phase": "ACT",
                    "step": target,
                    "confidence": step_result.confidence,
                    "violation_type": step_result.violation_type,
                    "duration_ms": step_result.duration_ms,
                })

                # PHASE 3: OBSERVE — 评估结果, 更新上下文
                evaluation = self._observe(ctx, step_result)

                loop_log.append({
                    "iteration": iteration + 1,
                    "phase": "OBSERVE",
                    "step": target,
                    "confidence": step_result.confidence,
                    "threshold_met": evaluation["threshold_met"],
                    "needs_replan": evaluation["needs_replan"],
                })

                if evaluation["needs_replan"]:
                    ctx["replan_triggered_by"] = {
                        "step": target,
                        "confidence": step_result.confidence,
                        "threshold": self.REPLAN_THRESHOLD,
                    }
            else:
                logger.warning(f"[PlanAgent] Unknown action: {action}, forcing DONE")
                ctx["status"] = PlanStatus.DONE.value
                break

        # 3. 记录循环日志
        elapsed = round((time.time() - t_start) * 1000)
        ctx["loop_log"] = loop_log
        ctx["total_duration_ms"] = elapsed

        logger.info(
            f"[PlanAgent] ReAct loop finished: "
            f"{len(ctx['completed_steps'])}/{len(plan)} steps done, "
            f"{ctx.get('replan_count', 0)} replans, "
            f"{elapsed}ms"
        )

        return state

    # ================================================================
    # THINK: 决策引擎
    # ================================================================

    async def _think(self, state: dict, ctx: dict) -> tuple:
        """
        分析当前状态, 决定下一步动作

        Returns: (LoopAction, target_step_id, reason)
        """
        # 规则优先: 快速决策, 避免不必要的 LLM 调用
        fast_decision = self._fast_think(ctx)
        if fast_decision:
            return fast_decision

        # LLM 辅助: 复杂状态需要深度分析
        if self._llm_client:
            try:
                return await self._llm_think(ctx)
            except Exception as e:
                logger.warning(f"[PlanAgent] LLM think failed: {e}")

        # 回退: 启发式决策
        return self._heuristic_think(ctx)

    def _fast_think(self, ctx: dict) -> Optional[tuple]:
        """快速规则决策 — 不调 LLM"""
        # 规则1: 还有未执行步骤 → 继续
        pending = [s for s in ctx["steps"] if s["step_id"] not in ctx["completed_steps"]]
        if pending:
            next_step = pending[0]
            return (LoopAction.CONTINUE, next_step["step_id"], "有未执行步骤，继续执行")

        # 规则2: 全部完成 → DONE
        return (LoopAction.DONE, "", "所有步骤已完成")

    async def _llm_think(self, ctx: dict) -> tuple:
        """LLM 深度分析决策"""
        # 构建已完成和待执行的摘要
        completed_summary = self._format_completed(ctx)
        pending = [s for s in ctx["steps"] if s["step_id"] not in ctx["completed_steps"]]
        pending_summary = "\n".join(
            f"  - {s['step_id']}: {s['agent']}.{s['action']} ({s['description'][:50]})"
            for s in pending
        ) if pending else "  (无)"

        prompt = THINK_PROMPT.format(
            total_steps=len(ctx["steps"]),
            completed_count=len(ctx["completed_steps"]),
            current_step=ctx.get("current_iteration", 0),
            completed_summary=completed_summary,
            pending_summary=pending_summary,
        )

        response = await self._llm_client.chat.completions.create(
            model=get_deepseek_model(),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=200,
        )
        data = json.loads(response.choices[0].message.content)

        action_str = data.get("action", "DONE").upper()
        target = data.get("target", "")
        reason = data.get("reason", "")

        try:
            action = LoopAction(action_str)
        except ValueError:
            action = LoopAction.DONE

        return (action, target, reason)

    def _heuristic_think(self, ctx: dict) -> tuple:
        """启发式决策 — LLM不可用时的回退"""
        pending = [s for s in ctx["steps"] if s["step_id"] not in ctx["completed_steps"]]
        if pending:
            return (LoopAction.CONTINUE, pending[0]["step_id"], "启发式: 继续执行待处理步骤")

        # 检查是否有低置信度步骤
        for step_id, result in ctx["step_results"].items():
            if result.get("confidence", 0) < self.REPLAN_THRESHOLD:
                step = self._find_step(ctx, step_id)
                if step and step.get("priority", 0) >= 7:
                    return (LoopAction.REPLAN, step_id, f"启发式: {step_id} 置信度{result['confidence']:.2f}低于阈值")

        return (LoopAction.DONE, "", "启发式: 所有步骤已完成")

    # ================================================================
    # ACT: 执行步骤
    # ================================================================

    async def _act(self, state: dict, ctx: dict, step_id: str) -> StepResult:
        """执行一个计划步骤"""
        step = self._find_step(ctx, step_id)
        if not step:
            return StepResult(
                step_id=step_id, agent="unknown",
                confidence=0.0, violation_type="none", risk_score=0.0,
                success=False, error=f"找不到步骤 {step_id}",
            )

        t0 = time.time()
        try:
            agent_name = step["agent"]
            # 根据 Agent 类型执行对应的分析
            # 注意: 实际的 Agent 调用由 LangGraph 节点处理,
            # PlanAgent 在这里标记当前步骤, 由工作流路由到对应节点
            result = self._simulate_step_result(state, step)
            result.duration_ms = round((time.time() - t0) * 1000)

            # 更新上下文
            ctx["completed_steps"].append(step_id)
            ctx["step_results"][step_id] = {
                "confidence": result.confidence,
                "violation_type": result.violation_type,
                "risk_score": result.risk_score,
                "agent": agent_name,
                "duration_ms": result.duration_ms,
            }
            ctx["current_step_index"] = ctx["steps"].index(step) + 1

            return result

        except Exception as e:
            return StepResult(
                step_id=step_id, agent=step.get("agent", "unknown"),
                confidence=0.0, violation_type="error", risk_score=0.0,
                duration_ms=round((time.time() - t0) * 1000),
                success=False, error=str(e)[:200],
            )

    def _simulate_step_result(self, state: dict, step: dict) -> StepResult:
        """从 state 中提取对应 Agent 的实际结果"""
        agent = step["agent"]
        result_key_map = {
            "text_agent": "text_result",
            "image_agent": "image_result",
            "audio_agent": "audio_result",
            "video_agent": "video_result",
            "file_agent": "file_results",
            "risk_agent": "final_risk",
        }

        key = result_key_map.get(agent)
        agent_result = (state.get(key) or {}) if key else {}

        confidence = agent_result.get("confidence", 0.0)
        vt = agent_result.get("violation_type", "none")
        risk = agent_result.get("risk_score", agent_result.get("overall_score", 0.0))

        # 如果对应的 Agent 还没执行, 返回默认值
        return StepResult(
            step_id=step["step_id"],
            agent=agent,
            confidence=confidence,
            violation_type=vt,
            risk_score=risk,
            reasoning=agent_result.get("reason", agent_result.get("reasoning", ""))[:200],
        )

    # ================================================================
    # OBSERVE: 评估结果
    # ================================================================

    def _observe(self, ctx: dict, step_result: StepResult) -> dict:
        """
        评估步骤执行结果

        Returns:
            {threshold_met, needs_replan, reason}
        """
        confidence = step_result.confidence
        priority = self._get_step_priority(ctx, step_result.step_id)

        threshold_met = confidence >= self.CONFIDENCE_TARGET
        needs_replan = (
            not threshold_met
            and priority >= 7
            and confidence < self.REPLAN_THRESHOLD
            and ctx.get("replan_count", 0) < self.MAX_REPLANS
        )

        return {
            "threshold_met": threshold_met,
            "needs_replan": needs_replan,
            "confidence": confidence,
            "priority": priority,
            "reason": (
                "ok" if threshold_met
                else f"置信度{confidence:.2f}不足" if needs_replan
                else f"置信度{confidence:.2f}偏低但不触发RePlan(priority={priority})"
            ),
        }

    # ================================================================
    # REPLAN: 动态调整计划
    # ================================================================

    async def _replan(self, state: dict, ctx: dict, reason: str) -> dict:
        """
        为薄弱步骤生成补救步骤, 动态追加到计划中
        """
        ctx["replan_count"] = ctx.get("replan_count", 0) + 1

        weak_step_id = ctx.get("replan_triggered_by", {}).get("step")
        if not weak_step_id:
            # 找置信度最低的步骤
            weakest = None
            lowest_conf = 1.0
            for sid, result in ctx["step_results"].items():
                if result.get("confidence", 0) < lowest_conf:
                    lowest_conf = result["confidence"]
                    weakest = sid
            weak_step_id = weakest or "unknown"

        weak_step = self._find_step(ctx, weak_step_id) or {}
        weak_agent = weak_step.get("agent", "unknown")

        logger.info(
            f"[PlanAgent] REPLAN #{ctx['replan_count']}: "
            f"weak_step={weak_step_id} ({weak_agent}), reason={reason[:50]}"
        )

        # LLM生成补救步骤
        if self._llm_client:
            try:
                new_steps = await self._llm_generate_remedial(ctx, weak_step_id, weak_agent, reason)
            except Exception as e:
                logger.warning(f"[PlanAgent] LLM replan failed: {e}")
                new_steps = self._heuristic_remedial(weak_step_id, weak_agent)
        else:
            new_steps = self._heuristic_remedial(weak_step_id, weak_agent)

        # 追加到计划末尾
        ctx["steps"].extend(new_steps)
        ctx["replan_history"] = ctx.get("replan_history", [])
        ctx["replan_history"].append({
            "replan_number": ctx["replan_count"],
            "weak_step": weak_step_id,
            "weak_agent": weak_agent,
            "reason": reason,
            "new_steps": [s["step_id"] for s in new_steps],
        })

        logger.info(
            f"[PlanAgent] RePlan: added {len(new_steps)} remedial steps "
            f"→ total steps now {len(ctx['steps'])}"
        )
        return ctx

    async def _llm_generate_remedial(self, ctx, weak_step_id, weak_agent, reason) -> list:
        """LLM生成补救步骤"""
        weak_result = ctx["step_results"].get(weak_step_id, {})
        confidence = weak_result.get("confidence", 0.4)

        prompt = REPLAN_PROMPT.format(
            weak_step_id=weak_step_id,
            weak_agent=weak_agent,
            weak_confidence=confidence,
            reason=reason,
        )

        response = await self._llm_client.chat.completions.create(
            model=get_deepseek_model(),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=300,
        )

        data = json.loads(response.choices[0].message.content)
        return data.get("steps", [])

    def _heuristic_remedial(self, weak_step_id: str, weak_agent: str) -> list:
        """启发式补救 — LLM不可用时的回退"""
        agent_remedy_map = {
            "text_agent": [
                {
                    "step_id": f"{weak_step_id}_replan_1",
                    "agent": "react_agent",
                    "action": "deep_analyze",
                    "description": "ReAct多步推理深度分析 (补救文本Agent低置信度)",
                    "input_key": "text",
                    "priority": 9,
                },
            ],
            "image_agent": [
                {
                    "step_id": f"{weak_step_id}_replan_1",
                    "agent": "image_agent",
                    "action": "deep_analyze",
                    "description": "图片上下文感知深度分析 (补救图片Agent低置信度)",
                    "input_key": "image",
                    "priority": 9,
                },
            ],
            "audio_agent": [
                {
                    "step_id": f"{weak_step_id}_replan_1",
                    "agent": "audio_agent",
                    "action": "deep_analyze",
                    "description": "语音深层语义分析 (补救音频Agent低置信度)",
                    "input_key": "audio",
                    "priority": 9,
                },
            ],
        }
        return agent_remedy_map.get(weak_agent, [
            {
                "step_id": f"{weak_step_id}_replan_1",
                "agent": "debate",
                "action": "cross_check",
                "description": f"跨Agent复核 (补救{weak_agent}低置信度)",
                "input_key": weak_agent.replace("_agent", ""),
                "priority": 9,
            },
        ])

    # ================================================================
    # 辅助函数
    # ================================================================

    def _create_heuristic_plan(self, state: dict) -> List[dict]:
        """为当前状态创建初始执行计划 (启发式, 不调LLM)"""
        content_type = state.get("content_type", "text")
        content = state.get("content") or {}
        files = content.get("files", [])

        steps = []
        sid = 0

        # 多模态文件 → 先解析
        if files:
            sid += 1
            steps.append(self._make_step(sid, "file_agent", "parse_files", f"解析{len(files)}个文件", "files", 9, []))

        file_dep = [f"step_{sid}"] if files and sid > 0 else []

        # 文本分析
        if content.get("text") or (state.get("file_results") or {}).get("combined_text"):
            sid += 1
            steps.append(self._make_step(sid, "text_agent", "analyze_text", "文本语义审核", "text", 8, file_dep))

        # 图片分析 (可与文本并行)
        has_images = any(f.get("mime_type", "").startswith("image/") for f in files) or bool(content.get("image"))
        if has_images:
            sid += 1
            steps.append(self._make_step(sid, "image_agent", "analyze_images", "图片内容审核", "image", 7, file_dep))

        # 音频分析
        has_audio = any(f.get("mime_type", "").startswith("audio/") for f in files) or bool(content.get("audio"))
        if has_audio:
            sid += 1
            steps.append(self._make_step(sid, "audio_agent", "analyze_audio", "语音内容审核", "audio", 7, file_dep))

        # 综合评估
        sid += 1
        analysis_deps = [s["step_id"] for s in steps if s["agent"] != "file_agent"]
        steps.append(self._make_step(sid, "risk_agent", "assess_risk", "综合风险评估", "final_risk", 10, analysis_deps))

        return steps

    def _make_step(self, idx, agent, action, desc, input_key, priority, depends_on) -> dict:
        return {
            "step_id": f"step_{idx}",
            "agent": agent,
            "action": action,
            "description": desc,
            "input_key": input_key,
            "depends_on": depends_on,
            "can_parallelize": agent != "risk_agent",
            "priority": priority,
        }

    def _init_context(self, plan: List[dict]) -> dict:
        """初始化执行上下文 (深拷贝plan列表, 避免修改原引用)"""
        import copy
        return {
            "plan_id": f"plan_{int(time.time())}",
            "steps": copy.deepcopy(plan),
            "current_step_index": 0,
            "completed_steps": [],
            "step_results": {},
            "replan_history": [],
            "replan_count": 0,
            "current_iteration": 0,
            "status": PlanStatus.PLANNING.value,
            "loop_log": [],
        }

    def _find_step(self, ctx: dict, step_id: str) -> Optional[dict]:
        for s in ctx["steps"]:
            if s["step_id"] == step_id:
                return s
        return None

    def _get_step_priority(self, ctx: dict, step_id: str) -> int:
        step = self._find_step(ctx, step_id)
        return step.get("priority", 5) if step else 5

    def _format_completed(self, ctx: dict) -> str:
        if not ctx["step_results"]:
            return "  (尚无)"
        lines = []
        for sid, result in ctx["step_results"].items():
            conf = result.get("confidence", 0)
            vt = result.get("violation_type", "?")
            icon = "✅" if conf >= self.CONFIDENCE_TARGET else "⚠️" if conf >= self.REPLAN_THRESHOLD else "❌"
            lines.append(f"  {icon} {sid}: {vt} (conf={conf:.2f})")
        return "\n".join(lines)

    def get_summary(self, state: dict) -> dict:
        """从 state 中提取计划摘要供前端展示"""
        ctx = state.get("_plan_context") or {}
        return {
            "plan_id": ctx.get("plan_id", ""),
            "total_steps": len(ctx.get("steps", [])),
            "completed_steps": len(ctx.get("completed_steps", [])),
            "status": ctx.get("status", "unknown"),
            "replan_count": ctx.get("replan_count", 0),
            "loop_log": ctx.get("loop_log", []),
            "step_results": ctx.get("step_results", {}),
            "replan_history": ctx.get("replan_history", []),
        }


# 全局单例
_plan_agent: Optional[PlanAgent] = None


def get_plan_agent() -> PlanAgent:
    global _plan_agent
    if _plan_agent is None:
        _plan_agent = PlanAgent()
    return _plan_agent


# 兼容旧接口
def get_planner() -> PlanAgent:
    return get_plan_agent()
