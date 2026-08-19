"""
违规类型统一枚举（v5.0）— 单一权威来源（D3）

设计目的：violation_type 从 7 类扩展为 13 类后，所有下游（text_agent prompt、
risk_agent 决策、debate 权重、RAG metadata、标注/优化）统一从这里引用，
消除各处硬编码字典。

类型清单：现有 7 类 + 新增 6 类（privacy/discrimination/crime/ethics/health/copyright）
OutSafe-Bench 9 类目录 → 13 类枚举的映射也集中在此，供数据加载器使用。
"""

# ============================================================
# 13 类枚举（唯一权威）
# ============================================================
VIOLATION_TYPES: list[str] = [
    "none",  # 正常
    "politics",  # 政治敏感
    "porn",  # 色情低俗
    "violence",  # 暴力恐怖
    "false_info",  # 虚假信息
    "harassment",  # 辱骂骚扰
    "advertisement",  # 广告引流
    "privacy",  # 隐私窃取（新增）
    "discrimination",  # 歧视偏见（新增）
    "crime",  # 违法犯罪（新增）
    "ethics",  # 道德伦理（新增）
    "health",  # 身心健康（新增）
    "copyright",  # 知识产权侵权（新增）
]

# 违规类型（不含 none）——大部分下游场景用
VIOLATION_TYPES_VIOLATION: list[str] = [v for v in VIOLATION_TYPES if v != "none"]

# ============================================================
# 强制升级/终止 统一常量（R20 新增）— 单一事实源
# 此前 risk_agent/termination_check/moderation 各自硬编码 FORCE 集合，
# 且用 "illegal" 而非官方枚举 "crime"，导致 text_agent 产出的 crime
# 类型走不到强制 REJECT 路径（T1 的 crime 类样本系统性漏放）。
# 现在统一在此定义，各文件 import 引用。
# ============================================================

# 发现即至少 REVIEW（宁高估不放走）
FORCE_REVIEW_TYPES: set[str] = {
    "porn", "violence", "politics", "false_info", "privacy",
    "discrimination", "crime", "ethics", "health", "copyright",
    "illegal", "phishing",  # illegal/phishing 兼容历史代码/老数据
}

# 发现即强制抬升到 REJECT 阈值（高危）
FORCE_REJECT_TYPES: set[str] = {"violence", "crime", "illegal"}

# 高危类型（路由/终止/大脑仲裁用）
HIGH_RISK_TYPES: set[str] = {"violence", "politics", "crime", "illegal"}

# ============================================================
# 中文标签映射
# ============================================================
VIOLATION_CN: dict[str, str] = {
    "none": "正常",
    "politics": "政治敏感",
    "porn": "色情低俗",
    "violence": "暴力恐怖",
    "false_info": "虚假信息",
    "harassment": "辱骂骚扰",
    "advertisement": "广告引流",
    "privacy": "隐私窃取",
    "discrimination": "歧视偏见",
    "crime": "违法犯罪",
    "ethics": "道德伦理",
    "health": "身心健康",
    "copyright": "知识产权侵权",
}

# ============================================================
# OutSafe-Bench 9 类目录 → 13 类枚举映射（D3）
# 目录名即类别标签，见 data/OutSafe-Bench/README.md
# ============================================================
OUTSAFE_CATEGORY_MAP: dict[str, str] = {
    "1Privacy_and_Property": "privacy",
    "2Prejudice_and_Discrimination": "discrimination",
    "3Crimes_and_Illegal_Activities": "crime",
    "4Ethics_and_Morality": "ethics",
    "5Violence_and_Hatred": "violence",
    "6False_Information_and_Misderection": "false_info",
    "7Polity_Sensibility": "politics",
    "8Physical_and_Mental_Health": "health",
    "9Copyright_and_Intellectual_Property": "copyright",
}

# OutSafe 所有类别覆盖了哪些枚举（9 类 → 9 个违规枚举）
OUTSAFE_COVERED_TYPES: set[str] = set(OUTSAFE_CATEGORY_MAP.values())


def map_outsafe_category(category: str) -> str:
    """将 OutSafe 目录名映射为 13 类枚举；未知目录返回 'none' 并告警。

    目录名带数字前缀（如 "1Privacy_and_Property"），也支持传入不带前缀的
    "Privacy_and_Property"，通过后缀匹配兜底。
    """
    if category in OUTSAFE_CATEGORY_MAP:
        return OUTSAFE_CATEGORY_MAP[category]
    # 兜底：去掉数字前缀后匹配
    for dir_name, vt in OUTSAFE_CATEGORY_MAP.items():
        if dir_name.split("_", 1)[-1] == category or category in dir_name:
            return vt
    return "none"


def is_valid_violation_type(vt: str) -> bool:
    """校验是否为合法的 13 类枚举之一"""
    return vt in VIOLATION_TYPES
