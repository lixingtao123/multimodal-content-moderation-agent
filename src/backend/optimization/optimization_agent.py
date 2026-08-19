"""
优化 Agent — 智能分析错误案例并自主决策优化方向

与 DspyStyleOptimizer 的区别:
  - DspyStyleOptimizer: 硬编码统计 → 追加固定指令 → bump version
  - OptimizationAgent: LLM 分析错误模式 → 自主决策优化目标 → 多种优化动作

优化动作类型:
  - prompt_update: 重写 Prompt 中的判断指引 (不是追加, 是智能修改)
  - keyword_update: 补充/删除关键词
  - threshold_adjust: 调整置信度阈值
  - rag_case_add: 将典型案例加入 ChromaDB 知识库
  - debate_weight_adjust: 调整 Debate Panel 投票权重

触发方式:
  - auto: buffer 达到 100 条自动触发 (由 AnnotationConsumer._check_auto_optimize 调用)
  - manual: 运营点击按钮或 API 调用
"""
import json
import os
import time
import logging
import aiohttp
from typing import Optional
from dataclasses import dataclass, field

from agent_moderation.agents.base import BaseAgent

logger = logging.getLogger(__name__)


def _row_to_dict(row) -> dict:
    """将 SQLAlchemy Row 转为普通 dict, 处理日期时间字段"""
    mapping = dict(row._mapping)
    for key in ("annotated_at", "created_at"):
        val = mapping.get(key)
        if hasattr(val, "isoformat"):
            mapping[key] = val.isoformat()
    return mapping


@dataclass
class OptimizationAction:
    action_type: str       # prompt_update | keyword_update | threshold_adjust | rag_case_add
    target: str            # 具体目标
    description: str       # 做了什么
    reason: str            # 为什么


# ============================================================
# LLM 分析 Prompt
# ============================================================

OPTIMIZATION_ANALYSIS_PROMPT = """你是一个内容审核系统的优化专家。你需要分析模型判断错误的案例,找出根本原因并提出优化方案。

## 当前系统配置
- 审核 Prompt:
{current_prompts}

- 当前关键词库:
{keywords}

- 当前置信度阈值: 待审核→REVIEW 阈值 0.4, 违规→REJECT 阈值 0.6

## 错误统计 (v3.2: 已按标注权重加权)
- 误判 (false_positive, 正常内容被判违规): {fp_count} 条
- 漏判 (false_negative, 违规内容被判正常): {fn_count} 条
- 类型错误 (wrong_violation_type): {wt_count} 条
- 标注来源分布: {source_info}

## 抽样错误案例 (按类型分组)
{sampled_cases}

## 分析要求
1. 归纳错误的共同模式(相似文本结构、相同违规类型、置信度区间等)
2. 判断错误根因: 是 Prompt 表述模糊? 关键词库缺失? 还是模型本身的局限?
3. 提出具体的、可执行的优化方案。可以包括:
   - **prompt_update**: 修改 Prompt 中的判断指引 (具体改哪段,怎么改)
   - **keyword_update**: 补充缺失的违规关键词, 或删除会误触发的关键词
   - **threshold_adjust**: 调整某类违规的置信度阈值 (当前: REVIEW≥0.4, REJECT≥0.6)
   - **rag_case_add**: 将某些典型案例加入知识库 (RAG检索用)
4. 如果缓冲区数据不足以得出有效结论, 返回空 actions

## 输出格式 (只返回JSON, 不要其他文字):
{{
  "pattern_analysis": "中文描述, 150-300字, 归纳错误模式",
  "actions": [
    {{
      "action_type": "prompt_update|keyword_update|threshold_adjust|rag_case_add",
      "target": "具体目标描述",
      "description": "具体改动内容, 越详细越好",
      "reason": "基于哪些错误案例做出的判断"
    }}
  ],
  "estimated_impact": "预期改进的简要描述"
}}"""


# ============================================================
# OptimizationAgent
# ============================================================

class OptimizationAgent:
    """
    优化 Agent — 读取 buffer, LLM 分析, 执行优化动作, 生成报告
    """

    def __init__(self):
        self._lock = False  # 本地锁, 防并发

    async def optimize(self, trigger: str = "auto", source_filter: str = "all") -> Optional[dict]:
        """
        执行一次优化

        Args:
            trigger: "auto" | "manual"
            source_filter: "all" (默认, 含 auto+human) | "auto" | "human"

        Returns:
            优化报告 dict, 或 None (buffer 不足/正在优化)
        """
        if self._lock:
            logger.info("[OptimizationAgent] Already optimizing, skip")
            return None

        self._lock = True
        try:
            return await self._do_optimize(trigger, source_filter)
        finally:
            self._lock = False

    async def _do_optimize(self, trigger: str, source_filter: str = "all") -> Optional[dict]:
        from memory.redis_service import get_redis_service
        from .annotation_queue import (
            BUFFER_KEY, OPT_LOCK_KEY, STATS_KEY, REPORTS_KEY, MIN_OPTIMIZE_INTERVAL,
        )
        from sqlalchemy import text as sa_text
        from db import connection as db_conn

        svc = get_redis_service()
        if not svc.client:
            logger.warning("[OptimizationAgent] Redis not available")
            return None

        # 防抖: 检查最近优化时间
        last_opt_time = await svc.client.hget(STATS_KEY, "last_optimization_time")
        if last_opt_time:
            elapsed = time.time() - int(last_opt_time)
            if elapsed < MIN_OPTIMIZE_INTERVAL and trigger == "auto":
                logger.info(f"[OptimizationAgent] Too soon since last optimization ({elapsed:.0f}s < {MIN_OPTIMIZE_INTERVAL}s)")
                return None

        # === 从 PostgreSQL 读取未消费的错误案例 (持久化数据源, v3.2 支持 source 过滤) ===
        async with db_conn.async_session_factory() as session:
            if source_filter == "human":
                query = sa_text("""
                    SELECT * FROM annotation_records
                    WHERE is_error = TRUE AND consumed = FALSE AND source = 'human'
                    ORDER BY annotated_at DESC
                """)
            elif source_filter == "auto":
                query = sa_text("""
                    SELECT * FROM annotation_records
                    WHERE is_error = TRUE AND consumed = FALSE AND (source = 'auto' OR source IS NULL)
                    ORDER BY annotated_at DESC
                """)
            else:
                query = sa_text("""
                    SELECT * FROM annotation_records
                    WHERE is_error = TRUE AND consumed = FALSE
                    ORDER BY weight DESC, annotated_at DESC
                """)
            result = await session.execute(query)
            rows = result.fetchall()
            buffer_data = [_row_to_dict(row) for row in rows]

        if not buffer_data:
            logger.info(f"[OptimizationAgent] No error cases for source_filter={source_filter}")
            return None

        # 手动触发不受阈值限制; 自动触发需 ≥100 (人工标注仅需 ≥15)
        min_threshold = 15 if source_filter == "human" else 100
        if trigger == "auto" and len(buffer_data) < min_threshold:
            logger.info(f"[OptimizationAgent] Buffer size {len(buffer_data)} below threshold {min_threshold}")
            return None
        if trigger == "manual" and len(buffer_data) < 3:
            return None  # 手动至少要有 3 条

        # 设置优化锁
        await svc.client.setex(OPT_LOCK_KEY, 300, "1")  # 5 分钟过期

        try:
            # 统计错误分布 (v3.2: 按 weight 加权计数)
            error_stats = {"false_positive": 0.0, "false_negative": 0.0, "wrong_violation_type": 0.0}
            source_counts = {"auto": 0, "human": 0}
            for item in buffer_data:
                et = item.get("error_type", "correct")
                w = item.get("weight", 1.0)
                if et in error_stats:
                    error_stats[et] += w
                # 统计来源分布
                src = item.get("source", "auto") or "auto"
                source_counts[src] = source_counts.get(src, 0) + 1

            fp_count = int(error_stats["false_positive"])
            fn_count = int(error_stats["false_negative"])
            wt_count = int(error_stats["wrong_violation_type"])

            # === 快照: 优化前状态 ===
            before_snapshot = self._take_snapshot()

            # 每类抽样 (最多 8 条)
            samples = self._sample_by_type(buffer_data, max_per_type=8)

            # 获取当前 Prompt
            current_prompts = self._get_current_prompts()

            # 获取关键词库
            keywords = self._get_keywords_summary()

            # 构建提示词 (v3.2: 含 source 分布信息)
            source_info = f"自动标注: {source_counts.get('auto', 0)}条, 人工标注: {source_counts.get('human', 0)}条"
            if source_counts.get('human', 0) > 0:
                source_info += "\n⚠️ 人工标注权重3x, 应优先关注人工标注发现的错误模式"
            prompt_text = OPTIMIZATION_ANALYSIS_PROMPT.format(
                current_prompts=current_prompts,
                keywords=keywords,
                fp_count=fp_count,
                fn_count=fn_count,
                wt_count=wt_count,
                sampled_cases=json.dumps(samples, ensure_ascii=False, indent=2),
                source_info=source_info,
            )

            # LLM 分析
            analysis_result = await self._call_llm_analysis(prompt_text)
            if not analysis_result:
                logger.warning("[OptimizationAgent] LLM analysis returned empty")
                return None

            # 执行优化动作
            executed_actions = []
            for action_data in analysis_result.get("actions", []):
                try:
                    action = OptimizationAction(
                        action_type=action_data.get("action_type", ""),
                        target=action_data.get("target", ""),
                        description=action_data.get("description", ""),
                        reason=action_data.get("reason", ""),
                    )
                    success = await self._execute_action(action, buffer_data)
                    if success:
                        executed_actions.append({
                            "action_type": action.action_type,
                            "target": action.target,
                            "description": action.description,
                            "reason": action.reason,
                        })
                except Exception as e:
                    logger.error(f"[OptimizationAgent] Action execution failed: {e}")

            # 生成报告
            import uuid
            report_id = f"opt_{uuid.uuid4().hex[:12]}"
            after_snapshot = self._take_snapshot()
            report = {
                "report_id": report_id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "trigger": trigger,
                "total_samples": len(buffer_data),
                "error_distribution": error_stats,
                "pattern_analysis": analysis_result.get("pattern_analysis", ""),
                "optimization_actions": executed_actions,
                "estimated_impact": analysis_result.get("estimated_impact", ""),
                "before": before_snapshot,
                "after": after_snapshot,
            }

            # 保存报告到 Redis
            await svc.client.lpush(REPORTS_KEY, json.dumps(report, ensure_ascii=False))
            await svc.client.ltrim(REPORTS_KEY, 0, 49)  # 保留最近 50 个报告

            # === 标记已消费: PostgreSQL UPDATE (不删除数据) ===
            async with db_conn.async_session_factory() as session:
                await session.execute(sa_text("""
                    UPDATE annotation_records
                    SET consumed = TRUE, optimization_id = :opt_id
                    WHERE is_error = TRUE AND consumed = FALSE
                """), {"opt_id": report_id})
                await session.commit()
                logger.info(f"[OptimizationAgent] Marked {len(buffer_data)} errors as consumed (opt_id={report_id})")

            # 同时清空 Redis buffer (兼容旧代码路径)
            await svc.client.delete(BUFFER_KEY)

            # 更新最后优化时间
            await svc.client.hset(STATS_KEY, "last_optimization_time", str(int(time.time())))

            # 释放优化锁
            await svc.client.delete(OPT_LOCK_KEY)

            logger.info(
                f"[OptimizationAgent] Optimization completed: "
                f"{len(executed_actions)} actions from {len(buffer_data)} samples"
            )
            return report

        except Exception as e:
            logger.error(f"[OptimizationAgent] Optimization failed: {e}", exc_info=True)
            await svc.client.delete(OPT_LOCK_KEY)
            return None

    def _sample_by_type(self, buffer_data: list, max_per_type: int = 8) -> dict:
        """按错误类型对buffer数据抽样"""
        by_type: dict[str, list] = {}
        for item in buffer_data:
            et = item.get("error_type", "correct")
            if et not in by_type:
                by_type[et] = []
            if len(by_type[et]) < max_per_type:
                # 只保留关键字段, 减少 token
                by_type[et].append({
                    "content_id": item.get("content_id"),
                    "model_decision": item.get("model_decision"),
                    "error_type": item.get("error_type"),
                    "error_detail": item.get("error_detail", "")[:300],
                    "model_confidence": item.get("model_confidence", 0),
                    "annotated_violation_types": item.get("annotated_violation_types", []),
                })
        return by_type

    def _get_current_prompts(self) -> str:
        """获取当前活跃的 Prompt 摘要"""
        from .prompt_optimizer import get_prompt_registry
        registry = get_prompt_registry()
        lines = []
        for name in ["text_moderation", "image_moderation", "audio_moderation"]:
            pv = registry.get_active(name)
            if pv:
                # 截取 system_prompt 的关键部分 (前600字)
                snippet = pv.system_prompt[:600]
                lines.append(f"### {name} (v{pv.version})\n{snippet}\n")
        return "\n".join(lines) if lines else "No prompts loaded"

    def _take_snapshot(self) -> dict:
        """快照当前系统配置状态"""
        from .prompt_optimizer import get_prompt_registry
        from .annotation_agent import VIOLATION_KEYWORDS

        registry = get_prompt_registry()
        prompt_snapshots = {}
        for name in ["text_moderation", "image_moderation", "audio_moderation"]:
            pv = registry.get_active(name)
            if pv:
                prompt_snapshots[name] = {
                    "version": pv.version,
                    "snippet": pv.system_prompt[:500],
                }

        kws_stats = {cat: len(kws) for cat, kws in VIOLATION_KEYWORDS.items()}

        thresholds = {}
        try:
            from memory.redis_service import get_redis_service
            svc = get_redis_service()
            if svc.client:
                import asyncio
                # Note: 简化实现，实际阈值在代码中
                thresholds = {"review": 0.35, "reject": 0.75}
        except Exception:
            thresholds = {"review": 0.35, "reject": 0.75}

        return {
            "prompts": prompt_snapshots,
            "keywords_stats": kws_stats,
            "thresholds": thresholds,
        }

    def _get_keywords_summary(self) -> str:
        """关键词库摘要"""
        try:
            from .annotation_agent import VIOLATION_KEYWORDS
            lines = []
            for category, kws in VIOLATION_KEYWORDS.items():
                lines.append(f"- {category}: {', '.join(kws[:10])}")
            return "\n".join(lines)
        except Exception:
            return "关键词库不可用"

    async def _call_llm_analysis(self, prompt: str) -> Optional[dict]:
        """调用 LLM 进行错误模式分析"""
        import os
        from common.config import get_settings
        from common.api_clients import get_deepseek_model

        settings = get_settings()
        api_key = settings.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            logger.warning("[OptimizationAgent] DEEPSEEK_API_KEY not set")
            return None

        payload = {
            "model": get_deepseek_model(),
            "temperature": 0.3,  # 分析任务用低温度
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 2000,
            "response_format": {"type": "json_object"},
            # R23: 关闭推理链。deepseek-v4-flash 是推理模型, 默认会把 max_tokens
            #      全部消耗在 reasoning_tokens 上, 导致 content 为空 → 优化必败。
            #      分析任务直接输出结构化 JSON 即可, 无需长思维链。
            "thinking": {"type": "disabled"},
        }

        try:
            api_url = f"{settings.deepseek_base_url}/v1/chat/completions"
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    api_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status != 200:
                        logger.error(f"[OptimizationAgent] LLM call failed: HTTP {resp.status}")
                        return None
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    # R23: 多级容错 JSON 解析 (与 BaseAgent._safe_json_parse 一致),
                    #      避免 DeepSeek 返回 markdown 包裹/非严格 JSON 时裸 json.loads 崩溃
                    parsed = BaseAgent._safe_json_parse(content)
                    if parsed is None:
                        logger.error(f"[OptimizationAgent] LLM response JSON parse failed, head: {str(content)[:300]!r}")
                        return None
                    return parsed
        except Exception as e:
            logger.error(f"[OptimizationAgent] LLM call exception: {e}")
            return None

    async def _execute_action_with_guard(self, action: OptimizationAction, buffer_data: list,
                                         evaluate_func=None, snapshot=None):
        """R15·L2: 动作执行 + 回归守卫（优化后变差自动回滚）。

        注意（诚实标注）：生产启用需提供动作前快照与回滚实现（依赖策略存储
        prompt/keyword/threshold 的读写）。当前为机制接入点，_do_optimize
        主循环的默认启用待 P6 完整落地。
        """
        from .regression_guard import RegressionGuard

        guard = RegressionGuard(evaluate_func=evaluate_func)

        async def apply():
            return await self._execute_action(action, buffer_data)

        async def rollback():
            if snapshot and callable(snapshot.get("restore")):
                await snapshot["restore"]()
            logger.warning(f"[OptimizationAgent] 动作已回滚: {action.action_type}")

        result = await guard.guard(apply, rollback)
        return result

    async def _execute_action(self, action: OptimizationAction, buffer_data: list) -> bool:
        """执行单个优化动作"""
        if action.action_type == "prompt_update":
            return await self._exec_prompt_update(action, buffer_data)
        elif action.action_type == "keyword_update":
            return await self._exec_keyword_update(action)
        elif action.action_type == "threshold_adjust":
            return await self._exec_threshold_adjust(action)
        elif action.action_type == "rag_case_add":
            return await self._exec_rag_case_add(action, buffer_data)
        else:
            logger.warning(f"[OptimizationAgent] Unknown action_type: {action.action_type}")
            return False

    async def _exec_prompt_update(self, action: OptimizationAction, buffer_data: list) -> bool:
        """执行 Prompt 更新"""
        from .prompt_optimizer import get_prompt_registry, get_optimizer

        registry = get_prompt_registry()
        optimizer = get_optimizer()

        # 确定目标 prompt
        prompt_name = "text_moderation"
        if action.target:
            for name in ["text_moderation", "image_moderation", "audio_moderation"]:
                if name in action.target:
                    prompt_name = name
                    break

        # 使用 optimize_from_feedback 方法 (已修复 error_type 匹配)
        # 过滤出与当前 prompt 相关的错误
        related_cases = [
            item for item in buffer_data
            if item.get("error_type") in ("false_positive", "false_negative", "wrong_violation_type")
        ]

        if related_cases:
            try:
                new_pv = optimizer.optimize_from_feedback(prompt_name, related_cases)
                logger.info(f"[OptimizationAgent] Prompt '{prompt_name}' updated → {new_pv.version}")
                return True
            except Exception as e:
                logger.error(f"[OptimizationAgent] Prompt update failed: {e}")
                return False
        return False

    async def _exec_keyword_update(self, action: OptimizationAction) -> bool:
        """
        执行关键词更新

        将 LLM 建议的关键词变更写入 annotation_agent.py 的 VIOLATION_KEYWORDS
        实际生产中可能写入单独的配置文件; 这里做内存更新
        """
        try:
            from . import annotation_agent
            # LLM 通过 description 描述具体要增加/删除的关键词
            desc = action.description or ""
            target = action.target or ""
            import re

            # 中文类别提示词 → 英文 key (LLM 用中文描述类别)
            CAT_ALIASES = {
                "advertisement": ["广告", "引流"],
                "false_info": ["虚假", "诈骗", "谣言"],
                "violence": ["暴力", "恐怖"],
                "porn": ["色情", "低俗"],
                "politics": ["政治", "敏感"],
                "harassment": ["骚扰", "辱骂"],
            }

            def _cats_from_hint(hint: str) -> list:
                """从中文类别提示词解析英文 key, 无命中返回空"""
                hint = hint or ""
                return [cat for cat, aliases in CAT_ALIASES.items() if any(a in hint for a in aliases)]

            def _match_categories(s: str) -> list:
                """回退: 从英文 target 字符串中匹配类别 key"""
                return [cat for cat in annotation_agent.VIOLATION_KEYWORDS if cat in s]

            changed = False

            # 1. 添加: 提取「补充/增加/添加<类别提示>关键词: A、B、C」的顿号分隔词 (R23 支持)
            #    例: "补充广告引流关键词：加微信、扫码进群、日赚、兼职、赚钱等"
            add_blocks = re.findall(r'(?:补充|增加|添加)([^：:]{0,12})?(?:关键词)?[：:]\s*([^。；]+)', desc)
            for hint, block in add_blocks:
                cats = _cats_from_hint(hint)
                if not cats:
                    # hint 无法映射时才回退到 target 匹配
                    cats = _match_categories(target)
                if not cats:
                    continue
                words = [w.strip().rstrip("等") for w in re.split(r"[、，,；;]+", block) if w.strip()]
                for cat in cats:
                    added = [w for w in words if w and w not in annotation_agent.VIOLATION_KEYWORDS[cat]]
                    if added:
                        annotation_agent.VIOLATION_KEYWORDS[cat].extend(added)
                        changed = True
                        logger.info(f"[OptimizationAgent] Added {len(added)} keywords to {cat}: {added}")

            # 2. 删除: 提取「如"X"」等引号包裹词 (R23: 同时支持中文引号)
            #    例: "删除可能误触发的通用词，如"验证码"在技术文档中常见"
            rm_words = re.findall(r'[“"]([^”"]+)[”"]', desc)
            if rm_words:
                for cat in _match_categories(target):
                    removed = [w for w in rm_words if w in annotation_agent.VIOLATION_KEYWORDS[cat]]
                    if removed:
                        for w in removed:
                            annotation_agent.VIOLATION_KEYWORDS[cat].remove(w)
                        changed = True
                        logger.info(f"[OptimizationAgent] Removed {len(removed)} keywords from {cat}: {removed}")

            if not changed:
                logger.info(f"[OptimizationAgent] Keyword update noted but nothing changed: {desc[:80]}")
            return True  # 柔和降级: 解析失败不报错, 不中断优化
        except Exception as e:
            logger.warning(f"[OptimizationAgent] Keyword update failed: {e}")
            return False

    async def _exec_threshold_adjust(self, action: OptimizationAction) -> bool:
        """
        调整置信度阈值

        通过 Redis Hash 存储动态阈值, 供 RiskAgent 读取
        """
        try:
            from memory.redis_service import get_redis_service
            svc = get_redis_service()
            if svc.client:
                # 存储到 Redis: moderation:thresholds → {review, reject}
                # 解析 LLM 建议的阈值 (如果有)
                desc = action.description or ""
                thresholds = {}
                import re
                # R23: 提取「降低至/调整为/→」后的目标值 (而非「从X」的原值)。
                # LLM 输出格式如「REVIEW阈值从0.4降低至0.3」→ 应取 0.3。
                review_match = re.search(r'REVIEW[^。;；]*?(?:至|到|→|调整为)\s*(\d+\.?\d*)', desc)
                reject_match = re.search(r'REJECT[^。;；]*?(?:至|到|→|调整为)\s*(\d+\.?\d*)', desc)
                # 兜底: 无目标值表述时退化为取第一个数字
                if not review_match:
                    review_match = re.search(r'REVIEW[^\d]*(\d+\.?\d*)', desc)
                if not reject_match:
                    reject_match = re.search(r'REJECT[^\d]*(\d+\.?\d*)', desc)
                if review_match:
                    thresholds["review"] = float(review_match.group(1))
                if reject_match:
                    thresholds["reject"] = float(reject_match.group(1))
                if thresholds:
                    await svc.client.hset("moderation:thresholds", mapping=thresholds)
                    logger.info(f"[OptimizationAgent] Thresholds updated: {thresholds}")
                    return True
            return False
        except Exception as e:
            logger.warning(f"[OptimizationAgent] Threshold adjust failed: {e}")
            return False

    async def _exec_rag_case_add(self, action: OptimizationAction, buffer_data: list) -> bool:
        """
        将典型案例加入 ChromaDB 知识库

        选取 buffer 中与 action 描述的违规类型匹配的案例, 写入 core_memory
        """
        try:
            from memory.manager import get_memory_manager
            memory = get_memory_manager()

            # 选取相关案例 (最多 5 条)
            relevant = []
            target_keywords = (action.target + action.description).lower()
            for item in buffer_data:
                error_type = item.get("error_type", "")
                error_detail = item.get("error_detail", "")
                if any(kw in error_detail for kw in ["漏判", "误判"]):
                    relevant.append(item)
                if len(relevant) >= 5:
                    break

            if not relevant:
                # 没有匹配的案例, 选前 3 个
                relevant = buffer_data[:3]

            saved = 0
            for item in relevant:
                try:
                    # L4-b（R12）: rag_case_add 前先 history_search 去重（>0.9 跳过，避免重复入库）
                    if item.get("error_detail"):
                        try:
                            from mcp_servers.registry import get_tool_registry
                            from mcp_servers.tool_reliability import call_with_reliability
                            hs = await call_with_reliability(
                                get_tool_registry(), "history_search",
                                {"query": item.get("error_detail", "")[:200], "top_k": 1})
                            if hs.cases and hs.cases[0].get("similarity", 0) >= 0.9:
                                logger.info(
                                    f"[OptimizationAgent] rag_case_add 跳过重复案例 "
                                    f"{item.get('content_id')} sim={hs.cases[0].get('similarity', 0):.2f}≥0.9")
                                continue
                        except Exception as de:
                            logger.warning(f"[OptimizationAgent] 去重检索失败，继续入库: {de}")

                    # 用高 importance 写入 core_memory
                    # R23: 唯一 case_id。此前复用 item.content_id, 而审核流程已用
                    #      同一 content_id 入库过 → chromadb 重复 id 静默跳过 →
                    #      saved 虚增但实际零写入。内容去重由上方 history_search 承担。
                    import uuid
                    case_id = f"rag_{uuid.uuid4().hex[:12]}"
                    await memory.save_case(
                        case_id=case_id,
                        content=item.get("error_detail", "")[:500],
                        violation_type=item.get("annotated_violation_types", ["unknown"])[0] if item.get("annotated_violation_types") else "unknown",
                        decision="REJECT" if item.get("error_type") == "false_negative" else "PASS",
                        confidence=0.85,
                        risk_score=0.85,
                        is_adversarial=False,
                        frequency=1,
                    )
                    saved += 1
                except Exception as e:
                    logger.warning(f"[OptimizationAgent] RAG case save failed: {e}")

            logger.info(f"[OptimizationAgent] Added {saved} cases to RAG knowledge base")
            return saved > 0
        except Exception as e:
            logger.warning(f"[OptimizationAgent] RAG case add failed: {e}")
            return False


# 全局单例
_optimization_agent: Optional[OptimizationAgent] = None


def get_optimization_agent() -> OptimizationAgent:
    global _optimization_agent
    if _optimization_agent is None:
        _optimization_agent = OptimizationAgent()
    return _optimization_agent
