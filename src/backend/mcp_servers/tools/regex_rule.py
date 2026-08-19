"""
正则规则引擎 v1.0 — 可配置的正则规则匹配

本地执行，用于检测特定格式的违规模式:
  - 手机号/QQ号/微信号 → 广告引流
  - 身份证号/银行卡号 → 隐私泄露/诈骗
  - 特定黑话/暗语 → 违规变体
  - 自定义正则规则

规则可配置，通过 rules 字典管理。
"""
import re
import logging
from typing import List, Dict, Optional
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RegexMatch(BaseModel):
    rule_name: str
    pattern: str
    match_count: int
    matched_texts: List[str]  # 匹配到的文本片段（最多5个）


class RegexRuleResult(BaseModel):
    has_match: bool
    total_matches: int
    rules_triggered: List[RegexMatch]
    risk_signals: List[str]  # 触发的风险信号
    summary: str


class RegexRuleTool:
    """正则规则引擎 — 检测特定格式的违规模式"""

    name = "regex_rule_check"
    description = "使用正则规则检测特定格式的违规模式（手机号/银行卡/黑话/自定义规则）"

    # 内置规则库
    DEFAULT_RULES = {
        "phone_number": {
            "pattern": r'1[3-9]\d{9}',
            "description": "手机号码 → 广告引流/隐私泄露",
            "risk_signal": "personal_contact",
        },
        "qq_number": {
            "pattern": r'[Qq]{2}[:\s]*\d{5,12}',
            "description": "QQ号码 → 广告引流",
            "risk_signal": "social_contact",
        },
        "wechat_id": {
            "pattern": r'(?:微信|vx|VX|wx|WX)[:\s]*[a-zA-Z0-9_-]{5,20}',
            "description": "微信号 → 广告引流",
            "risk_signal": "social_contact",
        },
        "bank_card": {
            "pattern": r'\d{16,19}',
            "description": "银行卡号（16-19位数字）→ 诈骗风险",
            "risk_signal": "financial_fraud",
        },
        "id_card": {
            "pattern": r'\d{17}[\dXx]',
            "description": "身份证号（18位）→ 隐私泄露",
            "risk_signal": "privacy_leak",
        },
        "money_amount": {
            "pattern": r'(\d+\.?\d*)\s*(万|w|W|k|K|亿)?\s*(元|块|刀|美金|美元)',
            "description": "金额提及 → 诈骗/赌博",
            "risk_signal": "money_mention",
        },
        "url_shortener": {
            "pattern": r'(?:https?://)?(?:t\.cn|url\.cn|dwz\.cn|suo\.im)/\w+',
            "description": "短链接 → 钓鱼/恶意跳转",
            "risk_signal": "suspicious_link",
        },
        "email_address": {
            "pattern": r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
            "description": "邮箱地址 → 信息收集",
            "risk_signal": "contact_info",
        },
        "video_platform": {
            "pattern": r'(?:抖音|快手|B站|bilibili|youtube|tiktok)[:：\s]*[@]?\w+',
            "description": "视频平台账号 → 引流",
            "risk_signal": "social_contact",
        },
    }

    def __init__(self, custom_rules: Dict[str, Dict] = None):
        self._compiled = {}
        # 编译默认规则
        for name, rule in self.DEFAULT_RULES.items():
            try:
                self._compiled[name] = {
                    "regex": re.compile(rule["pattern"], re.IGNORECASE),
                    "description": rule["description"],
                    "risk_signal": rule["risk_signal"],
                }
            except re.error as e:
                logger.warning(f"Regex compile failed for '{name}': {e}")

        # 加载自定义规则
        if custom_rules:
            for name, rule in custom_rules.items():
                try:
                    self._compiled[name] = {
                        "regex": re.compile(rule["pattern"], re.IGNORECASE),
                        "description": rule.get("description", name),
                        "risk_signal": rule.get("risk_signal", "custom"),
                    }
                except re.error as e:
                    logger.warning(f"Custom regex compile failed for '{name}': {e}")

    async def execute(self, text: str, rule_names: List[str] = None) -> RegexRuleResult:
        """
        执行正则规则匹配

        Args:
            text: 待检测文本
            rule_names: 指定的规则名列表（None=全部规则）
        """
        if not text:
            return RegexRuleResult(has_match=False, total_matches=0, rules_triggered=[], risk_signals=[], summary="空文本")

        rules_to_check = rule_names if rule_names else list(self._compiled.keys())
        triggered = []
        risk_signals = set()

        for name in rules_to_check:
            rule = self._compiled.get(name)
            if not rule:
                continue

            matches = rule["regex"].findall(text)
            if matches:
                # 去重
                unique_matches = list(set(str(m) for m in matches))
                triggered.append(RegexMatch(
                    rule_name=name,
                    pattern=rule["regex"].pattern,
                    match_count=len(unique_matches),
                    matched_texts=unique_matches[:5],
                ))
                risk_signals.add(rule["risk_signal"])

        total = sum(r.match_count for r in triggered)

        return RegexRuleResult(
            has_match=len(triggered) > 0,
            total_matches=total,
            rules_triggered=triggered,
            risk_signals=list(risk_signals),
            summary=f"匹配 {len(triggered)} 条规则, 共 {total} 处命中" if triggered else "无规则匹配",
        )
