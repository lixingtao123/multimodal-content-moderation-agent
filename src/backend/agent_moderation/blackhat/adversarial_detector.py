"""
对抗样本检测器 — 识别被刻意修改以绕过审核的内容

检测维度：
1. 同音字替换 — 用同音/形近字替代敏感词 (如 嶶信→微信)
2. 拼音/字母替换 — 用拼音首字母替换中文 (如 wx→微信)
3. 字符噪音 — 插入无关字符干扰检测
4. 拆分重组 — 将敏感词拆成多个片段
5. 语义一致性 — 整体语义是否与表面文字矛盾
"""
import re
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AdversarialResult:
    technique: str
    detected: bool
    confidence: float
    evidence: List[str] = field(default_factory=list)
    risk_score: float = 0.0


class AdversarialDetector:
    """对抗样本检测器 (v3.1 增强 — 同音字/形近字/拼音检测)"""

    # === 常见变体词映射 (大幅扩展) ===
    VARIANT_MAP = {
        # 政治敏感
        "违禁品": ["vjp", "WJP", "围巾品", "唯禁品", "违纪品", "违今品"],
        "枪支": ["qz", "QZ", "欠支", "仓支", "枪枝", "腔支"],
        "炸药": ["zy", "ZY", "乍药", "炸要", "诈药"],
        "炸弹": ["zd", "ZD", "乍弹", "炸但", "诈蛋"],
        "恐怖袭击": ["kbxj", "KBXJ", "孔怖袭击", "空布袭击"],
        "分裂": ["fl", "FL", "分列", "芬裂", "愤裂"],
        "示威": ["sw", "SW", "是威", "市威", "示危"],
        "抗议": ["ky", "KY", "炕议", "康议", "抗义"],
        "独裁": ["dc", "DC", "读裁", "毒才", "独才"],
        # 色情低俗
        "色情": ["sq", "SQ", "设情", "铯情", "瑟情", "啬情", "色晴", "涩情"],
        "裸聊": ["ll", "LL", "罗聊", "落聊", "骆聊", "倮聊", "躶聊"],
        "成人": ["cr", "CR", "成仁", "承人", "城人"],
        "私密": ["sm", "SM", "丝密", "斯密", "私蜜", "思密"],
        "视频": ["sp", "SP", "视頻", "視频", "視蘋", "是频", "市频", "事频", "視pin"],
        "直播": ["zb", "ZB", "直捅", "植播", "值播", "执播"],
        "裸体": ["lt", "LT", "罗体", "落体", "倮体"],
        "约炮": ["yp", "YP", "月炮", "乐炮", "悦跑"],
        "援交": ["yj", "YJ", "元交", "原交", "媛交"],
        # 赌博
        "赌博": ["db", "DB", "读博", "肚博", "赌搏", "杜博", "妬博"],
        "赌场": ["dch", "DCH", "读场", "杜场", "赌厂", "肚场"],
        "彩票": ["cp", "CP", "采票", "菜票", "彩漂"],
        "棋牌": ["qp", "QP", "奇牌", "其牌", "期牌"],
        "百家乐": ["bjl", "BJL", "白家乐", "百佳乐", "摆家乐"],
        "老虎机": ["lhj", "LHJ", "老胡机", "劳虎机", "老护机"],
        # 诈骗引流
        "微信": ["wx", "WX", "嶶信", "威信", "薇信", "微芯", "微訫", "微莘", "溦信", "V信", "vx", "嶶訫"],
        "支付宝": ["zfb", "ZFB", "支负宝", "之付宝", "知付宝", "支付寳"],
        "银行卡": ["yhk", "YHK", "银航卡", "淫行卡", "银杭卡"],
        "贷款": ["dk", "DK", "代款", "戴款", "袋款", "贷宽"],
        "赚钱": ["zq", "ZQ", "专钱", "转钱", "攒钱", "掙钱"],
        "兼职": ["jz", "JZ", "坚职", "间职", "尖职", "简职", "兼直"],
        "日赚": ["rz", "RZ", "曰赚", "日专", "日转"],
        "加好友": ["jhy", "JHY", "加好油", "家好友", "伽好友"],
        "QQ群": ["qq群", "扣扣群", "扣Q群", "Q扣群", "q群", "球球群"],
        # 暴力恐怖
        "杀人": ["sr", "SR", "沙人", "刹人", "纱人", "殺人"],
        "砍人": ["kr", "KR", "刊人", "坎人", "侃人"],
        "死亡": ["sw", "SW", "丝亡", "斯亡", "死王"],
        "绑架": ["bj", "BJ", "绑嫁", "帮架", "榜架"],
        "毒品": ["dp", "DP", "读品", "杜品", "独品", "毒平"],
        "吸毒": ["xd", "XD", "西毒", "吸读", "希毒"],
        "大麻": ["dm", "DM", "达麻", "打麻", "大马"],
        "海洛因": ["hly", "HLY", "海落因", "海洛音", "嗨洛因"],
        # 通用对抗
        "免费": ["mf", "MF", "免废", "缅费", "免弗"],
        "红包": ["hb", "HB", "红保", "宏包", "洪包"],
        "领取": ["lq", "LQ", "领娶", "玲取", "领曲"],
        "点击": ["dj", "DJ", "点鸡", "典击", "店击"],
        "链接": ["lj", "LJ", "炼接", "恋接", "连捷"],
        "注册": ["zc", "ZC", "注测", "驻册", "柱册"],
        "下载": ["xz", "XZ", "下栽", "下仔", "夏载"],
        "客服": ["kf", "KF", "客扶", "克服", "课服"],
    }

    # === 同音字/形近字映射 (用于检测字符级替换攻击) ===
    HOMOPHONE_GROUPS = [
        ['信', '芯', '莘', '訫', '嶶', '薇', '溦', '微'],
        ['视', '是', '市', '事', '示', '室', '世', '視'],
        ['频', '蘋', '平', '凭', '苹', '评', '頻'],
        ['色', '瑟', '啬', '铯', '涩', '渋'],
        ['情', '晴', '请', '清', '轻', '卿'],
        ['赌', '读', '杜', '肚', '妬', '独', '睹'],
        ['博', '伯', '搏', '薄', '播', '驳'],
        ['枪', '呛', '腔', '仓', '蒼'],
        ['杀', '沙', '刹', '纱', '砂', '煞'],
        ['死', '丝', '斯', '思', '司', '私'],
        ['赚', '专', '转', '攒', '砖', '钻'],
        ['钱', '前', '千', '签', '迁', '浅'],
        ['裸', '罗', '落', '骆', '倮', '躶', '洛'],
        ['聊', '了', '辽', '疗', '嘹', '潦'],
        ['毒', '读', '独', '都', '度', '督'],
        ['品', '平', '频', '苹', '评'],
        ['诈', '炸', '乍', '咋', '扎', '札'],
        ['骗', '片', '偏', '篇', '翩', '遍'],
        ['黄', '皇', '煌', '蝗', '簧'],
        ['交', '娇', '胶', '郊', '膠'],
    ]

    # === 敏感词原形列表 (用于同音字检测的反向匹配) ===
    SENSITIVE_TERMS = [
        "微信", "支付宝", "色情", "视频", "赌博", "赚钱", "兼职",
        "直播", "杀人", "炸弹", "枪支", "毒品", "贷款", "裸聊",
        "诈骗", "约炮", "援交", "免费", "红包", "领取", "下载",
        "注册", "加好友", "QQ", "银行卡", "客服", "彩票", "棋牌",
        "大麻", "海洛因", "百家乐", "老虎机", "日赚", "吸毒",
    ]

    # 正则模式
    SPLIT_PATTERN = re.compile(r'(?:[一-鿿])\s{1,3}(?:[一-鿿])')
    NOISE_PATTERN = re.compile(r'[^一-鿿\w\s.,!?，。！？、]{3,}')
    FULLWIDTH_PATTERN = re.compile(r'[ａ-ｚＡ-Ｚ０-９]')
    PINYIN_HANZI_PATTERN = re.compile(r'[a-zA-Z]{2,}[一-鿿]{1,}|[一-鿿]{1,}[a-zA-Z]{2,}')

    def _build_homophone_map(self) -> Dict[str, List[str]]:
        """构建同音字查找表: 每个字符 → 可用哪些字符替换"""
        char_map = {}
        for group in self.HOMOPHONE_GROUPS:
            for char in group:
                if char not in char_map:
                    char_map[char] = []
                char_map[char].extend([c for c in group if c != char])
        return char_map

    def detect_homophone_substitution(self, text: str) -> AdversarialResult:
        """
        检测同音字/形近字替换攻击 (v3.1 新增)

        策略:
        1. 对每个敏感词，检查是否存在同音字变体
        2. 例如: "嶶信看視蘋" → 检测 "嶶信" 和 "視蘋" 分别是 "微信" 和 "视频" 的变体
        """
        evidence = []
        confidence = 0.0
        detected_count = 0

        # 方法1: 直接匹配 VARIANT_MAP 中的变体词
        for keyword, variants in self.VARIANT_MAP.items():
            for variant in variants:
                if len(variant) >= 2 and variant.lower() in text.lower():
                    evidence.append(f"'{variant}' → 疑似变体替代 '{keyword}'")
                    detected_count += 1

        # 方法2: 滑动窗口 + 同音字检测
        # 对每个敏感词，在文本中查找其被同音字替换的版本
        homophone_map = self._build_homophone_map()

        for term in self.SENSITIVE_TERMS:
            if len(term) < 2:
                continue
            # 在文本中滑动窗口
            term_len = len(term)
            for i in range(len(text) - term_len + 1):
                window = text[i:i + term_len]
                if window == term:
                    continue  # 完全匹配不算对抗
                # 检查每个字符是否与敏感词对应位置的字符同音/形近
                match_count = 0
                matched_chars = []
                for j, ch in enumerate(window):
                    target_ch = term[j] if j < term_len else None
                    if not target_ch:
                        break
                    if ch == target_ch:
                        match_count += 1
                        matched_chars.append(ch)
                    elif ch in homophone_map and target_ch in homophone_map.get(ch, []):
                        match_count += 1
                        matched_chars.append(f"{ch}≈{target_ch}")
                    else:
                        break  # 连续匹配中断

                # 至少 2/3 的字符匹配且长度 >= 2
                threshold = max(2, term_len * 2 // 3)
                if match_count >= threshold:
                    evidence.append(
                        f"'{window}' → 同音/形近替换 '{term}' "
                        f"(匹配: {','.join(matched_chars)})"
                    )
                    detected_count += 1

        # 方法3: 拼音+汉字混杂检测
        pinyin_matches = self.PINYIN_HANZI_PATTERN.findall(text)
        if pinyin_matches:
            evidence.append(f"拼音汉字混杂: {pinyin_matches[:5]}")
            detected_count += 1

        # 去重 evidence
        evidence = list(dict.fromkeys(evidence))[:10]

        detected = detected_count > 0
        confidence = min(detected_count * 0.25, 0.95) if detected else 0.0

        return AdversarialResult(
            technique="HOMOPHONE_SUBSTITUTION",
            detected=detected,
            confidence=confidence,
            evidence=evidence,
            risk_score=min(detected_count * 0.2, 0.9),
        )

    def detect_char_noise(self, text: str) -> AdversarialResult:
        """检测字符噪音（插入无关字符绕过检测）"""
        evidence = []

        noise_matches = self.NOISE_PATTERN.findall(text)
        if noise_matches:
            unique_noise = list(set(str(m) for m in noise_matches))[:3]
            evidence.append(f"异常特殊字符: {unique_noise}")

        fw_matches = self.FULLWIDTH_PATTERN.findall(text)
        if fw_matches:
            evidence.append(f"全角字符混用: {len(fw_matches)}处")

        zw_chars = ['​', '‌', '‍', '﻿', '‎', '‏']
        found_zw = [c for c in zw_chars if c in text]
        if found_zw:
            evidence.append(f"零宽字符: {len(found_zw)}种")

        detected = len(evidence) > 0
        return AdversarialResult(
            technique="CHAR_NOISE",
            detected=detected,
            confidence=min(len(evidence) * 0.4, 1.0) if detected else 0.0,
            evidence=evidence,
            risk_score=min(len(evidence) * 0.25, 0.8),
        )

    def detect_word_split(self, text: str) -> AdversarialResult:
        """检测拆分重组（将敏感词拆成多个片段）"""
        evidence = []

        split_matches = self.SPLIT_PATTERN.findall(text)
        if split_matches:
            evidence.append(f"中文字间插入空格: {len(split_matches)}处")

        punctuation_between = re.findall(r'[一-鿿][,.\s!?，。！？、*_-]{1,5}[一-鿿]', text)
        if len(punctuation_between) > 2:
            evidence.append(f"字间标点插入: {len(punctuation_between)}处")

        detected = len(evidence) > 0
        return AdversarialResult(
            technique="WORD_SPLIT",
            detected=detected,
            confidence=min(len(evidence) * 0.5, 1.0) if detected else 0.0,
            evidence=evidence,
            risk_score=min(len(evidence) * 0.3, 0.7),
        )

    def detect_synonym_variant(self, text: str) -> AdversarialResult:
        """检测同义词替换/变体词 (保留作为兼容，核心逻辑移入 detect_homophone_substitution)"""
        evidence = []

        for keyword, variants in self.VARIANT_MAP.items():
            for variant in variants:
                if variant.lower() in text.lower():
                    evidence.append(f"'{variant}' → 疑似变体替代 '{keyword}'")

        detected = len(evidence) > 0
        return AdversarialResult(
            technique="SYNONYM_VARIANT",
            detected=detected,
            confidence=min(len(evidence) * 0.35, 0.9) if detected else 0.0,
            evidence=evidence,
            risk_score=min(len(evidence) * 0.25, 0.85),
        )

    def detect_semantic_inconsistency(self, text: str) -> AdversarialResult:
        """检测语义不一致（表面文字与隐含含义矛盾）"""
        evidence = []
        risk_signals = []

        pinyin_chars = re.findall(r'[a-zA-Z]{2,}', text)
        if pinyin_chars:
            common_words = {'the', 'is', 'are', 'a', 'an', 'in', 'on', 'at', 'we', 'he', 'she', 'it', 'they',
                          'this', 'that', 'to', 'of', 'for', 'and', 'or', 'but'}
            suspicious = [w for w in pinyin_chars if w.lower() not in common_words]
            if suspicious:
                evidence.append(f"疑似拼音混用: {suspicious[:5]}")

        emoji_pattern = re.compile(
            r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]'
        )
        emojis = emoji_pattern.findall(text)
        if emojis:
            risk_signals.append(f"包含 {len(emojis)} 个 emoji")

        detected = len(evidence) > 0
        return AdversarialResult(
            technique="SEMANTIC_INCONSISTENCY",
            detected=detected,
            confidence=min(len(evidence) * 0.3, 0.6) if detected else 0.0,
            evidence=evidence + risk_signals,
            risk_score=min(len(evidence) * 0.15, 0.5),
        )

    def detect_all(self, text: str) -> List[AdversarialResult]:
        """执行所有对抗检测 (v3.1: 新增同音字/形近字检测)"""
        results = [
            self.detect_homophone_substitution(text),  # 新: 同音字/形近字检测
            self.detect_char_noise(text),
            self.detect_word_split(text),
            self.detect_synonym_variant(text),
            self.detect_semantic_inconsistency(text),
        ]
        return [r for r in results if r.detected]
