"""
对抗样本检测工具 v1.0 — 检测文本中的对抗攻击模式

本地规则引擎，不调用外部API。
检测5种对抗攻击向量:
  - char_split: 字符间插入空格/符号 → 绕过关键词匹配
  - homophone: 同音字替换 (微信→薇信)
  - unicode_obfuscation: Unicode混淆 (全角/半角/零宽字符)
  - number_obfuscation: 数字变体 (123 → 1２3 / 一二三)
  - keyword_variant: 敏感词变体 (如用拼音首字母)

参考: tests/red_team.py 中的 AdversarialGenerator
"""
import re
import logging
from typing import List, Dict
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AdversarialResult(BaseModel):
    has_adversarial: bool
    attack_types: List[str]   # 检测到的攻击类型
    confidence: float         # 对抗概率 0.0-1.0
    details: List[Dict]       # 详细发现
    summary: str


class AdversarialDetectTool:
    """对抗样本检测工具 — 本地规则引擎"""

    name = "adversarial_detect"
    description = "检测文本中的对抗攻击模式（同音字/字符分割/Unicode混淆/变体词）"

    # 同音字/变体映射表
    HOMOPHONE_MAP = {
        "微信": ["薇信", "微新", "威信", "微X", "VX", "vx"],
        "加我": ["加wo", "+我", "伽我", "嘉我"],
        "赚钱": ["赚米", "转钱", "砖钱", "赚Q"],
        "裸聊": ["luo聊", "落聊", "倮聊", "裸L"],
        "色情": ["涩情", "色晴", "se情", "SQ"],
        "杀你": ["沙你", "煞你", "sha你"],
        "炸弹": ["炸蛋", "乍弹", "zha弹"],
        "银行卡": ["银航卡", "yin行卡", "YHK"],
        "裸照": ["洛照", "luo照", "LZ"],
        "赌博": ["赌搏", "du博", "DB"],
    }

    # 常见的拼音首字母变体模式 (大写字母序列)
    PINGYIN_PATTERN = re.compile(r'\b[A-Z]{2,5}\b')

    # Unicode零宽字符
    ZERO_WIDTH_CHARS = set('​‌‍‎‏﻿­')

    # 数字混淆模式
    NUMBER_OBFUSCATION = re.compile(r'[０-９０-９]')

    def __init__(self):
        self._compiled_homophones = {}
        for original, variants in self.HOMOPHONE_MAP.items():
            for v in variants:
                self._compiled_homophones[v] = original

    async def execute(self, text: str) -> AdversarialResult:
        """检测对抗样本"""
        if not text:
            return AdversarialResult(has_adversarial=False, attack_types=[], confidence=0.0, details=[], summary="空文本")

        attack_types = []
        details = []

        # 1. 字符分割检测 (空格/符号插入)
        char_split_score = self._detect_char_split(text)
        if char_split_score > 0.3:
            attack_types.append("char_split")
            details.append({"type": "char_split", "score": char_split_score, "desc": f"字符间异常分隔 (score={char_split_score:.2f})"})

        # 2. 同音字/变体检测
        homophone_matches = self._detect_homophones(text)
        if homophone_matches:
            attack_types.append("homophone")
            details.append({"type": "homophone", "matches": homophone_matches, "desc": f"检测到 {len(homophone_matches)} 个变体词: {homophone_matches[:5]}"})

        # 3. Unicode混淆检测
        unicode_score = self._detect_unicode_obfuscation(text)
        if unicode_score > 0:
            attack_types.append("unicode_obfuscation")
            details.append({"type": "unicode_obfuscation", "score": unicode_score, "desc": f"Unicode混淆 (score={unicode_score})"})

        # 4. 拼音首字母检测
        pingyin_matches = self.PINGYIN_PATTERN.findall(text)
        if pingyin_matches and len(text) > 10:
            attack_types.append("pingyin_abbr")
            details.append({"type": "pingyin_abbr", "matches": pingyin_matches[:5], "desc": f"拼音首字母: {pingyin_matches[:5]}"})

        # 5. 数字混淆检测
        num_obfuscated = len(self.NUMBER_OBFUSCATION.findall(text))
        if num_obfuscated > 0:
            attack_types.append("number_obfuscation")
            details.append({"type": "number_obfuscation", "count": num_obfuscated, "desc": f"检测到 {num_obfuscated} 个混淆数字"})

        has_adversarial = len(attack_types) > 0
        confidence = min(len(attack_types) * 0.25, 0.9) if has_adversarial else 0.0

        return AdversarialResult(
            has_adversarial=has_adversarial,
            attack_types=attack_types,
            confidence=round(confidence, 3),
            details=details,
            summary=f"{'检测到对抗样本: ' + ', '.join(attack_types) if has_adversarial else '未检测到对抗特征'}",
        )

    def _detect_char_split(self, text: str) -> float:
        """检测字符间异常分隔"""
        if len(text) < 4:
            return 0.0
        # 统计空格/符号占比
        separators = sum(1 for c in text if c in ' 　•··')
        ratio = separators / len(text)
        # 高分隔比 → 强信号
        if ratio > 0.15:
            return min(0.9, ratio * 2)
        return round(ratio, 3)

    def _detect_homophones(self, text: str) -> List[Dict]:
        """检测变体词"""
        matches = []
        for variant, original in self._compiled_homophones.items():
            if variant in text:
                matches.append({"variant": variant, "original": original})
        return matches

    def _detect_unicode_obfuscation(self, text: str) -> float:
        """检测Unicode混淆"""
        score = 0.0
        # 零宽字符
        zero_width = sum(1 for c in text if c in self.ZERO_WIDTH_CHARS)
        if zero_width > 0:
            score += min(0.4, zero_width * 0.1)

        # 全角/半角混用 (中日韩字符区)
        cjk = sum(1 for c in text if '一' <= c <= '鿿')
        latin = sum(1 for c in text if c.isascii() and c.isalpha())
        if cjk > 0 and latin > 0:
            mix_ratio = min(cjk, latin) / max(cjk, latin, 1)
            if mix_ratio > 0.3:
                score += 0.3

        return round(min(score, 0.9), 3)
