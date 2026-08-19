"""
快车道小模型（R19·M2）— 信号驱动的确定性判定器

设计（回应"快车道走小模型"）：
  - 快车道不再"规则直判 PASS 0 LLM"，而是由小模型做实际判定。
  - 小模型 = 本地规则信号综合评分器（keyword + 黑灰产 + 对抗 + 中度信号），
    便宜即时，作为 CascadeRouter 的 small_client。
  - 关键修复：**无信号 ≠ 安全**。信号为 0 时返回 needs_upgrade=True
    （隐私窃取/歧视/虚假信息等违规多无关键词信号，必须升级大模型确认，防系统性漏判）。
  - 有明确信号：按风险分判定 REJECT / REVIEW / PASS，高置信小模型直接出结论省成本。

接口遵循 CascadeRouter.small_client 契约：
    async judge(text) -> {"decision", "confidence", "needs_upgrade"}
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 中度信号（与 ModelRouter.MEDIUM_SIGNALS 对齐，用于小模型风险加分）
MEDIUM_SIGNALS = [
    r"(?:微信|QQ|加群|扫码|关注|点击|链接|www\.|http)",
    r"(?:赚钱|日赚|月入|代理|加盟|招募|兼职)",
    r"(?:杀|砍|死|打|揍|弄死|整死|弄残)",
    r"(?:诈骗|中奖|转账|银行卡|密码|验证码)",
    r"(?:裸|骚|色|淫|嫖|妓|陪睡|约炮|一夜情)",
    r"(?:傻逼|傻b|sb|尼玛|你妈|他妈|废物|垃圾|去死|脑残|弱智|白痴)",
]

# 高违规信号 → 小模型可直接 REJECT（无需升级）
HIGH_VIOLATION_SIGNALS = [
    r"(?:儿童色情|幼女|幼童|恐怖袭击|炸弹制作|杀人教程|博彩|赌博)",
    r"(?:杀猪盘|跑分|洗钱|毒品|海洛因|冰毒|枪支|弹药)",
]

# 明确安全平凡文本 → 小模型直接 PASS（无需升级）
TRIVIAL_SAFE = [
    r"^[好的嗯哦啊哈唉]+$",
    r"^(OK|ok|Ok|thanks?|thank you|yes|no|bye|hi|hello)[!~.]*$",
    r"^.{0,2}$",
]


class RuleSmallJudge:
    """快车道小模型：信号驱动，无信号升级大模型"""

    def __init__(self, keyword_tool=None, pattern_detector=None, adversarial_detector=None):
        self._keyword_tool = keyword_tool
        self._pattern_detector = pattern_detector
        self._adversarial_detector = adversarial_detector

    # ---- 懒加载组件 ----
    def _kw(self):
        if self._keyword_tool is None:
            try:
                from mcp_servers.registry import get_tool_registry
                self._keyword_tool = get_tool_registry().get_keyword_check()
            except Exception:
                self._keyword_tool = False  # 标记不可用
        return self._keyword_tool or None

    def _patterns(self, text):
        try:
            from agent_moderation.blackhat.pattern_detector import PatternDetector
            return PatternDetector().detect_all(text)
        except Exception:
            return []

    def _advers(self, text):
        try:
            from agent_moderation.blackhat.adversarial_detector import AdversarialDetector
            return AdversarialDetector().detect_all(text)
        except Exception:
            return []

    # ---- 信号统计 ----
    def _signal_score(self, text: str, kw: int = 0) -> dict:
        """统计文本信号，返回 {count, high_count, medium_count, safe}"""
        tl = text.strip().lower()
        # 平凡安全
        for p in TRIVIAL_SAFE:
            if re.match(p, tl):
                return {"count": 0, "high_count": 0, "medium_count": 0, "safe_trivial": True}
        high = sum(len(re.findall(p, tl)) for p in HIGH_VIOLATION_SIGNALS)
        medium = sum(len(re.findall(p, tl)) for p in MEDIUM_SIGNALS)
        # 黑灰产/对抗（同步，本地）
        patterns = self._patterns(text)
        advers = self._advers(text)
        bh = len(patterns) + len(advers)
        return {
            "count": high + medium + kw + bh,
            "high_count": high,
            "medium_count": medium,
            "kw_count": kw,
            "bh_count": bh,
            "safe_trivial": False,
        }

    async def _kw_count(self, text: str) -> int:
        kw_tool = self._kw()
        if kw_tool is None:
            return 0
        try:
            res = await kw_tool.execute(text)
            return int(getattr(res, "count", 0))
        except Exception:
            return 0

    async def judge(self, text: str) -> dict:
        """小模型判定。返回 CascadeRouter.small_client 契约。"""
        if not text or not text.strip():
            return {"decision": "PASS", "confidence": 0.99, "needs_upgrade": False}

        kw = await self._kw_count(text)
        sig = self._signal_score(text, kw)

        if sig["safe_trivial"]:
            return {"decision": "PASS", "confidence": 0.95, "needs_upgrade": False}

        # 无任何信号 → 不确定 → 必须升级大模型（防系统性漏判）
        if sig["count"] == 0:
            return {"decision": "UNKNOWN", "confidence": 0.0, "needs_upgrade": True,
                    "reason": "小模型无信号，需大模型语义确认"}

        # 高违规信号 → 小模型直接 REJECT
        if sig["high_count"] >= 1 or sig["bh_count"] >= 2:
            return {"decision": "REJECT", "confidence": 0.85, "needs_upgrade": False,
                    "signals": sig}

        # 中度信号：按信号强度决定 REVIEW 或升级
        if sig["count"] >= 4:
            return {"decision": "REVIEW", "confidence": 0.6, "needs_upgrade": False,
                    "signals": sig}
        if sig["count"] >= 2:
            # 2-3 个信号 → 有嫌疑但不确定类型 → 升级 LLM 确认
            return {"decision": "UNKNOWN", "confidence": 0.4, "needs_upgrade": True,
                    "reason": f"小模型{ sig['count'] }个中度信号，需 LLM 确认类型", "signals": sig}

        # 1 个信号 → 弱嫌疑，升级确认
        return {"decision": "UNKNOWN", "confidence": 0.3, "needs_upgrade": True,
                "reason": "小模型弱信号，需 LLM 确认", "signals": sig}
