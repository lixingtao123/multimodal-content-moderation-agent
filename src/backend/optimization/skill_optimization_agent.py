"""
Skill Optimization Agent v4.0 — 高级智能优化器（单人模式 + 单个建议投票）

基于真实路由日志深度分析，提供高价值的优化建议：
- 智能触发词挖掘与建议
- 语义描述优化（拒绝无意义后缀）
- 每个建议单独投票
- 可以选择性应用部分建议
- 优化前后对比预览
- 降低废弃建议的误报率
- 避免短期重复生成报告
- 智能去重建议
"""
import json
import re
import shutil
import time
import logging
import difflib
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import Counter, defaultdict

from agent_moderation.skill_registry import get_skill_registry

logger = logging.getLogger(__name__)

SKILLS_DIR = Path("/workspace/skills")
SKILL_BACKUP_DIR = Path("/workspace/skills_backups")
REPORTS_DIR = SKILL_BACKUP_DIR / "reports"
DEPRECATED_DIR = SKILL_BACKUP_DIR / "deprecated"

for dir_path in [SKILL_BACKUP_DIR, REPORTS_DIR, DEPRECATED_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

FRONTMATTER_RE = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)


@dataclass
class SkillOptimizationSuggestion:
    """优化建议（增强版）"""
    skill_name: str
    suggestion_type: str
    current_value: str = ""
    suggested_value: str = ""
    reason: str = ""
    confidence: float = 0.0
    supporting_examples: List[str] = field(default_factory=list)
    analysis_detail: str = ""
    impact: str = ""
    related_logs: List[Dict] = field(default_factory=list)
    related_skill_names: List[str] = field(default_factory=list)
    suggested_skill_names: List[str] = field(default_factory=list)


@dataclass
class SuggestionWithVote:
    """带投票状态的单个建议"""
    id: int  # 建议唯一 ID
    skill_name: str
    suggestion_type: str
    current_value: str = ""
    suggested_value: str = ""
    reason: str = ""
    confidence: float = 0.0
    supporting_examples: List[str] = field(default_factory=list)
    analysis_detail: str = ""
    impact: str = ""

    # 新增的投票状态
    approved: bool = False
    votes: List[Dict] = field(default_factory=list)
    # 应用状态
    applied: bool = False
    applied_at: Optional[float] = None


@dataclass
class EnhancedOptimizationReport:
    """增强的优化报告（支持单个建议投票）"""
    generated_at: float
    analysis_summary: str
    suggestions: List[SuggestionWithVote]

    voting_required: bool = True

    # 兼容旧格式
    approved: bool = False
    votes: List[Dict] = field(default_factory=list)

    # 应用状态
    applied_at: Optional[float] = None
    applied_suggestions: List[int] = field(default_factory=list)

    report_path: str = ""

    @property
    def suggestion_count(self) -> int:
        """建议数量（兼容旧格式）"""
        return len(self.suggestions)


@dataclass
class SkillOptimizationReport:
    """优化报告（与前端兼容）"""
    generated_at: float
    suggestion_count: int
    suggestions: List[SkillOptimizationSuggestion]
    analysis_summary: str
    voting_required: bool = True
    votes: List[Dict] = field(default_factory=list)
    approved: bool = False
    report_path: str = ""


class SkillOptimizationAgent:
    """智能 Skill 优化 Agent v4.0"""

    VALID_TYPES = [
        "description_update", "trigger_add", "trigger_remove",
        "tag_add", "tag_remove", "new_skill",
        "skill_split", "skill_merge", "skill_deprecate"
    ]

    # 关键词库，用于智能触发词挖掘
    KEYWORD_VARIATIONS = {
        "微信": ["加微信", "vx", "wx", "V信", "wechat", "加v", "联系v", "微", "微信联系", "加我微信"],
        "QQ": ["加q", "qq", "扣扣", "加群", "qq群", "q群"],
        "赚钱": ["赚钱", "日赚", "月入", "收益", "加盟", "代理", "项目", "轻松赚"],
        "红包": ["红包", "福利", "领现金", "注册送", "送钱"],
        "下载": ["下载", "app", "APP", "安装", "扫码", "二维码"],
        "辱骂": ["傻逼", "脑残", "废物", "死妈", "滚", "妈的", "操", "草"],
        "暴力": ["杀", "弄死", "砍死", "打死", "捅死"],
        "诈骗": ["中奖", "中奖了", "你中奖了", "银行", "公安局", "密码"],
    }

    # 防止短期重复报告的时间窗口（秒）
    REPORT_COOLDOWN = 3600  # 1小时

    def __init__(self):
        self._registry = None
        self._lock = False

    @property
    def registry(self):
        if self._registry is None:
            self._registry = get_skill_registry()
        return self._registry

    async def analyze_and_suggest(
        self, log_dir: str = '/tmp/skill_logs', min_logs: int = 10,
        force: bool = False
    ) -> Optional[EnhancedOptimizationReport]:
        """主要分析入口（生成增强格式报告）"""
        if self._lock:
            logger.info("Already running, skip")
            return None

        self._lock = True
        try:
            # 检查冷却期，避免重复报告
            if not force and self._has_recent_report():
                logger.info("Recent report exists, skipping generation")
                return self._get_latest_enhanced_report()

            routing_logs = await self._load_routing_logs_from_db()
            if len(routing_logs) < min_logs:
                file_logs = self._load_routing_logs_from_file(log_dir)
                routing_logs.extend(file_logs)

            if len(routing_logs) < min_logs:
                logger.info(f"Only {len(routing_logs)} logs, needs at least {min_logs}")
                return None

            logger.info(f"Analyzing {len(routing_logs)} logs...")

            log_summary = self._summarize_logs(routing_logs)
            skills = {s.name: s for s in self.registry.list_skills()}

            suggestions = self._generate_heuristic_suggestions(routing_logs, skills, log_summary)

            # 建议去重
            suggestions = self._deduplicate_suggestions(suggestions)

            # 限制建议数量
            suggestions = suggestions[:30]

            # 转换为增强格式
            enhanced_suggestions = [
                SuggestionWithVote(
                    id=i,
                    skill_name=s.skill_name,
                    suggestion_type=s.suggestion_type,
                    current_value=s.current_value,
                    suggested_value=s.suggested_value,
                    reason=s.reason,
                    confidence=s.confidence,
                    supporting_examples=s.supporting_examples,
                    analysis_detail=s.analysis_detail,
                    impact=s.impact,
                    approved=False,
                    votes=[],
                    applied=False,
                    applied_at=None
                )
                for i, s in enumerate(suggestions)
            ]

            analysis_summary = self._generate_analysis_summary(suggestions, routing_logs)

            report = EnhancedOptimizationReport(
                generated_at=time.time(),
                analysis_summary=analysis_summary,
                suggestions=enhanced_suggestions,
                voting_required=True,
            )

            report_path = self._save_enhanced_report(report)
            report.report_path = report_path

            return report

        finally:
            self._lock = False

    async def vote_suggestion(
        self, report_path: str, suggestion_id: int,
        voter: str, vote: bool, comment: str = ""
    ) -> Dict:
        """对单个建议投票（单人模式：任何通过即批准该建议）"""
        report = self._load_enhanced_report(report_path)
        if report is None:
            return {"success": False, "error": "Report not found"}

        # 找到该建议
        suggestion = None
        for s in report.suggestions:
            if s.id == suggestion_id:
                suggestion = s
                break

        if suggestion is None:
            return {"success": False, "error": "Suggestion not found"}

        # 添加/更新投票
        existing_idx = None
        for i, v in enumerate(suggestion.votes):
            if v.get("voter") == voter:
                existing_idx = i
                break

        vote_dict = {
            "voter": voter,
            "vote": vote,
            "comment": comment,
            "timestamp": time.time(),
        }

        if existing_idx is not None:
            suggestion.votes[existing_idx] = vote_dict
        else:
            suggestion.votes.append(vote_dict)

        # 单人模式：任何通过即批准该建议，拒绝则取消批准
        if vote:
            suggestion.approved = True
        else:
            # 如果投了拒绝票，取消批准状态（只要没有应用就可以回退）
            if not suggestion.applied:
                suggestion.approved = False

        # 保存更新后的报告
        self._save_enhanced_report(report)

        return {
            "success": True,
            "suggestion_id": suggestion_id,
            "approved": suggestion.approved,
            "votes": suggestion.votes
        }

    async def apply_selected(
        self, report_path: str, suggestion_ids: List[int]
    ) -> Dict:
        """应用选中的建议"""
        report = self._load_enhanced_report(report_path)
        if report is None:
            return {"success": False, "error": "Report not found"}

        # 找到要应用的建议（只应用已批准的）
        suggestions_to_apply = []
        for s in report.suggestions:
            if s.id in suggestion_ids and s.approved and not s.applied:
                suggestions_to_apply.append(s)

        if not suggestions_to_apply:
            return {"success": False, "error": "No approved suggestions to apply"}

        results = {"success": True, "applied": [], "skipped": [], "errors": []}

        for suggestion in suggestions_to_apply:
            try:
                await self._apply_single_suggestion(suggestion)
                suggestion.applied = True
                suggestion.applied_at = time.time()
                report.applied_suggestions.append(suggestion.id)
                results["applied"].append(suggestion.id)
            except Exception as e:
                logger.error(f"Failed to apply suggestion {suggestion.id}: {e}")
                results["errors"].append(f"{suggestion.id}: {e}")
                results["skipped"].append(suggestion.id)

        # 记录应用时间
        report.applied_at = time.time()

        # 保存报告
        self._save_enhanced_report(report)

        return results

    async def _apply_single_suggestion(self, suggestion: SuggestionWithVote):
        """应用单个建议"""
        # 复用现有的逻辑
        # 先构建一个简单的临时建议对象
        temp_suggestion = SkillOptimizationSuggestion(
            skill_name=suggestion.skill_name,
            suggestion_type=suggestion.suggestion_type,
            current_value=suggestion.current_value,
            suggested_value=suggestion.suggested_value,
            reason=suggestion.reason,
            confidence=suggestion.confidence,
            supporting_examples=suggestion.supporting_examples,
            analysis_detail=suggestion.analysis_detail,
            impact=suggestion.impact,
        )

        if temp_suggestion.suggestion_type == "new_skill":
            await self._create_new_skill(temp_suggestion)
        elif temp_suggestion.suggestion_type == "skill_split":
            await self._split_skill(temp_suggestion)
        elif temp_suggestion.suggestion_type == "skill_merge":
            await self._merge_skills(temp_suggestion)
        elif temp_suggestion.suggestion_type == "skill_deprecate":
            await self._deprecate_skill(temp_suggestion)
        else:
            await self._update_existing_skill(temp_suggestion)

    def get_preview_diff(self, report_path: str, suggestion_id: int) -> Optional[Dict]:
        """获取单个建议的预览效果（不实际修改文件）"""
        report = self._load_enhanced_report(report_path)
        if report is None:
            return None

        suggestion = None
        for s in report.suggestions:
            if s.id == suggestion_id:
                suggestion = s
                break

        if suggestion is None:
            return None

        # 读取当前 Skill 文件内容
        skill_name = suggestion.skill_name
        skill_dir = SKILLS_DIR / skill_name
        if not skill_dir.exists():
            skill_dir = SKILLS_DIR / skill_name.replace("-", "_")
        if not skill_dir.exists():
            return None

        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            return None

        with open(skill_file, 'r', encoding='utf-8') as f:
            original_content = f.read()

        # 模拟应用建议
        simulated_content = self._modify_skill_content(original_content, suggestion)

        # 生成差异
        diff_lines = list(difflib.unified_diff(
            original_content.splitlines(),
            simulated_content.splitlines(),
            fromfile='Original',
            tofile='Optimized',
            lineterm=''
        ))

        return {
            "suggestion_id": suggestion_id,
            "skill_name": skill_name,
            "original": original_content,
            "optimized": simulated_content,
            "diff": diff_lines
        }

    def _has_recent_report(self) -> bool:
        """检查是否有近期报告"""
        now = time.time()
        for report_file in REPORTS_DIR.glob("skill_opt_*.json"):
            try:
                if now - report_file.stat().st_mtime < self.REPORT_COOLDOWN:
                    return True
            except Exception:
                pass
        return False

    def _get_latest_report(self) -> Optional[SkillOptimizationReport]:
        """获取最新报告（兼容旧格式）"""
        latest_file = None
        latest_time = 0
        for report_file in REPORTS_DIR.glob("skill_opt_*.json"):
            try:
                mtime = report_file.stat().st_mtime
                if mtime > latest_time:
                    latest_time = mtime
                    latest_file = report_file
            except Exception:
                pass

        if latest_file:
            return self._load_report(latest_file.name)
        return None

    def _get_latest_enhanced_report(self) -> Optional[EnhancedOptimizationReport]:
        """获取最新报告（增强格式）"""
        latest_file = None
        latest_time = 0
        for report_file in REPORTS_DIR.glob("skill_opt_*.json"):
            try:
                mtime = report_file.stat().st_mtime
                if mtime > latest_time:
                    latest_time = mtime
                    latest_file = report_file
            except Exception:
                pass

        if latest_file:
            return self._load_enhanced_report(latest_file.name)
        return None

    def _deduplicate_suggestions(
        self, suggestions: List[SkillOptimizationSuggestion]
    ) -> List[SkillOptimizationSuggestion]:
        """对建议去重，同一技能同一类型只保留一条"""
        seen = set()
        result = []
        for s in suggestions:
            key = (s.skill_name, s.suggestion_type, s.suggested_value[:50])
            if key not in seen:
                seen.add(key)
                result.append(s)
        return result

    async def _load_routing_logs_from_db(self) -> List[Dict]:
        """从数据库加载路由日志"""
        logs = []
        try:
            from sqlalchemy import select, desc
            from db.connection import get_session_factory
            from db.models import SkillRoutingLog

            session_factory = get_session_factory()
            async with session_factory() as session:
                query = select(SkillRoutingLog).order_by(desc(SkillRoutingLog.timestamp)).limit(1000)
                result = await session.execute(query)
                db_logs = result.scalars().all()

                for log in db_logs:
                    logs.append({
                        "content_id": log.content_id,
                        "agent": log.agent,
                        "query": log.query,
                        "content_type": log.content_type,
                        "filtered_skills": log.filtered_skills,
                        "ranked_skills": log.ranked_skills,
                        "selected_skills": log.selected_skills,
                        "timestamp": log.timestamp.timestamp() if log.timestamp else time.time(),
                    })
        except Exception as e:
            logger.warning(f"Failed to load DB logs: {e}")
        return logs

    def _load_routing_logs_from_file(self, log_dir: str) -> List[Dict]:
        """从文件加载路由日志"""
        logs = []
        log_path = Path(log_dir)
        demo_path = Path("/workspace/skill_demo_data/skill_routing_logs.jsonl")

        if demo_path.exists():
            try:
                with open(demo_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            logs.append(json.loads(line))
            except Exception as e:
                logger.warning(f"Failed to read demo logs: {e}")

        if not logs and log_path.exists():
            for log_file in log_path.glob("skill_routing_*.jsonl"):
                try:
                    with open(log_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                logs.append(json.loads(line))
                except Exception as e:
                    logger.warning(f"Failed to read {log_file}: {e}")

        logs.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        return logs[:1000]

    def _summarize_logs(self, routing_logs: List[Dict]) -> Dict:
        """摘要化日志"""
        skill_stats = Counter()
        skill_filter_stats = Counter()
        skill_rank_stats = Counter()

        for log in routing_logs:
            for s in log.get('selected', []):
                skill_stats[s] += 1
            for s in log.get('filtered', []):
                skill_filter_stats[s] += 1
            for s in log.get('ranked', []):
                skill_rank_stats[s] += 1

        return {
            "total_logs": len(routing_logs),
            "skill_stats": dict(skill_stats),
            "skill_filter_stats": dict(skill_filter_stats),
            "skill_rank_stats": dict(skill_rank_stats),
        }

    def _generate_heuristic_suggestions(self, routing_logs: List[Dict], skills: Dict, log_summary: Dict) -> List[SkillOptimizationSuggestion]:
        """智能生成高价值建议"""
        suggestions = []
        skill_suggestion_count = defaultdict(int)

        # 1. 智能触发词挖掘（高价值建议）
        trigger_suggestions = self._mine_trigger_suggestions(routing_logs, skills, log_summary)
        for s in trigger_suggestions:
            if skill_suggestion_count[s.skill_name] < 4:  # 每个技能最多4个建议
                suggestions.append(s)
                skill_suggestion_count[s.skill_name] += 1

        # 2. 智能描述优化（拒绝无意义后缀）
        desc_suggestions = self._generate_desc_suggestions(routing_logs, skills, log_summary)
        for s in desc_suggestions:
            if skill_suggestion_count[s.skill_name] < 4:
                suggestions.append(s)
                skill_suggestion_count[s.skill_name] += 1

        # 3. Skill废弃建议（高阈值，避免误报，需要200条才考虑）
        deprecate_suggestions = self._generate_deprecate_suggestions(skills, log_summary)
        for s in deprecate_suggestions:
            if skill_suggestion_count[s.skill_name] < 4:
                suggestions.append(s)
                skill_suggestion_count[s.skill_name] += 1

        return suggestions

    def _mine_trigger_suggestions(
        self, logs: List[Dict], skills: Dict, log_summary: Dict
    ) -> List[SkillOptimizationSuggestion]:
        """智能挖掘应该添加的触发词"""
        suggestions = []
        skill_queries = defaultdict(list)
        skill_selected_queries = defaultdict(list)

        for log in logs:
            query = log.get('query', '')
            for s in log.get('filtered', []):
                skill_queries[s].append(query)
            for s in log.get('selected', []):
                skill_selected_queries[s].append(query)

        # 技能与关键词类别的映射
        skill_keyword_map = {
            "spam_detect": ["微信", "QQ", "赚钱", "红包", "下载"],
            "keyword-check": ["微信", "QQ", "赚钱", "红包", "下载", "辱骂", "暴力", "诈骗"],
            "keyword_check": ["微信", "QQ", "赚钱", "红包", "下载", "辱骂", "暴力", "诈骗"],
            "blackmarket_detect": ["辱骂", "暴力", "诈骗"],
            "download_risk_check": ["下载", "红包", "注册送"],
        }

        # 针对每个 Skill 分析应该添加什么触发词
        for skill_name, skill in skills.items():
            if skill_name not in skill_keyword_map:
                continue

            # 处理 triggers：可能是 list[dict] 或者其他格式
            current_trigger_keywords = set()
            if skill.triggers:
                for t in skill.triggers:
                    if isinstance(t, dict):
                        for v in t.values():
                            if isinstance(v, str):
                                current_trigger_keywords.add(v)
                    elif isinstance(t, str):
                        current_trigger_keywords.add(t)

            relevant_queries = skill_queries.get(skill_name, []) + skill_selected_queries.get(skill_name, [])
            if not relevant_queries:
                continue

            suggested_triggers = []
            keyword_categories = skill_keyword_map[skill_name]

            # 基于关键词库匹配 - 只使用该技能相关的类别
            for category in keyword_categories:
                keywords = self.KEYWORD_VARIATIONS.get(category, [])
                for query in relevant_queries:
                    query_lower = query.lower()
                    for kw in keywords:
                        if kw.lower() in query_lower and kw not in current_trigger_keywords and kw not in suggested_triggers:
                            count = sum(1 for q in relevant_queries if kw.lower() in q.lower())
                            if count >= 2:
                                suggested_triggers.append((kw, count, query))

            for new_trigger, count, example in suggested_triggers[:2]:
                suggestions.append(SkillOptimizationSuggestion(
                    skill_name=skill_name,
                    suggestion_type="trigger_add",
                    current_value="",
                    suggested_value=new_trigger,
                    reason=f"在 {count} 条相关查询中出现，添加可提高召回率",
                    confidence=0.9,
                    supporting_examples=[example],
                    analysis_detail=f"关键词 '{new_trigger}' 在相关查询中频繁出现，添加到触发词后可提高 Filter 阶段匹配概率。",
                    impact="高 - 提高 Skill 召回率",
                ))

        return suggestions

    def _generate_desc_suggestions(
        self, logs: List[Dict], skills: Dict, log_summary: Dict
    ) -> List[SkillOptimizationSuggestion]:
        """生成有意义的描述优化（拒绝无意义后缀）"""
        suggestions = []

        improved_descriptions = {
            "spam_detect": "识别垃圾营销广告与引流信息，包括诱导联系方式、红包福利、赚钱项目、下载注册等内容",
            "pii_scan": "检测隐私信息泄露风险，包括手机号、身份证号、银行卡号、微信号、QQ号等个人敏感信息",
            "blackmarket_detect": "识别违规内容，包括辱骂、暴力威胁、黑灰产交易、诈骗信息等",
            "keyword-check": "基于关键词匹配的内容安全检测，识别各类违规关键词模式",
            "keyword_check": "基于关键词匹配的内容安全检测，识别各类违规关键词模式",
            "download_risk_check": "检测下载相关风险，包括 APP 下载、扫码安装、注册送福利等引流下载内容",
        }

        for skill_name, improved_desc in improved_descriptions.items():
            skill = skills.get(skill_name)
            if not skill:
                continue

            if skill.description != improved_desc and not skill.description.endswith("(优化语义匹配)"):
                related_queries = [log.get('query', '') for log in logs if skill_name in log.get('filtered', [])]
                suggestions.append(SkillOptimizationSuggestion(
                    skill_name=skill_name,
                    suggestion_type="description_update",
                    current_value=skill.description,
                    suggested_value=improved_desc,
                    reason="优化后的描述更符合实际应用场景，可提高语义匹配度",
                    confidence=0.85,
                    supporting_examples=related_queries[:2] if related_queries else [],
                    analysis_detail="新描述更贴近实际应用场景，能提高 Semantic Rank 阶段的排名表现。",
                    impact="中 - 提高语义排名表现",
                ))

        return suggestions

    def _generate_deprecate_suggestions(
        self, skills: Dict, log_summary: Dict
    ) -> List[SkillOptimizationSuggestion]:
        """生成废弃建议（高阈值，避免误报，需要200条才考虑）"""
        suggestions = []
        skill_stats = log_summary.get('skill_stats', {})
        total_logs = log_summary.get('total_logs', 0)

        if total_logs < 200:  # 需要至少200条日志才考虑废弃
            return suggestions

        for skill_name, skill in skills.items():
            usage_count = skill_stats.get(skill_name, 0)

            if usage_count == 0:
                suggestions.append(SkillOptimizationSuggestion(
                    skill_name=skill_name,
                    suggestion_type="skill_deprecate",
                    current_value=f"使用次数：0 / {total_logs}",
                    suggested_value=f"废弃 {skill_name}",
                    reason=f"该 Skill 在 {total_logs} 条日志中从未被选中，建议先标记为废弃",
                    confidence=0.75,
                    supporting_examples=[f"分析了 {total_logs} 条路由日志"],
                    analysis_detail=f"长期未使用的 Skill 可能已经过时，建议先标记为 deprecated 观察。",
                    impact="低 - 仅标记，不影响现有功能",
                ))

        return suggestions

    def _generate_analysis_summary(self, suggestions: List, logs: List) -> str:
        """生成分析摘要"""
        total_logs = len(logs)
        type_counts = Counter()
        for s in suggestions:
            type_counts[s.suggestion_type] += 1

        parts = []
        if type_counts.get("trigger_add", 0) > 0:
            parts.append(f"{type_counts['trigger_add']}条触发词添加")
        if type_counts.get("description_update", 0) > 0:
            parts.append(f"{type_counts['description_update']}条描述优化")
        if type_counts.get("skill_deprecate", 0) > 0:
            parts.append(f"{type_counts['skill_deprecate']}条废弃建议")

        summary_text = "、".join(parts) if parts else "无优化建议"

        return f"分析了 {total_logs} 条路由日志，共生成 {len(suggestions)} 条优化建议：{summary_text}"

    def _save_enhanced_report(self, report: EnhancedOptimizationReport) -> str:
        """保存增强格式报告"""
        filename = f"skill_opt_{int(report.generated_at)}.json"
        filepath = REPORTS_DIR / filename

        report_dict = {
            "generated_at": report.generated_at,
            "analysis_summary": report.analysis_summary,
            "suggestions": [
                {
                    "id": s.id,
                    "skill_name": s.skill_name,
                    "suggestion_type": s.suggestion_type,
                    "current_value": s.current_value,
                    "suggested_value": s.suggested_value,
                    "reason": s.reason,
                    "confidence": s.confidence,
                    "supporting_examples": s.supporting_examples,
                    "analysis_detail": s.analysis_detail,
                    "impact": s.impact,
                    "approved": s.approved,
                    "votes": s.votes,
                    "applied": s.applied,
                    "applied_at": s.applied_at
                }
                for s in report.suggestions
            ],
            "voting_required": report.voting_required,
            "approved": report.approved,
            "votes": report.votes,
            "applied_at": report.applied_at,
            "applied_suggestions": report.applied_suggestions,
            "report_path": filename,
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report_dict, f, ensure_ascii=False, indent=2)

        return filename

    def _load_enhanced_report(self, filepath: str) -> Optional[EnhancedOptimizationReport]:
        """加载增强格式报告"""
        try:
            path = Path(filepath)
            if not path.exists():
                path = REPORTS_DIR / filepath
            if not path.exists():
                path = REPORTS_DIR / f"{filepath}.json"
            if not path.exists():
                return None

            with open(path, 'r', encoding='utf-8') as f:
                report_dict = json.load(f)

            suggestions = []
            for s in report_dict.get("suggestions", []):
                suggestions.append(SuggestionWithVote(
                    id=s.get("id", 0),
                    skill_name=s.get("skill_name", ""),
                    suggestion_type=s.get("suggestion_type", ""),
                    current_value=s.get("current_value", ""),
                    suggested_value=s.get("suggested_value", ""),
                    reason=s.get("reason", ""),
                    confidence=s.get("confidence", 0.0),
                    supporting_examples=s.get("supporting_examples", []),
                    analysis_detail=s.get("analysis_detail", ""),
                    impact=s.get("impact", ""),
                    approved=s.get("approved", False),
                    votes=s.get("votes", []),
                    applied=s.get("applied", False),
                    applied_at=s.get("applied_at", None)
                ))

            return EnhancedOptimizationReport(
                generated_at=report_dict.get("generated_at", time.time()),
                analysis_summary=report_dict.get("analysis_summary", ""),
                suggestions=suggestions,
                voting_required=report_dict.get("voting_required", True),
                approved=report_dict.get("approved", False),
                votes=report_dict.get("votes", []),
                applied_at=report_dict.get("applied_at", None),
                applied_suggestions=report_dict.get("applied_suggestions", []),
                report_path=Path(filepath).name if filepath else "",
            )
        except Exception as e:
            logger.error(f"Failed to load enhanced report: {e}")
            return None

    # 兼容旧格式的方法
    def _save_report(self, report: SkillOptimizationReport) -> str:
        """保存报告（旧格式兼容）"""
        filename = f"skill_opt_{int(report.generated_at)}.json"
        filepath = REPORTS_DIR / filename

        report_dict = {
            "generated_at": report.generated_at,
            "suggestion_count": report.suggestion_count,
            "suggestions": [
                {
                    "skill_name": s.skill_name,
                    "suggestion_type": s.suggestion_type,
                    "current_value": s.current_value,
                    "suggested_value": s.suggested_value,
                    "reason": s.reason,
                    "confidence": s.confidence,
                    "supporting_examples": s.supporting_examples,
                    "analysis_detail": s.analysis_detail,
                    "impact": s.impact,
                    "related_skill_names": s.related_skill_names if hasattr(s, "related_skill_names") else [],
                    "suggested_skill_names": s.suggested_skill_names if hasattr(s, "suggested_skill_names") else [],
                }
                for s in report.suggestions
            ],
            "analysis_summary": report.analysis_summary,
            "voting_required": report.voting_required,
            "votes": report.votes,
            "approved": report.approved,
            "report_path": filename,
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report_dict, f, ensure_ascii=False, indent=2)

        return filename

    def _load_report(self, filepath: str) -> Optional[SkillOptimizationReport]:
        """加载报告（旧格式兼容）"""
        try:
            path = Path(filepath)
            if not path.exists():
                path = REPORTS_DIR / filepath
            if not path.exists():
                path = REPORTS_DIR / f"{filepath}.json"
            if not path.exists():
                return None

            with open(path, 'r', encoding='utf-8') as f:
                report_dict = json.load(f)

            suggestions = [
                SkillOptimizationSuggestion(
                    skill_name=s.get("skill_name", ""),
                    suggestion_type=s.get("suggestion_type", ""),
                    current_value=s.get("current_value", ""),
                    suggested_value=s.get("suggested_value", ""),
                    reason=s.get("reason", ""),
                    confidence=s.get("confidence", 0.0),
                    supporting_examples=s.get("supporting_examples", []),
                    analysis_detail=s.get("analysis_detail", ""),
                    impact=s.get("impact", ""),
                    related_logs=[],
                    related_skill_names=s.get("related_skill_names", []),
                    suggested_skill_names=s.get("suggested_skill_names", []),
                )
                for s in report_dict.get("suggestions", [])
            ]

            return SkillOptimizationReport(
                generated_at=report_dict.get("generated_at", time.time()),
                suggestion_count=report_dict.get("suggestion_count", 0),
                suggestions=suggestions,
                analysis_summary=report_dict.get("analysis_summary", ""),
                voting_required=report_dict.get("voting_required", True),
                votes=report_dict.get("votes", []),
                approved=report_dict.get("approved", False),
                report_path=Path(filepath).name if filepath else "",
            )
        except Exception as e:
            logger.error(f"Failed to load report: {e}")
            return None

    async def add_vote(
        self, report_path: str, voter: str, vote: bool, comment: str = ""
    ) -> Dict:
        """添加投票（单人模式：任何通过即批准）"""
        report = self._load_report(report_path)
        if report is None:
            return {"success": False, "error": "Report not found"}

        existing_idx = None
        for i, v in enumerate(report.votes):
            if v.get("voter") == voter:
                existing_idx = i
                break

        vote_dict = {
            "voter": voter,
            "vote": vote,
            "comment": comment,
            "timestamp": time.time(),
        }

        if existing_idx is not None:
            report.votes[existing_idx] = vote_dict
        else:
            report.votes.append(vote_dict)

        # 单人模式：任何通过的投票都直接批准
        if vote:
            report.approved = True

        self._save_report(report)

        return {
            "success": True,
            "approved": report.approved,
            "votes": report.votes,
        }

    async def apply_suggestions(self, report: SkillOptimizationReport) -> Dict:
        """应用建议（需要已批准）"""
        if not report.approved:
            return {"success": False, "error": "Report not approved"}

        results = {"success": True, "applied_count": 0, "skipped_count": 0, "errors": []}

        for suggestion in report.suggestions:
            try:
                if suggestion.suggestion_type == "new_skill":
                    await self._create_new_skill(suggestion)
                elif suggestion.suggestion_type == "skill_split":
                    await self._split_skill(suggestion)
                elif suggestion.suggestion_type == "skill_merge":
                    await self._merge_skills(suggestion)
                elif suggestion.suggestion_type == "skill_deprecate":
                    await self._deprecate_skill(suggestion)
                else:
                    await self._update_existing_skill(suggestion)
                results["applied_count"] += 1
            except Exception as e:
                logger.error(f"Failed to apply suggestion for {suggestion.skill_name}: {e}")
                results["errors"].append(f"{suggestion.skill_name}: {e}")
                results["skipped_count"] += 1

        return results

    async def _create_new_skill(self, suggestion):
        """创建新 Skill"""
        skill_name = re.sub(r'[^\w\-]', '_', suggestion.skill_name).lower()
        skill_dir = SKILLS_DIR / skill_name
        skill_dir.mkdir(exist_ok=True)
        content = f"""---
name: {skill_name}
description: {suggestion.suggested_value}
version: 1.0.0
tags: ["new"]
triggers: []
---

# {skill_name}

## Overview
{suggestion.reason}

## When to Use
待补充...

## How It Works
待补充...
"""
        with open(skill_dir / "SKILL.md", 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info(f"Created skill: {skill_name}")

    async def _update_existing_skill(self, suggestion):
        """更新现有 Skill"""
        skill_name = suggestion.skill_name
        skill_dir = SKILLS_DIR / skill_name
        if not skill_dir.exists():
            skill_dir = SKILLS_DIR / skill_name.replace("-", "_")
        if not skill_dir.exists():
            raise ValueError(f"Skill not found: {skill_name}")
        skill_file = skill_dir / "SKILL.md"
        backup_path = self._backup_skill(skill_name, skill_file)
        with open(skill_file, 'r', encoding='utf-8') as f:
            content = f.read()
        new_content = self._modify_skill_content(content, suggestion)
        with open(skill_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        logger.info(f"Updated skill: {skill_name} (backup: {backup_path})")

    async def _split_skill(self, suggestion):
        """拆分 Skill"""
        skill_name = suggestion.skill_name
        skill_dir = SKILLS_DIR / skill_name
        if not skill_dir.exists():
            skill_dir = SKILLS_DIR / skill_name.replace("-", "_")
        if not skill_dir.exists():
            raise ValueError(f"Skill not found: {skill_name}")
        skill_file = skill_dir / "SKILL.md"
        backup_path = self._backup_skill(skill_name, skill_file)
        with open(skill_file, 'r', encoding='utf-8') as f:
            content = f.read()
        frontmatter_match = FRONTMATTER_RE.match(content)
        if frontmatter_match:
            frontmatter_str = frontmatter_match.group(1)
            body = content[frontmatter_match.end():]
            frontmatter = self._parse_simple_frontmatter(frontmatter_str)
            if "tags" in frontmatter:
                if "deprecated" not in frontmatter["tags"]:
                    frontmatter["tags"].append("deprecated")
            else:
                frontmatter["tags"] = ["deprecated"]
            new_frontmatter = self._generate_frontmatter(frontmatter)
            with open(skill_file, 'w', encoding='utf-8') as f:
                f.write(f"{new_frontmatter}\n{body}")
        logger.info(f"Marked for split: {skill_name}")

    async def _merge_skills(self, suggestion):
        """合并 Skills"""
        all_names = [suggestion.skill_name] + (suggestion.related_skill_names if hasattr(suggestion, "related_skill_names") else [])
        for name in all_names:
            skill_dir = SKILLS_DIR / name
            if not skill_dir.exists():
                skill_dir = SKILLS_DIR / name.replace("-", "_")
            if not skill_dir.exists():
                continue
            skill_file = skill_dir / "SKILL.md"
            self._backup_skill(name, skill_file)
            with open(skill_file, 'r', encoding='utf-8') as f:
                content = f.read()
            frontmatter_match = FRONTMATTER_RE.match(content)
            if frontmatter_match:
                frontmatter_str = frontmatter_match.group(1)
                body = content[frontmatter_match.end():]
                frontmatter = self._parse_simple_frontmatter(frontmatter_str)
                if "tags" in frontmatter:
                    if "deprecated" not in frontmatter["tags"]:
                        frontmatter["tags"].append("deprecated")
                else:
                    frontmatter["tags"] = ["deprecated"]
                new_frontmatter = self._generate_frontmatter(frontmatter)
                with open(skill_file, 'w', encoding='utf-8') as f:
                    f.write(f"{new_frontmatter}\n{body}")
        logger.info(f"Marked for merge: {all_names}")

    async def _deprecate_skill(self, suggestion):
        """废弃 Skill"""
        skill_name = suggestion.skill_name
        skill_dir = SKILLS_DIR / skill_name
        if not skill_dir.exists():
            skill_dir = SKILLS_DIR / skill_name.replace("-", "_")
        if not skill_dir.exists():
            raise ValueError(f"Skill not found: {skill_name}")
        timestamp = int(time.time())
        deprecated_dir = DEPRECATED_DIR / f"{skill_name}_v{timestamp}"
        shutil.copytree(skill_dir, deprecated_dir)
        shutil.rmtree(skill_dir)
        logger.info(f"Deprecated skill: {skill_name} (moved to {deprecated_dir})")

    def _backup_skill(self, skill_name: str, skill_file: Path) -> Path:
        """备份 Skill"""
        timestamp = int(time.time())
        backup_file = SKILL_BACKUP_DIR / f"{skill_name}_v{timestamp}.md"
        shutil.copy2(skill_file, backup_file)
        return backup_file

    def _modify_skill_content(self, content: str, suggestion) -> str:
        """修改 Skill 内容（纯函数）"""
        frontmatter_match = FRONTMATTER_RE.match(content)
        if not frontmatter_match:
            return content

        frontmatter_str = frontmatter_match.group(1)
        body = content[frontmatter_match.end():]
        frontmatter = self._parse_simple_frontmatter(frontmatter_str)
        sug_type = suggestion.suggestion_type

        if sug_type == "trigger_add":
            if "triggers" not in frontmatter:
                frontmatter["triggers"] = []
            if isinstance(frontmatter["triggers"], list):
                val = suggestion.suggested_value
                if val and val not in frontmatter["triggers"]:
                    frontmatter["triggers"].append(val)
        elif sug_type == "trigger_remove":
            if "triggers" in frontmatter and isinstance(frontmatter["triggers"], list):
                val = suggestion.current_value
                if val in frontmatter["triggers"]:
                    frontmatter["triggers"].remove(val)
        elif sug_type == "description_update":
            frontmatter["description"] = suggestion.suggested_value
        elif sug_type == "tag_add":
            if "tags" not in frontmatter:
                frontmatter["tags"] = []
            if isinstance(frontmatter["tags"], list):
                val = suggestion.suggested_value
                if val and val not in frontmatter["tags"]:
                    frontmatter["tags"].append(val)
        elif sug_type == "tag_remove":
            if "tags" in frontmatter and isinstance(frontmatter["tags"], list):
                val = suggestion.current_value
                if val in frontmatter["tags"]:
                    frontmatter["tags"].remove(val)

        new_frontmatter = self._generate_frontmatter(frontmatter)
        return f"{new_frontmatter}\n{body}"

    def _parse_simple_frontmatter(self, frontmatter_text: str) -> Dict:
        """简单解析 frontmatter"""
        lines = frontmatter_text.splitlines()
        frontmatter = {}
        current_key = None
        current_list = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('- '):
                if current_key:
                    val = line[2:].strip()
                    try:
                        parsed = json.loads(val)
                        current_list.append(parsed)
                    except Exception:
                        current_list.append(val)
                    frontmatter[current_key] = current_list
            elif ':' in line:
                key, val = line.split(':', 1)
                key = key.strip()
                val = val.strip()
                current_key = key
                current_list = []
                if val.startswith('[') or val.startswith('{'):
                    try:
                        frontmatter[key] = json.loads(val)
                    except Exception:
                        frontmatter[key] = val
                elif val:
                    frontmatter[key] = val
        return frontmatter

    def _generate_frontmatter(self, frontmatter: Dict) -> str:
        """生成 frontmatter 字符串"""
        lines = ['---']
        for key, val in frontmatter.items():
            if isinstance(val, list):
                lines.append(f'{key}:')
                for item in val:
                    if isinstance(item, dict):
                        lines.append(f'  - {json.dumps(item, ensure_ascii=False)}')
                    else:
                        lines.append(f'  - {item}')
            else:
                lines.append(f'{key}: {val}')
        lines.append('---')
        return '\n'.join(lines)


_skill_optimization_agent: Optional[SkillOptimizationAgent] = None


def get_skill_optimization_agent() -> SkillOptimizationAgent:
    global _skill_optimization_agent
    if _skill_optimization_agent is None:
        _skill_optimization_agent = SkillOptimizationAgent()
    return _skill_optimization_agent
