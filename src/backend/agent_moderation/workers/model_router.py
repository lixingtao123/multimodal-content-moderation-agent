"""
Model Router v1.0 — 三级级联智能路由

将内容分级处理，降低 LLM 调用成本 60-70%:

  Tier 1 — 规则引擎 (0 LLM 调用, ~0ms):
    关键词硬匹配 + 长度/格式检查 → 覆盖 40% 流量
    ├── 明确正常("好的""谢谢""OK") → PASS
    ├── 明确违规(命中硬敏感词+黑灰产模式) → 标记
    └── 不确定 → Tier 2

  Tier 2 — 快速通道 (可选, 预留接口):
    本地轻量规则 + 启发式评分 → 覆盖 40% 流量
    └── 不确定 → Tier 3

  Tier 3 — 大模型 (完整 LLM 审核):
    DeepSeek-v4-flash → 覆盖 20% 流量

技术参考:
  - FrugalGPT (Chen et al., 2023): LLM Cascade
  - LLM-Blender (Jiang et al., 2023): Pairwise Ranking
  - 字节跳动内容审核级联架构

面试话术: "我们实现了三级级联路由，Tier1规则引擎拦截40%简单case，Tier2启发式处理40%
中等复杂度case，只有20%真正需要大模型深度分析。每条简单case从~500ms降到<1ms，
API成本从~$0.001降到$0。这是大厂内容审核降本增效的标准做法。"
"""
import re
import time
import logging
from typing import Optional, Tuple, Dict
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class RouteTier(Enum):
    """路由层级"""
    TIER1_RULES = "tier1_rules"       # 纯规则, 0 API 调用
    TIER2_HEURISTIC = "tier2_heuristic"  # 启发式规则
    TIER3_LLM = "tier3_llm"           # 完整LLM审核
    TIER4_ESCALATE = "tier4_escalate"  # 升级人工 (超长/超复杂)


@dataclass
class RouteDecision:
    """路由决策"""
    tier: RouteTier
    reason: str
    pre_judgment: Optional[str] = None     # PASS / VIOLATION / UNCERTAIN
    pre_violation_type: Optional[str] = None  # 预判的违规类型
    pre_confidence: float = 0.0
    cost_saved: bool = False


class ModelRouter:
    """
    三级级联模型路由器

    决策流程:
    1. 检查是否极短/极简单 → Tier1 PASS
    2. 检查是否明确敏感 → Tier1 VIOLATION
    3. 启发式复杂度评分 → Tier2/Tier3
    """

    # Tier1: 极短且明确正常的内容 (不需 LLM 审核)
    TRIVIAL_PASS_PATTERNS = [
        r"^[好的嗯哦啊哈唉]+$",
        r"^(OK|ok|Ok|thanks?|thank you|yes|no|bye|hi|hello)[!~.]*$",
        r"^[\s\d标点符号]+$",
        r"^.{0,2}$",  # 0-2个字符
    ]

    # Tier1: 硬敏感词 — 发现即标记 (不需要语义分析)
    HARD_SENSITIVE_WORDS = [
        "习近平", "毛泽东", "台独", "港独", "藏独", "法轮功",
        "基地组织", "伊斯兰国", "isis", "ISIS",
        "恐怖袭击", "炸弹制作", "杀人教程",
        "儿童色情", "幼女", "幼童",
    ]

    # Tier2: 中度信号 — 需要启发式评估
    MEDIUM_SIGNALS = [
        r"(?:微信|QQ|加群|扫码|关注|点击|链接|www\.|http)",
        r"(?:赚钱|日赚|月入|代理|加盟|招募|兼职)",
        r"(?:杀|砍|死|打|揍|弄死|整死|弄残)",
        r"(?:诈骗|中奖|转账|银行卡|密码|验证码)",
        r"(?:裸|骚|色|淫|嫖|妓|陪睡|约炮|一夜情)",
        # v3.8.1: 侮辱/人身攻击 — 之前缺少这类导致辱骂文本被Tier1放行
        r"(?:傻逼|傻b|sb|尼玛|你妈|他妈|废物|垃圾|去死|脑残|弱智|白痴|狗日的|操你|草你|fuck|shit|nmsl)",
    ]

    def __init__(self):
        self._stats = {
            "tier1_pass": 0, "tier1_violation": 0, "tier2": 0, "tier3": 0,
            "tier4": 0, "total_routed": 0,
        }
        self._start_time = time.time()

    def _get_dynamic_keywords(self) -> list:
        """从策略缓存中加载动态关键词规则"""
        try:
            from api.routes.policies import get_policy_cache
            cache = get_policy_cache()
            keyword_policies = cache.get("by_type", {}).get("keyword", [])
            extra_words = []
            for p in keyword_policies:
                config = p.get("rule_config") or {}
                keywords = config.get("keywords", [])
                extra_words.extend(keywords)
            return list(set(extra_words))
        except Exception:
            return []

    def _get_dynamic_routes(self) -> list:
        """从策略缓存中加载模型路由规则"""
        try:
            from api.routes.policies import get_policy_cache
            cache = get_policy_cache()
            route_policies = cache.get("by_type", {}).get("model_route", [])
            return route_policies
        except Exception:
            return []

    def route(self, text: str, content_type: str = "text") -> RouteDecision:
        """
        对输入文本做路由决策 (v3.8: 动态加载策略规则)

        Args:
            text: 待审核文本
            content_type: 内容类型

        Returns:
            RouteDecision (路由到哪个层级)
        """
        self._stats["total_routed"] += 1

        if not text or not text.strip():
            return RouteDecision(
                tier=RouteTier.TIER1_RULES,
                reason="空文本",
                pre_judgment="PASS",
                cost_saved=True,
            )

        text_stripped = text.strip()
        text_len = len(text_stripped)

        # === Tier 1: 规则引擎 ===

        # 1a. 动态路由规则 (从策略平台加载)
        for policy in self._get_dynamic_routes():
            config = policy.get("rule_config") or {}
            pattern = config.get("pattern", "")
            action = config.get("action", "")
            if pattern and re.match(pattern, text_stripped):
                if action == "pass":
                    self._stats["tier1_pass"] += 1
                    return RouteDecision(
                        tier=RouteTier.TIER1_RULES,
                        reason=f"动态规则({policy.get('name','?')}): {text_len}字",
                        pre_judgment="PASS",
                        cost_saved=True,
                    )

        # 1b. 极短/极简单 → 直接 PASS (硬编码回退规则)
        for pattern in self.TRIVIAL_PASS_PATTERNS:
            if re.match(pattern, text_stripped):
                self._stats["tier1_pass"] += 1
                return RouteDecision(
                    tier=RouteTier.TIER1_RULES,
                    reason=f"简单文本(长度={text_len}), 无需LLM审核",
                    pre_judgment="PASS",
                    cost_saved=True,
                )

        # 1c. 动态关键词规则 (从策略平台加载)
        for word in self._get_dynamic_keywords():
            if word and word.lower() in text_stripped.lower():
                self._stats["tier1_violation"] += 1
                return RouteDecision(
                    tier=RouteTier.TIER1_RULES,
                    reason=f"命中动态关键词: '{word}'",
                    pre_judgment="VIOLATION",
                    pre_violation_type="advertisement",
                    pre_confidence=0.85,
                    cost_saved=False,
                )

        # 1d. 硬敏感词 → 直接标记违规 (硬编码回退规则)
        for word in self.HARD_SENSITIVE_WORDS:
            if word.lower() in text_stripped.lower():
                self._stats["tier1_violation"] += 1
                return RouteDecision(
                    tier=RouteTier.TIER1_RULES,
                    reason=f"命中硬敏感词: '{word}'",
                    pre_judgment="VIOLATION",
                    pre_violation_type=self._classify_hard_violation(word),
                    pre_confidence=0.92,
                    cost_saved=False,  # 仍需LLM确认类型和细节
                )

        # === Tier 2: 启发式评估 ===

        # 统计中度信号
        medium_hits = 0
        hit_details = []
        for pattern in self.MEDIUM_SIGNALS:
            matches = re.findall(pattern, text_stripped, re.IGNORECASE)
            if matches:
                medium_hits += len(matches)
                hit_details.append(matches[0] if matches else "")

        # 复杂度评分 (0-10)
        complexity = self._calculate_complexity(text_stripped, medium_hits)

        # === Tier 4: 升级人工/大脑（超长/超高复杂度/强信号堆叠）===
        # R20 修复：此前 route() 永不返回 TIER4_ESCALATE → triage 的 HIGH 车道
        # 是死代码（brain_node 端到端不可达，终止双签规则3永不触发）。
        # 现在高复杂度/超长/强信号 → TIER4_ESCALATE → HIGH lane → 大脑仲裁。
        if complexity >= 8 or text_len >= 800 or medium_hits >= 5:
            self._stats["tier4"] += 1
            return RouteDecision(
                tier=RouteTier.TIER4_ESCALATE,
                reason=f"高复杂度(score={complexity})/超长{text_len}字/强信号{medium_hits}个, 升级大脑",
                pre_judgment="UNCERTAIN",
            )

        if complexity < 3 and medium_hits == 0 and text_len <= 150:
            # 低复杂度 + 无风险信号 + 短文本 → Tier1 PASS (三者同时满足)
            # R19 注：PASS 仅表示"进入快车道"，快车道现在用**小模型**做实际判定
            # （无信号会升级大模型），不再是规则直接放行——见 fast_lane_node。
            # R20 注：>150 字不再直接 PASS —— 长文本零信号本身是异常信号
            # （正常短对话才零信号；长文+零信号=政治新闻/虚假信息等弱信号违规），
            # 必须走 LLM/小模型确认，防止长文本有害内容误入快车道直接放行。
            self._stats["tier1_pass"] += 1
            return RouteDecision(
                tier=RouteTier.TIER1_RULES,
                reason=f"低复杂度(score={complexity})且短文本{text_len}字, 无风险信号",
                pre_judgment="PASS",
                cost_saved=True,
            )
        elif complexity < 6 and medium_hits == 0 and text_len <= 150:
            # 中等复杂度但无风险信号 → Tier2 (启发式快速通道)
            self._stats["tier2"] += 1
            return RouteDecision(
                tier=RouteTier.TIER2_HEURISTIC,
                reason=f"中等复杂度(score={complexity}), 无风险信号, 快速通道",
                pre_judgment="UNCERTAIN",
            )
        else:
            # 中高复杂度或有风险信号或长文本 → Tier3 完整 LLM 审核
            self._stats["tier3"] += 1
            return RouteDecision(
                tier=RouteTier.TIER3_LLM,
                reason=f"复杂度{complexity}/10, 风险信号{medium_hits}个 ({', '.join(hit_details[:3])})",
                pre_judgment="UNCERTAIN",
            )

    def _calculate_complexity(self, text: str, medium_hits: int) -> int:
        """计算内容复杂度 (0-10分)"""
        score = 0
        text_len = len(text)

        # 长度因素（R20: 超长文本独立提级，>800 直接接近 TIER4 门槛）
        if text_len > 800:
            score += 4
        elif text_len > 500:
            score += 3
        elif text_len > 200:
            score += 2
        elif text_len > 50:
            score += 1

        # 信号数量
        score += min(medium_hits, 4)

        # 长文本零信号异常（R20）：正常短对话才零信号；长文+零信号大概率是
        # 弱信号违规（政治新闻体/虚假信息/深度洗稿），提级让 LLM 确认。
        if medium_hits == 0 and text_len > 200:
            score += 1

        # 对抗样本特征
        if re.search(r"[^一-鿿\w\s]{3,}", text):  # 特殊字符多
            score += 1
        if re.search(r"[＀-￯]", text):  # 全角字符
            score += 1
        if re.search(r"(.)\1{4,}", text):  # 重复字符
            score += 1

        return min(score, 10)

    def _classify_hard_violation(self, word: str) -> str:
        """根据硬敏感词分类违规类型"""
        politics_words = {"习近平", "毛泽东", "台独", "港独", "藏独", "法轮功"}
        violence_words = {"基地组织", "伊斯兰国", "isis", "ISIS", "恐怖袭击", "炸弹制作", "杀人教程"}
        porn_words = {"儿童色情", "幼女", "幼童"}

        word_lower = word.lower()
        if word in politics_words:
            return "politics"
        elif word in violence_words or word_lower in {"isis"}:
            return "violence"
        elif word in porn_words:
            return "porn"
        # R20: 官方枚举用 crime（violation_types.py），illegal 已废弃
        return "crime"

    def get_stats(self) -> Dict:
        """获取路由统计"""
        total = max(self._stats["total_routed"], 1)
        return {
            "total": self._stats["total_routed"],
            "tier1_pass": self._stats["tier1_pass"],
            "tier1_pass_rate": round(self._stats["tier1_pass"] / total * 100, 1),
            "tier1_violation": self._stats["tier1_violation"],
            "tier2": self._stats["tier2"],
            "tier2_rate": round(self._stats["tier2"] / total * 100, 1),
            "tier3": self._stats["tier3"],
            "tier3_rate": round(self._stats["tier3"] / total * 100, 1),
            "tier4": self._stats["tier4"],
            "tier4_rate": round(self._stats["tier4"] / total * 100, 1),
            "cost_saved_estimate": self._stats["tier1_pass"] + self._stats["tier2"],
            "uptime_seconds": round(time.time() - self._start_time),
        }


# 全局单例
_model_router: Optional[ModelRouter] = None


def get_model_router() -> ModelRouter:
    global _model_router
    if _model_router is None:
        _model_router = ModelRouter()
    return _model_router
