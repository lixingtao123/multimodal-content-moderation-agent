"""
Skill 自优化模块 v2.0

基于路由日志和标注数据，自动优化 Skills：
- 分析哪些 Skill 应该被选中但没被选中
- 优化 Skill 的 triggers（触发词）
- 优化 Skill 的 description（描述）
- 优化 Skill 的 tags（标签）
- 识别应该新增的 Skill 场景

优化流程：
1. 收集：Skill 路由日志 + 人工标注数据
2. 分析：启发式规则分析（不依赖 LLM）
3. 建议：生成优化建议
4. 评审：三方评审 + 2-of-3 投票机制
5. 执行：自动更新 Skill 文件
6. 版本：保留历史版本，支持回滚
"""
import json
import os
import time
import logging
import re
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path

from agent_moderation.skill_registry import get_skill_registry

logger = logging.getLogger(__name__)


# ============================================================
# 数据结构
# ============================================================

@dataclass
class SkillOptimizationSuggestion:
    """Skill 优化建议"""
    skill_name: str
    suggestion_type: str           # trigger_add / trigger_remove / description_update / tag_add / tag_remove / new_skill
    current_value: str = ""
    suggested_value: str = ""
    reason: str = ""
    confidence: float = 0.0
    supporting_examples: List[str] = field(default_factory=list)


@dataclass
class SkillOptimizationReport:
    """Skill 优化报告"""
    generated_at: float
    suggestion_count: int
    suggestions: List[SkillOptimizationSuggestion]
    analysis_summary: str
    voting_required: bool = True
    votes: List[Dict] = field(default_factory=list)
    approved: bool = False
    report_path: str = ""


@dataclass
class SkillVersion:
    """Skill 版本（用于回滚）"""
    name: str
    version: str
    frontmatter: Dict
    body: str
    created_at: float


# ============================================================
# Skill 优化 Agent
# ============================================================

class SkillOptimizer:
    """
    Skill 优化器 - 分析路由日志，生成优化建议
    """

    SKILLS_DIR = "/workspace/skills"
    SKILL_BACKUP_DIR = "/workspace/skills_backups"
    REPORTS_DIR = "/workspace/skills_backups/reports"

    def __init__(self):
        self._registry = None
        self._lock = False
        # 确保备份目录存在
        Path(self.SKILL_BACKUP_DIR).mkdir(exist_ok=True)
        Path(self.REPORTS_DIR).mkdir(exist_ok=True)

    @property
    def registry(self):
        if self._registry is None:
            self._registry = get_skill_registry()
        return self._registry

    async def analyze_and_suggest(self, log_dir: str = '/tmp/skill_logs',
                              min_logs: int = 10) -> Optional[SkillOptimizationReport]:
        """
        分析路由日志并生成优化建议

        Args:
            log_dir: Skill 路由日志目录
            min_logs: 最少日志数

        Returns:
            SkillOptimizationReport 或 None
        """
        if self._lock:
            logger.info("[SkillOptimizer] Already running, skip")
            return None

        self._lock = True
        try:
            # 1. 从数据库加载路由日志
            routing_logs = await self._load_routing_logs_from_db()

            if len(routing_logs) < min_logs:
                # 如果数据库中不够，尝试从文件加载
                file_logs = self._load_routing_logs_from_file(log_dir)
                routing_logs.extend(file_logs)

            if len(routing_logs) < min_logs:
                logger.info(f"[SkillOptimizer] Only {len(routing_logs)} logs, needs {min_logs}")
                return None

            logger.info(f"[SkillOptimizer] Analyzing {len(routing_logs)} routing logs")

            # 2. 分析日志，生成建议（启发式规则，不依赖 LLM）
            suggestions = await self._generate_suggestions_heuristic(routing_logs)

            # 3. 生成报告
            analysis_summary = self._generate_analysis_summary(suggestions, routing_logs)

            report = SkillOptimizationReport(
                generated_at=time.time(),
                suggestion_count=len(suggestions),
                suggestions=suggestions,
                analysis_summary=analysis_summary,
                voting_required=True,
            )

            # 4. 保存报告
            report_path = self._save_report(report)
            report.report_path = report_path

            return report
        finally:
            self._lock = False

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
                        "filtered": log.filtered_skills,
                        "ranked": log.ranked_skills,
                        "selected": log.selected_skills,
                        "timestamp": log.timestamp.timestamp() if log.timestamp else time.time(),
                    })
        except Exception as e:
            logger.warning(f"Failed to load routing logs from DB: {e}")
        return logs

    def _load_routing_logs_from_file(self, log_dir: str) -> List[Dict]:
        """从文件系统加载路由日志"""
        logs = []
        log_path = Path(log_dir)
        if not log_path.exists():
            return logs

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

    async def _generate_suggestions_heuristic(self, routing_logs: List[Dict]) -> List[SkillOptimizationSuggestion]:
        """使用启发式规则生成优化建议"""
        suggestions = []

        # 1. 统计每个 Skill 的使用情况
        skill_stats = self._compute_skill_stats(routing_logs)

        all_skills = {s.name for s in self.registry.list_skills()}

        # 2. 找出未被充分使用的 Skill（可能需要优化 triggers/description）
        for skill_meta in self.registry.list_skills():
            name = skill_meta.name
            stats = skill_stats.get(name, {"count": 0, "queries": []})
            count = stats["count"]

            # 分析应该命中但没命中的查询
            missed_queries = self._find_missed_queries(name, routing_logs)

            if missed_queries and count < 20:  # 如果使用次数较少，且有潜在相关查询
                # 从 missed_queries 中提取关键词，建议添加 triggers
                suggested_triggers = self._extract_potential_triggers(missed_queries, skill_meta)
                if suggested_triggers:
                    for trigger in suggested_triggers[:3]:  # 最多 3 个建议
                        suggestions.append(SkillOptimizationSuggestion(
                            skill_name=name,
                            suggestion_type='trigger_add',
                            current_value='',
                            suggested_value=trigger,
                            reason=f"'{trigger}' appears in {len(missed_queries)} queries that didn't select {name}",
                            confidence=0.6,
                            supporting_examples=missed_queries[:5],
                        ))

            # 如果完全没被使用，建议优化描述或标签
            if count == 0 and missed_queries:
                suggestions.append(SkillOptimizationSuggestion(
                    skill_name=name,
                    suggestion_type='description_update',
                    current_value=skill_meta.description,
                    suggested_value=self._suggest_improved_description(skill_meta, missed_queries),
                    reason=f"{name} is never selected but {len(missed_queries)} potentially relevant queries exist",
                    confidence=0.5,
                    supporting_examples=missed_queries[:5],
                ))

        # 3. 找出频繁被使用的 Skill（可能需要拆分）
        for name, stats in skill_stats.items():
            if stats["count"] > 50 and name in all_skills:
                suggestions.append(SkillOptimizationSuggestion(
                    skill_name=name,
                    suggestion_type='analysis_only',
                    reason=f"{name} is selected {stats['count']} times - consider analyzing if it should be split",
                    confidence=0.4,
                ))

        # 4. 分析经常一起出现的查询，建议新增 Skill
        cluster_suggestions = self._find_new_skill_suggestions(routing_logs)
        suggestions.extend(cluster_suggestions)

        return suggestions

    def _compute_skill_stats(self, routing_logs: List[Dict]) -> Dict[str, Dict]:
        """统计每个 Skill 的使用情况"""
        skill_stats = {}
        for log in routing_logs:
            selected = log.get('selected', [])
            query = log.get('query', '')
            for skill in selected:
                if skill not in skill_stats:
                    skill_stats[skill] = {"count": 0, "queries": []}
                skill_stats[skill]["count"] += 1
                if query:
                    skill_stats[skill]["queries"].append(query)
        return skill_stats

    def _find_missed_queries(self, skill_name: str, routing_logs: List[Dict]) -> List[str]:
        """找出应该命中某个 Skill 但没命中的查询"""
        meta = None
        for m in self.registry.list_skills():
            if m.name == skill_name:
                meta = m
                break

        if not meta:
            return []

        missed = []
        # 从 skill 的 description、tags、triggers 中提取关键词
        keywords = set()

        for tag in meta.tags or []:
            keywords.add(tag.lower())
        for trigger in meta.triggers or []:
            if isinstance(trigger, str):
                keywords.add(trigger.lower())
            elif isinstance(trigger, dict):
                for v in trigger.values():
                    if isinstance(v, str):
                        keywords.add(v.lower())
        for word in (meta.description or "").lower().split():
            if len(word) >= 3:
                keywords.add(word)

        if not keywords:
            return []

        for log in routing_logs:
            if skill_name not in log.get('selected', []):
                query = log.get('query', '').lower()
                if query and any(kw in query for kw in keywords):
                    missed.append(log.get('query', ''))

        return list(set(missed))[:20]

    def _extract_potential_triggers(self, missed_queries: List[str], skill_meta) -> List[str]:
        """从 missed_queries 中提取潜在的 trigger 词"""
        from collections import Counter

        word_count = Counter()
        stop_words = {"的", "了", "在", "是", "就", "都", "而", "及", "与", "和", "或", "但", "也", "这", "那", "有", "没", "不", "很", "太", "最", "更", "比", "让", "把", "被", "给", "到", "从", "向", "往", "朝", "当", "对", "于", "就", "才", "刚", "正", "在", "已", "经", "将", "要", "会", "可", "能", "应", "该", "想", "要", "希", "望", "可", "以", "能", "够", "需", "要", "必", "须", "应", "该"}

        for query in missed_queries:
            words = re.findall(r'[\w一-鿿]+', query.lower())
            for word in words:
                if len(word) >= 2 and word not in stop_words:
                    word_count[word] += 1

        suggested = []
        for word, count in word_count.most_common(10):
            if count >= 2:  # 至少出现 2 次
                # 检查是否已在现有 triggers/tags 中
                exists = False
                for tag in skill_meta.tags or []:
                    if word in tag.lower():
                        exists = True
                        break
                for trigger in skill_meta.triggers or []:
                    if isinstance(trigger, str) and word in trigger.lower():
                        exists = True
                        break
                if not exists:
                    suggested.append(word)
        return suggested

    def _suggest_improved_description(self, skill_meta, missed_queries: List[str]) -> str:
        """建议改进的 description"""
        if not missed_queries:
            return skill_meta.description

        sample_queries = ", ".join(q[:30] for q in missed_queries[:3])
        return f"{skill_meta.description} (Consider adding keywords related to: {sample_queries}"

    def _find_new_skill_suggestions(self, routing_logs: List[Dict]) -> List[SkillOptimizationSuggestion]:
        """找出应该新增 Skill 的场景"""
        suggestions = []

        # 统计常见查询模式
        from collections import defaultdict
        text_queries = [log.get('query', '') for log in routing_logs if log.get('content_type') == 'text' and log.get('query')]

        # 简单分析：如果有很多查询没有选中任何 Skills
        unselected_queries = []
        for log in routing_logs:
            if not log.get('selected', []):
                q = log.get('query')
                if q:
                    unselected_queries.append(q)

        if len(unselected_queries) >= 10:
            suggestions.append(SkillOptimizationSuggestion(
                skill_name='new_skill_general',
                suggestion_type='new_skill',
                suggested_value='General content analysis skill',
                reason=f"{len(unselected_queries)} queries didn't select any skill",
                confidence=0.4,
                supporting_examples=unselected_queries[:10],
            ))

        return suggestions

    def _generate_analysis_summary(self, suggestions: List[SkillOptimizationSuggestion], routing_logs: List[Dict]) -> str:
        """生成分析摘要"""
        total_logs = len(routing_logs)

        # 统计各类型的建议数
        type_counts = {}
        for s in suggestions:
            t = s.suggestion_type
            type_counts[t] = type_counts.get(t, 0) + 1

        type_summary = ", ".join(f"{t}: {c}" for t, c in type_counts.items())

        return f"Analyzed {total_logs} logs, generated {len(suggestions)} suggestions ({type_summary})"

    async def apply_suggestions(self, report: SkillOptimizationReport) -> Dict:
        """
        应用优化建议（需要已投票通过）

        Args:
            report: 优化报告

        Returns:
            应用结果 dict
        """
        if not report.approved:
            return {"success": False, "error": "Report not approved"}

        results = {
            "success": True,
            "applied_count": 0,
            "skipped_count": 0,
            "errors": [],
        }

        for suggestion in report.suggestions:
            try:
                if suggestion.suggestion_type == 'analysis_only':
                    results["skipped_count"] += 1
                    continue

                await self._apply_one_suggestion(suggestion)
                results["applied_count"] += 1
            except Exception as e:
                logger.error(f"Failed to apply suggestion for {suggestion.skill_name}: {e}")
                results["errors"].append(f"{suggestion.skill_name}: {e}")
                results["skipped_count"] += 1

        return results

    async def add_vote(self, report_path: str, voter: str, vote: bool, comment: str = "") -> Dict:
        """
        添加评审投票

        Args:
            report_path: 报告文件路径
            voter: 投票人
            vote: True=通过, False=拒绝
            comment: 评论

        Returns:
            投票结果 dict
        """
        # 加载报告
        report = self._load_report(report_path)
        if not report:
            return {"success": False, "error": "Report not found"}

        # 检查是否已投票过
        existing_vote = None
        for v in report.votes:
            if v.get("voter") == voter:
                existing_vote = v
                break

        if existing_vote:
            existing_vote["vote"] = vote
            existing_vote["comment"] = comment
            existing_vote["timestamp"] = time.time()
        else:
            report.votes.append({
                "voter": voter,
                "vote": vote,
                "comment": comment,
                "timestamp": time.time(),
            })

        # 检查是否达到 2-of-3 通过条件
        approve_count = sum(1 for v in report.votes if v.get("vote"))
        total_count = len(report.votes)

        if total_count >= 3 and approve_count >= 2:
            report.approved = True
            logger.info(f"[SkillOptimizer] Report approved ({approve_count}/{total_count})")

        # 保存报告
        self._save_report(report)

        return {
            "success": True,
            "approved": report.approved,
            "votes": report.votes,
        }

    async def _apply_one_suggestion(self, suggestion: SkillOptimizationSuggestion) -> None:
        """应用单条优化建议"""
        if suggestion.suggestion_type == 'new_skill':
            await self._create_new_skill(suggestion)
        else:
            await self._update_existing_skill(suggestion)

    async def _create_new_skill(self, suggestion: SkillOptimizationSuggestion) -> None:
        """创建新 Skill"""
        skill_name = suggestion.skill_name
        skill_dir = Path(self.SKILLS_DIR) / skill_name
        skill_dir.mkdir(exist_ok=True)

        skill_content = f"""---
name: {skill_name}
description: {suggestion.suggested_value or skill_name}
version: 1.0.0
tags: ["new"]
triggers: []
---

# {skill_name}

## Overview
{suggestion.reason or "Auto-generated skill"}
"""
        with open(skill_dir / "SKILL.md", 'w', encoding='utf-8') as f:
            f.write(skill_content)

        logger.info(f"[SkillOptimizer] Created new skill: {skill_name}")

    async def _update_existing_skill(self, suggestion: SkillOptimizationSuggestion) -> None:
        """更新现有 Skill"""
        skill_name = suggestion.skill_name
        skill_dir = Path(self.SKILLS_DIR) / skill_name

        if not skill_dir.exists():
            # 尝试下划线命名
            skill_dir = Path(self.SKILLS_DIR) / skill_name.replace('-', '_')

        if not skill_dir.exists():
            raise ValueError(f"Skill not found: {skill_name}")

        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            raise ValueError(f"Skill file not found: {skill_file}")

        # 备份
        self._backup_skill(skill_name, skill_file)

        # 读取并更新
        with open(skill_file, 'r', encoding='utf-8') as f:
            content = f.read()

        new_content = self._modify_skill_content(content, suggestion)

        with open(skill_file, 'w', encoding='utf-8') as f:
            f.write(new_content)

        logger.info(f"[SkillOptimizer] Updated skill: {skill_name}")

    def _modify_skill_content(self, content: str, suggestion: SkillOptimizationSuggestion) -> str:
        """修改 Skill 内容"""
        # 解析 frontmatter
        frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
        if not frontmatter_match:
            return content

        frontmatter_str = frontmatter_match.group(1)
        body = content[frontmatter_match.end():]

        frontmatter = self._parse_simple_frontmatter(frontmatter_str)

        # 应用修改
        if suggestion.suggestion_type == 'trigger_add':
            if 'triggers' not in frontmatter:
                frontmatter['triggers'] = []
            if isinstance(frontmatter['triggers'], list):
                if suggestion.suggested_value and suggestion.suggested_value not in frontmatter['triggers']:
                    frontmatter['triggers'].append(suggestion.suggested_value)

        elif suggestion.suggestion_type == 'trigger_remove':
            if 'triggers' in frontmatter and isinstance(frontmatter['triggers'], list):
                if suggestion.current_value in frontmatter['triggers']:
                    frontmatter['triggers'].remove(suggestion.current_value)

        elif suggestion.suggestion_type == 'description_update':
            frontmatter['description'] = suggestion.suggested_value

        elif suggestion.suggestion_type == 'tag_add':
            if 'tags' not in frontmatter:
                frontmatter['tags'] = []
            if isinstance(frontmatter['tags'], list) and suggestion.suggested_value:
                if suggestion.suggested_value not in frontmatter['tags']:
                    frontmatter['tags'].append(suggestion.suggested_value)

        elif suggestion.suggestion_type == 'tag_remove':
            if 'tags' in frontmatter and isinstance(frontmatter['tags'], list):
                if suggestion.current_value in frontmatter['tags']:
                    frontmatter['tags'].remove(suggestion.current_value)

        # 重新生成 frontmatter
        new_frontmatter = self._generate_frontmatter(frontmatter)

        return f"{new_frontmatter}\n{body}"

    def _parse_simple_frontmatter(self, frontmatter_str: str) -> Dict:
        """简单解析 frontmatter"""
        lines = frontmatter_str.splitlines()
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
                else:
                    # 开始一个列表
                    pass
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

    def _backup_skill(self, skill_name: str, skill_file: Path) -> None:
        """备份 Skill 文件"""
        backup_dir = Path(self.SKILL_BACKUP_DIR)
        backup_dir.mkdir(exist_ok=True)

        timestamp = int(time.time())
        backup_file = backup_dir / f"{skill_name}_v{timestamp}.md"

        import shutil
        shutil.copy2(skill_file, backup_file)
        logger.debug(f"[SkillOptimizer] Backed up {skill_name} to {backup_file}")

    def _save_report(self, report: SkillOptimizationReport) -> str:
        """保存优化报告"""
        reports_dir = Path(self.REPORTS_DIR)
        reports_dir.mkdir(exist_ok=True)

        filename = f"skill_opt_{int(report.generated_at)}.json"
        filepath = reports_dir / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump({
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
                    }
                    for s in report.suggestions
                ],
                "analysis_summary": report.analysis_summary,
                "voting_required": report.voting_required,
                "votes": report.votes,
                "approved": report.approved,
                "report_path": str(filepath),
            }, f, ensure_ascii=False, indent=2)

        return str(filepath)

    def _load_report(self, filepath: str) -> Optional[SkillOptimizationReport]:
        """加载优化报告"""
        try:
            # 如果不是完整路径，尝试在 reports 目录中找
            path = Path(filepath)
            if not path.exists():
                path = Path(self.REPORTS_DIR) / filepath
                if not path.exists():
                    path = Path(self.REPORTS_DIR) / f"{filepath}.json"

            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            suggestions = [
                SkillOptimizationSuggestion(**s)
                for s in data.get('suggestions', [])
            ]

            return SkillOptimizationReport(
                generated_at=data.get('generated_at', time.time()),
                suggestion_count=data.get('suggestion_count', 0),
                suggestions=suggestions,
                analysis_summary=data.get('analysis_summary', ''),
                voting_required=data.get('voting_required', True),
                votes=data.get('votes', []),
                approved=data.get('approved', False),
                report_path=str(path),
            )
        except Exception as e:
            logger.error(f"Failed to load report {filepath}: {e}")
            return None


# ============================================================
# 全局单例
# ============================================================

_skill_optimizer: Optional[SkillOptimizer] = None


def get_skill_optimizer() -> SkillOptimizer:
    global _skill_optimizer
    if _skill_optimizer is None:
        _skill_optimizer = SkillOptimizer()
    return _skill_optimizer
