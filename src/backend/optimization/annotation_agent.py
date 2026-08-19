"""
标注 Agent — 独立审核结果校验

对每次审核结果做三视角交叉验证:
  ① 规则引擎复核 (本地,零延迟)
  ② LLM 独立审核 (差异化 prompt + temperature)
  ③ 语义矛盾检测 (violation_type vs reason 自洽性)

三方投票裁决 → AnnotationResult (is_error + 详细错误原因)

设计原则:
  - 与审核并行,不阻塞
  - 规则引擎先过滤: 明显的正确判断跳过 LLM (节省 token)
  - 只有模型判定与标注不一致时才标记为错误
"""
import json
import time
import logging
import re
from typing import Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


# ============================================================
# 数据模型
# ============================================================

@dataclass
class AnnotationInput:
    """标注输入 — 从 Redis 队列消费"""
    content_id: str
    content_type: str           # text / image / audio / video
    annotation_input: str       # 可用于独立判断的文本
    model_decision: str         # PASS / REVIEW / REJECT
    model_confidence: float
    model_violation_types: list = field(default_factory=list)
    model_reason: str = ""
    model_risk_score: float = 0.0
    timestamp: str = ""


@dataclass
class AnnotationResult:
    """标注结果"""
    content_id: str
    is_error: bool              # 模型是否判断错误
    error_type: str             # false_positive / false_negative / wrong_violation_type / correct
    error_detail: str           # 详细错误原因 (中文, 100-300字)
    rule_verdict: str           # violation / normal / uncertain
    rule_detail: str = ""       # 规则引擎判定详情
    llm_verdict: str = ""       # violation / normal / uncertain (如果调用了LLM)
    llm_reason: str = ""        # LLM 独立审核理由
    contradiction_flag: bool = False  # 语义矛盾标记
    annotated_violation_types: list = field(default_factory=list)
    annotated_confidence: float = 0.0
    processing_time_ms: float = 0.0
    annotated_at: str = ""      # 标注时间 (ISO 8601 UTC)
    # v3.2: 标注来源和权重 (统一人工和自动标注存储)
    source: str = "auto"        # "auto" (AnnotationAgent) | "human" (人工标注)
    weight: float = 1.0         # auto=1.0, human=3.0
    reviewer_id: str = ""       # 人工标注人员ID (human时填写)
    human_corrected_json: dict = field(default_factory=dict)  # 人工修改后的JSON结果
    # 模型原始判定信息 (用于详情展示)
    model_decision: str = ""
    model_confidence: float = 0.0
    model_violation_types: list = field(default_factory=list)
    model_reason: str = ""
    model_risk_score: float = 0.0
    content_type: str = ""      # 内容类型
    annotation_input: str = ""  # 用于标注的原始输入文本
    # 规则引擎详细信息
    rule_matched_keywords: list = field(default_factory=list)
    rule_matched_rules: list = field(default_factory=list)
    rule_whitelist_hit: bool = False
    rule_adversarial_hit: bool = False
    # 是否调用了 LLM
    llm_called: bool = False
    # L4-a（R12）: 工具视角复核证据（keyword_check/history_search 结果）
    tool_evidence: dict = field(default_factory=dict)


# ============================================================
# 规则引擎 — 本地关键词/正则检测
# ============================================================

# 违规关键词库 (按类别)
VIOLATION_KEYWORDS: dict[str, list[str]] = {
    "violence": [
        "杀人", "砍死", "弄死", "炸掉", "枪击", "杀死", "打死",
        "灭口", "屠杀", "行刑", "处决", "处死", "斩首",
        "炸弹制作", "制作炸弹", "如何制造", "武器制作",
        "恐怖袭击", "恐怖分子", "圣战", "自杀式袭击",
    ],
    "porn": [
        "裸聊", "裸照", "裸体", "色情", "成人影片", "成人内容",
        "私密视频", "艳照", "不雅视频", "性暗示", "一夜情",
        "约炮", "嫖娼", "卖淫", "招嫖", "外围女",
        "福利姬", "色情直播", "黄片", "AV",
    ],
    "politics": [
        "反动", "推翻", "颠覆", "分裂", "独立建国",
        "法轮功", "六四", "天安门",
    ],
    "false_info": [
        "中奖", "转账", "银行卡号", "验证码", "密码",
        "汇款", "打款", "赚钱秘籍", "稳赚", "日赚",
        "躺着赚钱", "暴富", "刷单",
    ],
    "harassment": [
        "傻逼", "操你", "去死", "滚蛋", "废物",
        "人肉", "网暴",
    ],
    "advertisement": [
        "加微信", "加QQ", "扫码关注", "扫码进群",
        "代理", "招代理", "招商", "加盟",
    ],
}

# 白名单模式 (正常的新闻/学术/技术讨论)
WHITELIST_PATTERNS: list[re.Pattern] = [
    re.compile(r"(新闻|报道|记者|新华社|人民日报|央视)"),
    re.compile(r"(学术|研究|论文|期刊|教授|博士|硕士)"),
    re.compile(r"(技术|编程|代码|算法|架构|系统设计)"),
    re.compile(r"(法律法规|条款|协议|合同|法院|检察院)"),
    re.compile(r"(医疗|健康|营养|运动|健身|瑜伽)"),
]

# 对抗特征检测
ADVERSARIAL_PATTERNS: list[re.Pattern] = [
    re.compile(r"[​‌‍⁠﻿]"),  # 零宽字符
    re.compile(r"([一-鿿])[\s　]{2,}([一-鿿])"),  # 字符间异常空格
    re.compile(r"[a-zA-Z0-9]{20,}"),  # 异常长无意义字符串
]


def _rule_review(annotation_input: str) -> dict:
    """规则引擎复核 — 纯本地执行, 无 LLM 调用"""
    text = annotation_input or ""
    matched_rules: list[str] = []
    matched_keywords: list[str] = []

    # 1. 关键词匹配
    for category, keywords in VIOLATION_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                matched_rules.append(f"keyword:{category}")
                matched_keywords.append(kw)

    # 2. 白名单检测
    whitelist_hit = any(p.search(text) for p in WHITELIST_PATTERNS)

    # 3. 对抗特征检测
    adversarial_hit = any(p.search(text) for p in ADVERSARIAL_PATTERNS)
    if adversarial_hit:
        matched_rules.append("adversarial_pattern")

    # 4. 判决
    violation_count = len(matched_rules)
    if violation_count >= 2 and not whitelist_hit:
        verdict = "violation"
        detail = f"命中 {violation_count} 个违规规则: {', '.join(matched_rules[:5])}"
        if matched_keywords:
            detail += f" | 关键词: {', '.join(matched_keywords[:5])}"
    elif whitelist_hit and violation_count == 0:
        verdict = "normal"
        detail = "命中白名单模式, 无违规规则命中"
    elif violation_count == 0:
        verdict = "normal"
        detail = "无违规规则命中"
    elif whitelist_hit and violation_count > 0:
        verdict = "uncertain"
        detail = f"白名单与违规规则冲突: 命中 {violation_count} 个违规规则({', '.join(matched_rules[:3])}) + 白名单"
    else:
        verdict = "uncertain"
        detail = f"仅命中 {violation_count} 个违规规则, 不足以判定: {', '.join(matched_rules[:3])}"

    return {
        "verdict": verdict,
        "detail": detail,
        "matched_rules": matched_rules,
        "matched_keywords": matched_keywords,
        "whitelist_hit": whitelist_hit,
        "adversarial_hit": adversarial_hit,
    }


# ============================================================
# L4-a（R12）: 工具视角复核 — 标注接入 skill_router + 工具
# ============================================================
async def _tool_assisted_review(annotation_input: str) -> dict:
    """工具视角复核：keyword_check（本地AC，比硬编码词典全）+ history_search（相似案例佐证）。

    走 skill_router 路由 + reliability 可靠性层（参数校验/降级），结果作为第三视角证据。
    任何工具异常不阻断标注流程（降级为空证据）。
    """
    evidence = {"routed_skills": [], "keyword": None, "history": []}
    try:
        from agent_moderation.skill_router import get_skill_router
        from mcp_servers.registry import get_tool_registry
        from mcp_servers.tool_reliability import call_with_reliability

        router = get_skill_router()
        routed = router.route(annotation_input, top_n=20, top_k=5, max_inject=3)
        evidence["routed_skills"] = routed["selected"]

        registry = get_tool_registry()
        try:
            kw = await call_with_reliability(
                registry, "keyword_check", {"text": annotation_input})
            evidence["keyword"] = {
                "has_violation": bool(getattr(kw, "has_violation", False)),
                "matches": [str(m) for m in (getattr(kw, "matches", None) or [])][:5],
            }
        except Exception as e:
            evidence["keyword_error"] = str(e)

        try:
            hs = await call_with_reliability(
                registry, "history_search", {"query": annotation_input, "top_k": 3})
            cases = getattr(hs, "cases", None) or []
            evidence["history"] = [
                {"content_id": c.get("content_id"), "similarity": round(c.get("similarity", 0), 3)}
                for c in cases[:3]
            ]
        except Exception as e:
            evidence["history_error"] = str(e)
    except Exception as e:
        evidence["router_error"] = str(e)
    return evidence


# ============================================================
# 语义矛盾检测
# ============================================================

CONTRADICTION_RULES: list[dict] = [
    {
        "violation_types": ["violence"],
        "normal_signals": ["广告", "推销", "联系", "购买", "加微信", "优惠", "代理"],
        "desc": "判定为violence但reason描述广告/推销内容",
    },
    {
        "violation_types": ["porn"],
        "normal_signals": ["医学", "教育", "生理", "解剖", "健康", "科普", "教学"],
        "desc": "判定为porn但reason描述医学/教育内容",
    },
    {
        "violation_types": ["advertisement"],
        "normal_signals": ["新闻", "报道", "公告", "通知", "声明"],
        "desc": "判定为advertisement但reason描述新闻/公告内容",
    },
    {
        "violation_types": ["politics"],
        "normal_signals": ["学术", "历史", "研究", "讨论", "法律"],
        "desc": "判定为politics但reason描述学术/历史讨论",
    },
]


def _semantic_contradiction_check(violation_types: list[str], reason: str) -> dict:
    """
    检测 violation_type 与 reason 是否自洽
    返回: {"flag": bool, "detail": str}
    """
    if not violation_types or not reason:
        return {"flag": False, "detail": ""}

    for rule in CONTRADICTION_RULES:
        vt_match = any(vt in rule["violation_types"] for vt in violation_types)
        if not vt_match:
            continue
        normal_count = sum(1 for sig in rule["normal_signals"] if sig in reason)
        if normal_count >= 2:
            return {
                "flag": True,
                "detail": f"语义矛盾: {rule['desc']} (命中信号: {normal_count}个)",
            }

    # 反之: reason 描述违规但 violation_type 为空/none
    if (not violation_types or violation_types == ["none"] or "none" in violation_types):
        violation_signals = ["违规", "敏感", "色情", "暴力", "政治", "广告"]
        signal_count = sum(1 for sig in violation_signals if sig in reason)
        if signal_count >= 2:
            return {
                "flag": True,
                "detail": f"语义矛盾: 判定为正常但reason描述违规内容 (命中信号: {signal_count}个)",
            }

    return {"flag": False, "detail": ""}


# ============================================================
# LLM 独立审核
# ============================================================

ANNOTATION_SYSTEM_PROMPT = """你是一个独立的内容审核校验专家。你的判断与任何其他系统无关，请基于以下规则独立判断。

审核维度:
1. 政治敏感(politics): 涉政、敏感事件、分裂言论
2. 色情低俗(porn): 色情描写、低俗色情暗示
3. 暴力恐怖(violence): 暴力威胁、恐怖主义宣传
4. 虚假信息(false_info): 谣言、虚假欺诈信息
5. 辱骂骚扰(harassment): 人身攻击、侮辱性言论
6. 广告引流(advertisement): 垃圾广告、诱导加好友

判断标准:
- 明确违规 → violation, confidence ≥ 0.80
- 模糊边界 → uncertain, confidence 0.40-0.60
- 明确正常 → normal, confidence ≤ 0.20

请以JSON格式返回 (只返回JSON):
{"verdict": "violation|normal|uncertain",
 "violation_types": ["类型1","类型2"],
 "confidence": 0.0-1.0,
 "reason": "简短判断依据(50字以内)"}"""


async def _llm_independent_review(annotation_input: str) -> dict:
    """LLM 独立审核 — 使用不同 prompt + temperature=0.7 与主工作流差异化"""
    import os
    import aiohttp
    from common.config import get_settings
    from common.api_clients import get_deepseek_model

    settings = get_settings()
    api_key = settings.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        logger.warning("DEEPSEEK_API_KEY not set, falling back to rule-based review")
        return {"verdict": "uncertain", "violation_types": [], "confidence": 0.5,
                "reason": "LLM key not configured (请设置 DEEPSEEK_API_KEY)"}

    # 截断输入, 避免过长
    truncated_input = annotation_input[:1500] if annotation_input else ""

    payload = {
        "model": get_deepseek_model(),
        "temperature": 0.7,  # 刻意与主工作流差异化 (主工作流通常用更低温度)
        "messages": [
            {"role": "system", "content": ANNOTATION_SYSTEM_PROMPT},
            {"role": "user", "content": f"请独立判断以下内容是否违规:\n\n{truncated_input}"},
        ],
        "max_tokens": 300,
        "response_format": {"type": "json_object"},
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
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Annotation LLM call failed: HTTP {resp.status}")
                    return {"verdict": "uncertain", "violation_types": [], "confidence": 0.5,
                            "reason": f"LLM API error: {resp.status}"}

                data = await resp.json()
                content = data["choices"][0]["message"]["content"]
                result = json.loads(content)
                return {
                    "verdict": result.get("verdict", "uncertain"),
                    "violation_types": result.get("violation_types", []),
                    "confidence": float(result.get("confidence", 0.5)),
                    "reason": result.get("reason", ""),
                }
    except Exception as e:
        logger.warning(f"Annotation LLM call exception: {e}")
        return {"verdict": "uncertain", "violation_types": [], "confidence": 0.5,
                "reason": f"LLM error: {str(e)[:50]}"}


# ============================================================
# 裁决引擎
# ============================================================

def _make_ruling(
    model_decision: str,
    model_violation_types: list[str],
    rule_result: dict,
    llm_result: dict,
    contradiction_result: dict,
) -> tuple[bool, str, str, list[str], float]:
    """
    三方投票裁决

    规则: 2-of-3 投票。规则引擎 + LLM审核 + 矛盾检测 三者中
    ≥2 个认为模型出错 → is_error=true

    Returns:
        (is_error, error_type, error_detail, annotated_violation_types, annotated_confidence)
    """
    rule_verdict = rule_result["verdict"]  # violation / normal / uncertain
    llm_verdict = llm_result.get("verdict", "uncertain")  # violation / normal / uncertain
    contra_flag = contradiction_result["flag"]  # bool

    # 将模型判定映射为 "模型认为违规" 或 "模型认为正常"
    model_says_violation = model_decision in ("REJECT", "REVIEW") and model_violation_types
    model_says_normal = model_decision == "PASS" or (model_decision == "REVIEW" and not model_violation_types)

    # 规则引擎认为违规/正常
    rule_says_violation = rule_verdict == "violation"
    rule_says_normal = rule_verdict == "normal"

    # LLM 认为违规/正常
    llm_says_violation = llm_verdict == "violation"
    llm_says_normal = llm_verdict == "normal"

    # 矛盾检测认为出错
    contra_says_error = contra_flag

    # 收集错误信号
    error_signals = []

    # 情况1: 模型判正常, 但规则+LLM都认为违规 → false_negative
    if model_says_normal:
        if rule_says_violation and llm_says_violation:
            error_signals.append("false_negative")
        elif rule_says_violation and contra_says_error:
            error_signals.append("false_negative")
        elif llm_says_violation and contra_says_error:
            error_signals.append("false_negative")
        elif rule_says_violation and not llm_says_normal:
            error_signals.append("false_negative")

    # 情况2: 模型判违规, 但规则+LLM都认为正常 → false_positive
    if model_says_violation:
        if rule_says_normal and llm_says_normal:
            error_signals.append("false_positive")
        elif rule_says_normal and contra_says_error:
            error_signals.append("false_positive")
        elif llm_says_normal and contra_says_error:
            error_signals.append("false_positive")

    # 情况3: 语义矛盾 → wrong_violation_type
    if contra_says_error and not error_signals:
        error_signals.append("wrong_violation_type")
    elif contra_says_error:
        pass  # 矛盾检测已体现在上面的判断中

    # 投票判定
    if len(error_signals) >= 1:
        is_error = True
        # 优先选 false_positive / false_negative
        if "false_positive" in error_signals:
            error_type = "false_positive"
        elif "false_negative" in error_signals:
            error_type = "false_negative"
        else:
            error_type = "wrong_violation_type"
    else:
        is_error = False
        error_type = "correct"

    # 生成详细错误原因
    if is_error:
        parts = [f"模型判定为 [{model_decision}]"]
        if rule_result.get("detail"):
            parts.append(f"规则复核: {rule_result['detail']}")
        if llm_result.get("reason"):
            parts.append(f"LLM独立审核: {llm_result['reason']} (verdict={llm_verdict})")
        if contradiction_result.get("detail"):
            parts.append(f"矛盾检测: {contradiction_result['detail']}")

        if error_type == "false_negative":
            parts.append("结论: 【漏判】模型判为正常/通过, 但标注发现违规信号")
            suggestion = "建议: 提高对该类违规内容的敏感度, 补充相关关键词或案例"
        elif error_type == "false_positive":
            parts.append("结论: 【误判】模型判为违规, 但标注认为内容正常")
            suggestion = "建议: 降低过度敏感判定, 增加白名单规则, 或在Prompt中强调边界case的处理"
        else:
            parts.append("结论: 【类型错误】违规类型判定不准确")
            suggestion = "建议: 强化违规类型区分指引, 补充交叉案例训练"

        parts.append(suggestion)
        error_detail = "; ".join(parts)
    else:
        error_detail = "模型判定正确, 与标注验证一致"

    # 确定标注后的违规类型
    if llm_says_violation and llm_result.get("violation_types"):
        annotated_violation_types = llm_result["violation_types"]
    elif rule_says_violation:
        # 从规则结果中提取类别
        annotated_violation_types = list(set(
            r.split(":")[1] for r in rule_result.get("matched_rules", [])
            if r.startswith("keyword:")
        ))
    else:
        annotated_violation_types = model_violation_types

    annotated_confidence = llm_result.get("confidence", 0.5) if llm_result.get("verdict") != "uncertain" else 0.5

    return is_error, error_type, error_detail, annotated_violation_types, annotated_confidence


# ============================================================
# AnnotationAgent
# ============================================================

class AnnotationAgent:
    """
    标注 Agent — 独立审核结果校验

    使用方式:
        agent = AnnotationAgent()
        result = await agent.annotate(input_item)

    annotate() 内部流程:
        1. 规则引擎复核 (本地, ~1ms)
        2. 快速跳过: 规则明确且与模型判定一致 → 不调LLM
        3. LLM 独立审核 (仅必要时, ~2-5s)
        4. 语义矛盾检测 (本地, ~0.5ms)
        5. 三方投票裁决
    """

    def __init__(self):
        self._llm_call_count = 0
        self._total_count = 0

    async def annotate(self, item: dict) -> AnnotationResult:
        """对单个审核结果进行标注"""
        t0 = time.time()

        input_obj = AnnotationInput(
            content_id=item.get("content_id", ""),
            content_type=item.get("content_type", "text"),
            annotation_input=item.get("annotation_input", ""),
            model_decision=item.get("model_decision", "PASS"),
            model_confidence=float(item.get("model_confidence", 0)),
            model_violation_types=item.get("model_violation_types", []),
            model_reason=item.get("model_reason", ""),
            model_risk_score=float(item.get("model_risk_score", 0)),
            timestamp=item.get("timestamp", ""),
        )

        self._total_count += 1
        annotation_input = input_obj.annotation_input

        # === 步骤1: 规则引擎复核 ===
        rule_result = _rule_review(annotation_input)

        # L4-a（R12）: 工具视角复核（keyword_check/history_search），并入证据
        try:
            tool_evidence = await _tool_assisted_review(annotation_input)
        except Exception as e:
            logger.warning(f"[Annotation] tool_assisted_review failed: {e}")
            tool_evidence = {"error": str(e)}

        # === 步骤2: 快速跳过判断 ===
        # 规则引擎明确 + 与模型判定一致 → 直接判正确, 不调 LLM
        need_llm = self._should_call_llm(input_obj, rule_result)

        if not need_llm:
            llm_result = {"verdict": "uncertain", "violation_types": [], "confidence": 0.5, "reason": ""}
            logger.debug(f"[Annotation] {input_obj.content_id}: fast skip (rule clear, no LLM needed)")
        else:
            # === 步骤3: LLM 独立审核 ===
            self._llm_call_count += 1
            llm_result = await _llm_independent_review(annotation_input)

        # === 步骤4: 语义矛盾检测 ===
        contradiction_result = _semantic_contradiction_check(
            input_obj.model_violation_types, input_obj.model_reason
        )

        # === 步骤5: 三方投票裁决 ===
        is_error, error_type, error_detail, annotated_types, annotated_conf = _make_ruling(
            input_obj.model_decision,
            input_obj.model_violation_types,
            rule_result,
            llm_result,
            contradiction_result,
        )

        elapsed = (time.time() - t0) * 1000

        result = AnnotationResult(
            content_id=input_obj.content_id,
            is_error=is_error,
            error_type=error_type,
            error_detail=error_detail,
            rule_verdict=rule_result["verdict"],
            rule_detail=rule_result.get("detail", ""),
            llm_verdict=llm_result.get("verdict", ""),
            llm_reason=llm_result.get("reason", ""),
            contradiction_flag=contradiction_result["flag"],
            annotated_violation_types=annotated_types,
            annotated_confidence=annotated_conf,
            processing_time_ms=elapsed,
            annotated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            # 原始模型判定信息 (用于详情展示)
            model_decision=input_obj.model_decision,
            model_confidence=input_obj.model_confidence,
            model_violation_types=input_obj.model_violation_types,
            model_reason=input_obj.model_reason,
            model_risk_score=input_obj.model_risk_score,
            content_type=input_obj.content_type,
            annotation_input=input_obj.annotation_input,
            # 规则引擎详细信息
            rule_matched_keywords=rule_result.get("matched_keywords", []),
            rule_matched_rules=rule_result.get("matched_rules", []),
            # L4-a: 工具视角证据
            tool_evidence=tool_evidence,
            rule_whitelist_hit=rule_result.get("whitelist_hit", False),
            rule_adversarial_hit=rule_result.get("adversarial_hit", False),
            # 是否调用了 LLM
            llm_called=need_llm,
        )

        if is_error:
            logger.info(
                f"[Annotation] {input_obj.content_id}: ERROR ({error_type}) — "
                f"model={input_obj.model_decision}, rule={rule_result['verdict']}, "
                f"llm={llm_result.get('verdict','?')}, elapsed={elapsed:.0f}ms"
            )

        return result

    def _should_call_llm(self, input_obj: AnnotationInput, rule_result: dict) -> bool:
        """
        快速跳过逻辑: 如果规则引擎结果与模型判定一致且明确, 跳过 LLM

        Returns True 表示需要调用 LLM
        """
        model_says_violation = input_obj.model_decision in ("REJECT", "REVIEW") and input_obj.model_violation_types
        model_says_normal = input_obj.model_decision == "PASS" or (
            input_obj.model_decision == "REVIEW" and not input_obj.model_violation_types
        )
        rule_says_violation = rule_result["verdict"] == "violation"
        rule_says_normal = rule_result["verdict"] == "normal"

        # 一致且明确 → 跳过 LLM
        if model_says_violation and rule_says_violation:
            logger.debug(f"[Annotation] {input_obj.content_id}: model+rule agree on violation, skip LLM")
            return False
        if model_says_normal and rule_says_normal:
            logger.debug(f"[Annotation] {input_obj.content_id}: model+rule agree on normal, skip LLM")
            return False

        # 不一致或不确定 → 需要 LLM
        return True

    @property
    def stats(self) -> dict:
        """获取标注统计"""
        return {
            "total": self._total_count,
            "llm_calls": self._llm_call_count,
            "llm_ratio": f"{self._llm_call_count / max(self._total_count, 1) * 100:.1f}%",
        }


# 全局单例
_annotation_agent: Optional[AnnotationAgent] = None


def get_annotation_agent() -> AnnotationAgent:
    global _annotation_agent
    if _annotation_agent is None:
        _annotation_agent = AnnotationAgent()
    return _annotation_agent
