"""
违规模式检测器 — 识别黑灰产批量操作模式

检测模式：
1. BULK_GENERATION — 批量生成/模板化内容
2. KEYWORD_VARIANT — 关键词变体（谐音、拆字、特殊符号）
3. PHISHING — 钓鱼诈骗模式
4. TRAFFIC_FRAUD — 流量造假/广告引流
"""
import re
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PatternResult:
    pattern_type: str
    pattern_name: str
    detected: bool
    confidence: float
    evidence: List[str] = field(default_factory=list)
    risk_score: float = 0.0


class PatternDetector:
    """违规模式检测器"""

    # 关键词变体模式（谐音、拆字、特殊符号）
    VARIANT_PATTERNS = [
        # 微信变体
        (re.compile(r'[wvVW]{1,2}[e3]{0,2}[i1l|]{0,2}[xX×][i1l|]?[nNhH]?'), "微信变体"),
        (re.compile(r'薇[信号]'), "微信谐音"),
        # QQ变体
        (re.compile(r'[qQ]{1,2}\s*[qQ]?\s*[:：]?\s*\d{5,}'), "QQ号"),
        # 诱导添加
        (re.compile(r'[+＋]?\s*(我|[vV]|[wW])\s*[信号号]?\s*[:：]?\s*[a-zA-Z0-9_-]{5,}'), "诱导添加好友"),
        # 金钱诱导
        (re.compile(r'(日|天|小时|月)\s*(赚|入|收|搞)\s*\d+'), "快速赚钱"),
        (re.compile(r'[赚搞弄][个]?\d+[元块]'), "赚钱诱导"),
        # 扫码变体
        (re.compile(r'[扫看][一二三]?[维微][码马]'), "扫码变体"),
        # 赌博相关
        (re.compile(r'[输赢赌押注][了]?\d+'), "赌博暗示"),
        # 色情服务
        (re.compile(r'(上门|包夜|兼职|陪[聊睡])'), "色情服务"),
        (re.compile(r'(私[密信聊]|[约预]会|特[殊服])'), "隐秘联系"),
        # 变体字符（零宽空格、特殊 unicode）
        (re.compile(r'[​‌‍﻿‎‏]'), "零宽字符混淆"),
    ]

    # 批量生成检测模式
    BULK_PATTERNS = [
        # 模板化话术
        (re.compile(r'^.{0,10}(福利|免费|限时|特价|保证|正规|专业).{0,20}(微信|QQ|联系|扫码)$'), "营销模板"),
        (re.compile(r'^.{0,5}[!！?？]{2,}.{0,5}$'), "过度标点"),
        # 重复字符
        (re.compile(r'(.)\1{5,}'), "重复字符"),
        # 大量数字/符号（可能是编号）
        (re.compile(r'\d{10,}'), "长数字串"),
    ]

    # 钓鱼诈骗模式
    PHISHING_PATTERNS = [
        (re.compile(r'(点击|打开|访问).{0,10}(链接|网址|网站|URL)'), "诱导点击"),
        (re.compile(r'(http[s]?://|www\.)[^\s]{3,}'), "外链"),
        (re.compile(r'(账号|密码|验证码|银行卡).{0,5}(输入|填写|告诉|给)'), "索要凭据"),
        (re.compile(r'(官方|系统|平台).{0,5}(通知|提醒|警告)'), "冒充官方"),
        (re.compile(r'(积分|奖品|红包|现金).{0,5}(领取|兑换|到账)'), "虚假奖励"),
    ]

    # 广告引流模式
    AD_PATTERNS = [
        (re.compile(r'(免费|低价|折扣|促销|特惠).{0,5}(咨询|了解|体验)'), "诱导消费"),
        (re.compile(r'(关注|点赞|转发|分享).{0,5}(有礼|送|奖励)'), "刷量诱导"),
        (re.compile(r'(微信|公众号|小程序|APP).{0,5}(搜索|关注|下载)'), "跨平台引流"),
    ]

    def detect_keyword_variants(self, text: str) -> PatternResult:
        """检测关键词变体"""
        evidence = []
        for pattern, name in self.VARIANT_PATTERNS:
            matches = pattern.findall(text)
            if matches:
                # 取前3个唯一匹配
                unique = list(set(str(m) for m in matches))[:3]
                evidence.append(f"{name}: {unique}")

        detected = len(evidence) > 0
        confidence = min(len(evidence) * 0.3, 1.0) if detected else 0.0

        return PatternResult(
            pattern_type="KEYWORD_VARIANT",
            pattern_name="关键词变体检测",
            detected=detected,
            confidence=confidence,
            evidence=evidence,
            risk_score=min(len(evidence) * 0.2, 0.8),
        )

    def detect_bulk_generation(self, text: str) -> PatternResult:
        """检测批量生成内容"""
        evidence = []
        for pattern, name in self.BULK_PATTERNS:
            if pattern.search(text):
                evidence.append(name)

        detected = len(evidence) > 0
        confidence = min(len(evidence) * 0.25, 0.8) if detected else 0.0

        return PatternResult(
            pattern_type="BULK_GENERATION",
            pattern_name="批量生成检测",
            detected=detected,
            confidence=confidence,
            evidence=evidence,
            risk_score=min(len(evidence) * 0.15, 0.6),
        )

    def detect_phishing(self, text: str) -> PatternResult:
        """检测钓鱼诈骗"""
        evidence = []
        for pattern, name in self.PHISHING_PATTERNS:
            if pattern.search(text):
                evidence.append(name)

        detected = len(evidence) > 0
        confidence = min(len(evidence) * 0.35, 1.0) if detected else 0.0

        return PatternResult(
            pattern_type="PHISHING",
            pattern_name="钓鱼诈骗检测",
            detected=detected,
            confidence=confidence,
            evidence=evidence,
            risk_score=min(len(evidence) * 0.3, 0.9),
        )

    def detect_advertisement(self, text: str) -> PatternResult:
        """检测广告引流"""
        evidence = []
        for pattern, name in self.AD_PATTERNS:
            if pattern.search(text):
                evidence.append(name)

        detected = len(evidence) > 0
        confidence = min(len(evidence) * 0.3, 1.0) if detected else 0.0

        return PatternResult(
            pattern_type="TRAFFIC_FRAUD",
            pattern_name="广告引流检测",
            detected=detected,
            confidence=confidence,
            evidence=evidence,
            risk_score=min(len(evidence) * 0.2, 0.7),
        )

    def detect_all(self, text: str) -> List[PatternResult]:
        """执行所有模式检测"""
        results = [
            self.detect_keyword_variants(text),
            self.detect_bulk_generation(text),
            self.detect_phishing(text),
            self.detect_advertisement(text),
        ]
        return [r for r in results if r.detected]
