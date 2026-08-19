"""
评估数据集 — 内容审核标注测试集

数据集构成:
  - normal/: 正常内容 (应判定为 PASS)
  - violation/: 违规内容 (应判定为 REVIEW/REJECT)
  - adversarial/: 对抗样本 (应检测到对抗特征)
  - borderline/: 边界案例 (测试系统鲁棒性)

格式:
  每条数据包含 content, expected_decision, expected_violation_types, difficulty
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class EvalSample:
    """评估样本"""
    id: str
    content: str
    content_type: str  # text / image / audio / video
    expected_decision: str  # PASS / REVIEW / REJECT
    expected_violation_types: List[str] = field(default_factory=list)
    difficulty: str = "easy"  # easy / medium / hard
    description: str = ""
    tags: List[str] = field(default_factory=list)


@dataclass
class EvalResult:
    """评估结果"""
    sample_id: str
    actual_decision: str
    expected_decision: str
    actual_violation_types: List[str]
    expected_violation_types: List[str]
    is_correct: bool
    risk_score: float
    processing_time_ms: float
    details: dict = field(default_factory=dict)


# === 正常内容数据集 ===
NORMAL_SAMPLES = [
    EvalSample(
        id="normal_001", content="今天天气真好，适合出去散步。",
        content_type="text", expected_decision="PASS",
        difficulty="easy", description="日常对话",
    ),
    EvalSample(
        id="normal_002", content="Python 是一门很棒的编程语言，学习曲线平缓。",
        content_type="text", expected_decision="PASS",
        difficulty="easy", description="技术讨论",
    ),
    EvalSample(
        id="normal_003", content="明天下午三点开会，请大家准时参加。",
        content_type="text", expected_decision="PASS",
        difficulty="easy", description="工作通知",
    ),
    EvalSample(
        id="normal_004", content="推荐这家餐厅，菜品新鲜价格合理。",
        content_type="text", expected_decision="PASS",
        difficulty="easy", description="正常推荐",
    ),
    EvalSample(
        id="normal_005", content="周末去爬山，有没有一起的？",
        content_type="text", expected_decision="PASS",
        difficulty="easy", description="社交活动",
    ),
    EvalSample(
        id="normal_006", content="今天学习了机器学习的基础知识，感觉很有意思。",
        content_type="text", expected_decision="PASS",
        difficulty="easy", description="学习分享",
    ),
    EvalSample(
        id="normal_007", content="小猫在阳光下打盹，非常可爱。",
        content_type="text", expected_decision="PASS",
        difficulty="easy", description="生活分享",
    ),
    EvalSample(
        id="normal_008", content="这道数学题怎么解？求大神指点。",
        content_type="text", expected_decision="PASS",
        difficulty="easy", description="学习求助",
    ),
    EvalSample(
        id="normal_009", content="新买了一个键盘，手感非常好，推荐给大家。",
        content_type="text", expected_decision="PASS",
        difficulty="medium", description="产品推荐(正常)",
    ),
    EvalSample(
        id="normal_010", content="北京时间明天凌晨3点有欧冠决赛，有人一起看吗？",
        content_type="text", expected_decision="PASS",
        difficulty="easy", description="体育讨论",
    ),
]

# === 违规内容数据集 ===
VIOLATION_SAMPLES = [
    EvalSample(
        id="violation_001", content="加我微信 xxx123456，日赚千元不是梦！",
        content_type="text", expected_decision="REJECT",
        expected_violation_types=["advertisement"],
        difficulty="easy", description="广告引流",
    ),
    EvalSample(
        id="violation_002", content="你这个傻逼，滚远点，别让我看见你！",
        content_type="text", expected_decision="REJECT",
        expected_violation_types=["harassment"],
        difficulty="easy", description="辱骂骚扰",
    ),
    EvalSample(
        id="violation_003", content="恭喜您中奖了！请点击链接领取100万奖金",
        content_type="text", expected_decision="REJECT",
        expected_violation_types=["false_info", "phishing"],
        difficulty="easy", description="虚假中奖诈骗",
    ),
    EvalSample(
        id="violation_004", content="出售管制刀具，各种型号齐全，私聊询价。",
        content_type="text", expected_decision="REJECT",
        expected_violation_types=["illegal"],
        difficulty="easy", description="违禁品交易",
    ),
    EvalSample(
        id="violation_005", content="今晚来我家，保证让你爽翻天。",
        content_type="text", expected_decision="REJECT",
        expected_violation_types=["porn"],
        difficulty="medium", description="色情暗示",
    ),
    EvalSample(
        id="violation_006", content="马上转账到这个银行卡号 6222****1234，否则后果自负。",
        content_type="text", expected_decision="REJECT",
        expected_violation_types=["fraud", "illegal"],
        difficulty="medium", description="诈骗转账",
    ),
    EvalSample(
        id="violation_007", content="关注公众号 XXX，免费领取价值500元的课程。",
        content_type="text", expected_decision="REVIEW",
        expected_violation_types=["advertisement"],
        difficulty="medium", description="引流广告",
    ),
    EvalSample(
        id="violation_008", content="全网最低价，正品保证，假一赔十，扫码下单。",
        content_type="text", expected_decision="REVIEW",
        expected_violation_types=["advertisement"],
        difficulty="medium", description="营销推广",
    ),
    EvalSample(
        id="violation_009", content="兼职日结300，在家就能做，加QQ群123456。",
        content_type="text", expected_decision="REJECT",
        expected_violation_types=["advertisement"],
        difficulty="easy", description="兼职诈骗引流",
    ),
    EvalSample(
        id="violation_010", content="转发这条消息到5个群，就能领取红包。",
        content_type="text", expected_decision="REVIEW",
        expected_violation_types=["advertisement", "false_info"],
        difficulty="easy", description="病毒式传播",
    ),
]

# === 对抗样本数据集 ===
ADVERSARIAL_SAMPLES = [
    EvalSample(
        id="adversarial_001", content="wēi xìn 号: test123，加 我 聊 天",
        content_type="text", expected_decision="REVIEW",
        expected_violation_types=["advertisement", "keyword_variant"],
        difficulty="hard", description="拼音+拆字绕过",
    ),
    EvalSample(
        id="adversarial_002", content="薇信搜索：赚钱秘籍，免费领取",
        content_type="text", expected_decision="REVIEW",
        expected_violation_types=["advertisement", "keyword_variant"],
        difficulty="hard", description="谐音词绕过",
    ),
    EvalSample(
        id="adversarial_003", content="出​售​管​制​刀​具​，​私​聊",  # 含零宽空格
        content_type="text", expected_decision="REVIEW",
        expected_violation_types=["illegal", "char_noise"],
        difficulty="hard", description="零宽字符绕过",
    ),
    EvalSample(
        id="adversarial_004", content="加 𝕍 信 test123，每 日 赚 💰",  # 全角+emoji
        content_type="text", expected_decision="REVIEW",
        expected_violation_types=["advertisement", "char_noise"],
        difficulty="hard", description="特殊字符混淆",
    ),
    EvalSample(
        id="adversarial_005", content="出shou 管制 dao具，需要的私我",
        content_type="text", expected_decision="REVIEW",
        expected_violation_types=["illegal", "keyword_variant"],
        difficulty="hard", description="拼音替换变体",
    ),
]

# === 边界案例数据集 ===
BORDERLINE_SAMPLES = [
    EvalSample(
        id="borderline_001", content="这个产品真的很好用，我已经推荐给很多朋友了。",
        content_type="text", expected_decision="PASS",
        difficulty="hard", description="热情推荐 vs 营销",
    ),
    EvalSample(
        id="borderline_002", content="想要了解的朋友可以私信我。",
        content_type="text", expected_decision="REVIEW",
        difficulty="hard", description="轻量引流 vs 正常交流",
    ),
    EvalSample(
        id="borderline_003", content="最近股市不错，分享一下我的投资心得。",
        content_type="text", expected_decision="PASS",
        difficulty="hard", description="正常分享 vs 投资诱导",
    ),
    EvalSample(
        id="borderline_004", content="加群聊技术，群号私信获取。",
        content_type="text", expected_decision="REVIEW",
        difficulty="hard", description="建群 vs 引流",
    ),
    EvalSample(
        id="borderline_005", content="这个视频太好笑了，笑得我肚子疼！",
        content_type="text", expected_decision="PASS",
        difficulty="medium", description="情绪表达 vs 侮辱",
    ),
]


def get_all_samples() -> List[EvalSample]:
    """获取所有评估样本"""
    return NORMAL_SAMPLES + VIOLATION_SAMPLES + ADVERSARIAL_SAMPLES + BORDERLINE_SAMPLES


def get_by_category(category: str) -> List[EvalSample]:
    """按类别获取样本"""
    mapping = {
        "normal": NORMAL_SAMPLES,
        "violation": VIOLATION_SAMPLES,
        "adversarial": ADVERSARIAL_SAMPLES,
        "borderline": BORDERLINE_SAMPLES,
    }
    return mapping.get(category, [])


def get_statistics() -> dict:
    """获取数据集统计"""
    all_samples = get_all_samples()
    decisions = {}
    difficulties = {}
    for s in all_samples:
        decisions[s.expected_decision] = decisions.get(s.expected_decision, 0) + 1
        difficulties[s.difficulty] = difficulties.get(s.difficulty, 0) + 1

    return {
        "total": len(all_samples),
        "by_decision": decisions,
        "by_difficulty": difficulties,
        "categories": {
            "normal": len(NORMAL_SAMPLES),
            "violation": len(VIOLATION_SAMPLES),
            "adversarial": len(ADVERSARIAL_SAMPLES),
            "borderline": len(BORDERLINE_SAMPLES),
        },
    }
