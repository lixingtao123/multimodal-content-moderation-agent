"""
敏感词检测工具 — 基于 AC 自动机（Aho-Corasick）
不调用任何外部 API，纯本地执行
"""
import logging
from typing import List, Dict
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class KeywordMatch(BaseModel):
    keyword: str
    position: int


class KeywordCheckResult(BaseModel):
    has_violation: bool
    matches: List[Dict]
    count: int


class KeywordCheckTool:
    """敏感词检测工具 — AC 自动机实现"""

    name = "keyword_check"
    description = "检测文本中的敏感词（本地 AC 自动机，不调 API）"

    # 内置基础敏感词（系统默认，策略管理中的敏感词会动态合并）
    BUILTIN_KEYWORDS = [
        # 政治类
        "违禁品", "管制刀具", "枪支", "弹药",
        # 色情类
        "色情", "裸体", "淫秽",
        # 暴力类
        "暴力", "恐怖", "杀人",
        # 诈骗类
        "中奖", "转账", "汇款", "银行卡号",
        # 广告类
        "加微信", "加QQ", "扫码", "兼职", "赚钱",
        # v4.0: 骚扰/辱骂类
        "你妈", "他妈", "废物", "傻逼", "傻b", "sb", "尼玛",
        "去死", "脑残", "弱智", "白痴", "狗日的", "操你", "草你",
        "fuck", "shit", "nmsl", "垃圾东西", "滚远点", "滚蛋",
    ]

    def __init__(self):
        self.keywords: List[str] = []
        self._automaton = None
        self._policy_keyword_count = 0  # 用于检测策略变更
        self._load_keywords()

    def _load_keywords(self):
        """加载敏感词库：内置词 + 策略管理中配置的动态词"""
        self.keywords = list(self.BUILTIN_KEYWORDS)

        # 从策略缓存加载动态敏感词
        try:
            from api.routes.policies import get_active_keywords
            policy_keywords = get_active_keywords()
            for kw in policy_keywords:
                if kw not in self.keywords:
                    self.keywords.append(kw)
            self._policy_keyword_count = len(policy_keywords)
            if policy_keywords:
                logger.info(f"KeywordCheckTool: merged {len(policy_keywords)} policy keywords")
        except Exception as e:
            logger.debug(f"KeywordCheckTool: cannot load policy keywords ({e})")

        self._build_automaton()
        logger.info(f"KeywordCheckTool loaded with {len(self.keywords)} total keywords")

    def _maybe_reload_keywords(self):
        """检测策略缓存是否有更新，有则重建 AC 自动机"""
        try:
            from api.routes.policies import get_active_keywords
            policy_keywords = get_active_keywords()
            if len(policy_keywords) != self._policy_keyword_count:
                logger.info(f"KeywordCheckTool: policy keywords changed ({self._policy_keyword_count} → {len(policy_keywords)}), reloading...")
                self._load_keywords()
                return True
        except Exception:
            pass
        return False

    def _build_automaton(self):
        """构建 AC 自动机"""
        try:
            import ahocorasick
            self._automaton = ahocorasick.Automaton()
            for idx, keyword in enumerate(self.keywords):
                self._automaton.add_word(keyword, (idx, keyword))
            self._automaton.make_automaton()
        except ImportError:
            logger.warning("pyahocorasick not installed, falling back to simple search")
            self._automaton = None

    def _simple_search(self, text: str) -> List[Dict]:
        """简单字符串匹配（无 pyahocorasick 时的兜底）"""
        matches = []
        for keyword in self.keywords:
            pos = text.find(keyword)
            if pos != -1:
                matches.append({"keyword": keyword, "position": pos})
        return matches

    def _automaton_search(self, text: str) -> List[Dict]:
        """AC 自动机搜索"""
        matches = []
        for end_index, (idx, keyword) in self._automaton.iter(text):
            matches.append({"keyword": keyword, "position": end_index - len(keyword) + 1})
        return matches

    async def execute(self, text: str) -> KeywordCheckResult:
        """执行敏感词检测"""
        if not text:
            return KeywordCheckResult(has_violation=False, matches=[], count=0)

        # 每次执行前检查策略缓存的敏感词是否有更新
        self._maybe_reload_keywords()

        if self._automaton:
            matches = self._automaton_search(text)
        else:
            matches = self._simple_search(text)

        # 去重
        seen = set()
        unique_matches = []
        for m in matches:
            key = (m["keyword"], m["position"])
            if key not in seen:
                seen.add(key)
                unique_matches.append(m)

        return KeywordCheckResult(
            has_violation=len(unique_matches) > 0,
            matches=unique_matches,
            count=len(unique_matches),
        )
