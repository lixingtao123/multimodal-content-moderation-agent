"""
文本安全域扩展工具（R19·MCP 扩展批 1）

纯确定性规则实现（不调外部 API，可单测）：
  - pii_detect            隐私信息（手机号/身份证/银行卡/邮箱）
  - language_detect       语种检测（Unicode 字符统计启发式）
  - text_fingerprint      MinHash 文本指纹相似度
  - blackmarket_slang     黑灰产黑话/谐音隐语检测
  - sensitive_word_expand 敏感词变体生成（谐音/拆字/间隔）
  - email_spam_detect     垃圾营销/引流识别
"""
import re
from typing import List, Dict
from pydantic import BaseModel


# ------------------------------------------------------------
# 1. PII 检测
# ------------------------------------------------------------
class PIMMatch(BaseModel):
    pii_type: str      # phone / id_card / bank_card / email / ip
    matched: List[str]
    count: int
    risk: str          # high / medium / low


class PIIDetectResult(BaseModel):
    detected: bool
    matches: List[PIMMatch]
    risk_level: str
    summary: str


class PIIDetectTool:
    name = "pii_detect"
    description = "检测文本中的隐私信息（手机号/身份证/银行卡/邮箱/IP）"

    PATTERNS = {
        "phone": (r'(?<!\d)1[3-9]\d{9}(?!\d)', "high"),
        "id_card": (r'(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)', "high"),
        "bank_card": (r'(?<!\d)[4-9]\d{15}(?:\d{3})?(?!\d)', "high"),
        "email": (r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', "medium"),
        "ip": (r'(?<!\d)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?!\d)', "low"),
    }

    async def execute(self, text: str) -> PIIDetectResult:
        matches: List[PIMMatch] = []
        for pii_type, (pattern, risk) in self.PATTERNS.items():
            found = re.findall(pattern, text)
            if found:
                matches.append(PIMMatch(pii_type=pii_type, matched=list(dict.fromkeys(found))[:5], count=len(found), risk=risk))
        detected = bool(matches)
        risk_level = "high" if any(m.risk == "high" for m in matches) else ("medium" if matches else "safe")
        return PIIDetectResult(
            detected=detected, matches=matches, risk_level=risk_level,
            summary=f"发现 {len(matches)} 类 PII" if detected else "未发现 PII",
        )


# ------------------------------------------------------------
# 2. 语种检测
# ------------------------------------------------------------
class LanguageDetectResult(BaseModel):
    language: str      # zh / en / ja / ko / ru / ar / other
    confidence: float
    scripts: Dict[str, int]  # 各文字体系字符数


class LanguageDetectTool:
    name = "language_detect"
    description = "检测文本语种（中/英/日/韩/俄/阿拉伯/其他）"

    RANGES = {
        "zh": [(0x4E00, 0x9FFF)],
        "ja_kana": [(0x3040, 0x30FF)],
        "ko": [(0xAC00, 0xD7AF)],
        "ru": [(0x0410, 0x044F)],
        "ar": [(0x0600, 0x06FF)],
        "en": [(0x0041, 0x005A), (0x0061, 0x007A)],
    }

    def _count_scripts(self, text: str) -> Dict[str, int]:
        counts = {name: 0 for name in self.RANGES}
        for ch in text:
            cp = ord(ch)
            for name, ranges in self.RANGES.items():
                if any(lo <= cp <= hi for lo, hi in ranges):
                    counts[name] += 1
        return counts

    async def execute(self, text: str) -> LanguageDetectResult:
        counts = self._count_scripts(text)
        total = sum(counts.values()) or 1
        zh = counts["zh"] + counts["ja_kana"]  # 日文假名与汉字同源
        table = {
            "zh": zh,
            "ko": counts["ko"],
            "ru": counts["ru"],
            "ar": counts["ar"],
            "en": counts["en"],
        }
        lang, best = max(table.items(), key=lambda kv: kv[1])
        if best == 0:
            return LanguageDetectResult(language="other", confidence=0.0, scripts=counts)
        confidence = best / max(total, 1)
        return LanguageDetectResult(language=lang, confidence=round(min(confidence, 1.0), 4), scripts=counts)


# ------------------------------------------------------------
# 3. 文本指纹（n-gram Jaccard 相似度）
# ------------------------------------------------------------
class TextFingerprintResult(BaseModel):
    char_ngrams: int
    hash_signature: str
    similarity: float   # 与 ref_text 的相似度（无 ref 时为 0）
    is_near_duplicate: bool


class TextFingerprintTool:
    name = "text_fingerprint"
    description = "计算文本指纹（字符 n-gram + Jaccard 相似度），检测近似重复内容"

    def _ngrams(self, text: str, n: int = 3) -> set:
        text = re.sub(r"\s+", "", text)
        return {text[i:i + n] for i in range(len(text) - n + 1)}

    async def execute(self, text: str, ref_text: str = "", threshold: float = 0.8) -> TextFingerprintResult:
        grams = self._ngrams(text)
        signature = str(hash(frozenset(grams)) % (10 ** 12))
        similarity = 0.0
        if ref_text:
            ref = self._ngrams(ref_text)
            union = grams | ref
            similarity = (len(grams & ref) / len(union)) if union else 0.0
        return TextFingerprintResult(
            char_ngrams=len(grams), hash_signature=signature,
            similarity=round(similarity, 4),
            is_near_duplicate=similarity >= threshold,
        )


# ------------------------------------------------------------
# 4. 黑灰产黑话/隐语
# ------------------------------------------------------------
class SlangMatch(BaseModel):
    slang: str
    technique: str   # direct / homophone / split
    risk: float


class BlackmarketSlangResult(BaseModel):
    detected: bool
    matches: List[SlangMatch]
    risk_score: float
    summary: str


class BlackmarketSlangTool:
    name = "blackmarket_slang"
    description = "检测黑灰产黑话/隐语（直接词/同音变体/拆字）"

    DIRECT = ["菠菜", "狗推", "杀猪盘", "跑分", "水军", "刷单", "薅羊毛", "口子", "养号", "黑产", "暗雷", "白漂", "代练", "外挂"]
    HOMOPHONE = {"加v": "加微信", "薇": "微信", "vx": "微信", "q群": "QQ群", "涩图": "色情图", "y黄": "淫秽"}

    def _detect(self, text: str) -> List[SlangMatch]:
        matches = []
        tl = text.lower()
        for s in self.DIRECT:
            if s in text:
                matches.append(SlangMatch(slang=s, technique="direct", risk=0.8))
        for alias, orig in self.HOMOPHONE.items():
            if alias in tl:
                matches.append(SlangMatch(slang=orig, technique="homophone", risk=0.7))
        # 拆字：如 "不要加 危 信"（间隔）→ 用去空格后再匹配
        compact = re.sub(r"[\s　]", "", text)
        for s in ["加微信", "转账", "汇款", "博彩"]:
            if s in compact and s not in text:
                matches.append(SlangMatch(slang=s, technique="split", risk=0.6))
        return matches

    async def execute(self, text: str) -> BlackmarketSlangResult:
        matches = self._detect(text)
        risk = min(sum(m.risk for m in matches) / 3.0, 1.0)
        return BlackmarketSlangResult(
            detected=bool(matches), matches=matches, risk_score=round(risk, 3),
            summary=f"命中 {len(matches)} 条黑话" if matches else "未命中黑话",
        )


# ------------------------------------------------------------
# 5. 敏感词变体生成
# ------------------------------------------------------------
class WordVariant(BaseModel):
    original: str
    variant: str
    technique: str


class VariantExpandResult(BaseModel):
    generated: List[WordVariant]
    count: int


class SensitiveWordExpandTool:
    name = "sensitive_word_expand"
    description = "为敏感词生成变体（同音/拆字/间隔/同义），辅助对抗样本库构建"

    HOMOPHONES = {"赌": "堵堵", "黄": "皇", "枪": "qiang", "毒": "读", "博": "拨"}
    COMMON = ["赌博", "色情", "诈骗", "毒品", "暴恐", "政治"]

    async def execute(self, words: List[str] = None) -> VariantExpandResult:
        words = words or self.COMMON
        generated = []
        for w in words:
            generated.append(WordVariant(original=w, variant=w, technique="raw"))
            # 谐音变体
            alt = "".join(self.HOMOPHONES.get(ch, ch) for ch in w)
            if alt != w:
                generated.append(WordVariant(original=w, variant=alt, technique="homophone"))
            # 间隔变体（插零宽字符/空格）
            spaced = "[ ]".join(w)
            generated.append(WordVariant(original=w, variant=spaced, technique="spaced"))
            # 拆字变体（仅单字）
            if len(w) == 2:
                split = f"{w[0]} {w[1]}"
                generated.append(WordVariant(original=w, variant=split, technique="split"))
        return VariantExpandResult(generated=generated, count=len(generated))


# ------------------------------------------------------------
# 6. 垃圾营销/引流识别
# ------------------------------------------------------------
class EmailSpamResult(BaseModel):
    is_spam: bool
    score: float
    signals: List[str]
    summary: str


class EmailSpamDetectTool:
    name = "email_spam_detect"
    description = "识别垃圾营销/广告引流内容（关键词+结构特征）"

    SPAM_KEYWORDS = ["加微信", "加V", "扫码", "点击链接", "注册送", "免费领取", "兼职", "日赚", "刷单", "返利", "优惠券", "限时抢购", "点击下方", "私信我"]
    URL_HINT = re.compile(r'(https?://|www\.|\.com|\.cn)')
    NUMERIC_EXCLAIM = re.compile(r'[!！]{2,}')

    async def execute(self, text: str) -> EmailSpamResult:
        signals = []
        score = 0.0
        hits = [k for k in self.SPAM_KEYWORDS if k in text]
        if hits:
            score += min(len(hits) * 0.2, 0.6)
            signals.append(f"关键词: {','.join(hits[:3])}")
        if self.URL_HINT.search(text):
            score += 0.25
            signals.append("含外链")
        if self.NUMERIC_EXCLAIM.search(text):
            score += 0.15
            signals.append("过度感叹号")
        return EmailSpamResult(
            is_spam=score >= 0.4, score=round(min(score, 1.0), 3), signals=signals,
            summary="疑似营销引流" if score >= 0.4 else "未发现营销特征",
        )
