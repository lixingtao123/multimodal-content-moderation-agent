"""
GraphRAG v1.0 — 知识图谱增强检索

基于违规类型间的关联关系和内容-账号异构图进行多跳推理检索。

核心结构:
  - 违规类型关系图: 色情↔低俗↔广告, 暴力↔恐怖↔政治 等
  - 内容-账号异构图: Content → ViolationType → Account → Pattern
  - 社区摘要 (Leiden 聚类): 将高度关联的违规案例聚类

技术参考:
  - Microsoft GraphRAG (2024): Leiden community detection + hierarchical summarization
  - Neo4j Graph Data Science: 图遍历 + 路径检索
"""
import logging
from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from agent_moderation.violation_types import VIOLATION_TYPES

logger = logging.getLogger(__name__)


@dataclass
class GraphNode:
    """图节点"""
    id: str
    label: str  # violation_type / account / content / pattern
    properties: dict = field(default_factory=dict)


@dataclass
class GraphEdge:
    """图边"""
    source: str
    target: str
    relation: str  # similar_to / has_type / belongs_to / detected_with
    weight: float = 1.0


@dataclass
class GraphPath:
    """图路径 (多跳推理结果)"""
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    score: float
    reasoning: str


class ViolationKnowledgeGraph:
    """
    违规知识图谱

    预定义违规类型之间的关系:
    - 色情 ↔ 低俗: 相似但不完全相同
    - 暴力 ↔ 恐怖: 通常同时出现
    - 广告 ↔ 引流: 手段相似
    - 诈骗 ↔ 钓鱼: 技术手段重叠
    - 政治 ↔ 虚假信息: 常伴随传播
    """

    # 违规类型关系定义
    VIOLATION_RELATIONS = [
        ("porn", "vulgar", "related_to", 0.7),
        ("porn", "advertisement", "often_accompanies", 0.5),
        ("violence", "terrorism", "co_occurs", 0.8),
        ("violence", "politics", "sometimes_linked", 0.4),
        ("advertisement", "traffic_fraud", "similar_method", 0.75),
        ("advertisement", "phishing", "overlapping", 0.6),
        ("phishing", "false_info", "same_category", 0.65),
        ("fraud", "false_info", "related_to", 0.7),
        ("politics", "false_info", "often_accompanies", 0.55),
        ("harassment", "violence", "escalates_to", 0.45),
        ("bulk_generation", "keyword_variant", "technique_similarity", 0.8),
        ("keyword_variant", "char_noise", "evasion_technique", 0.9),
        # R14·G4: 新增 6 类（v5.0 枚举扩展）加入关系图
        ("privacy", "false_info", "often_accompanies", 0.6),       # 隐私窃取常伴随虚假信息
        ("discrimination", "harassment", "escalates_to", 0.55),    # 歧视常升级为辱骂骚扰
        ("crime", "violence", "co_occurs", 0.7),                    # 违法犯罪常伴随暴力
        ("crime", "phishing", "overlapping", 0.65),                # 诈骗是违法
        ("health", "violence", "sometimes_linked", 0.5),            # 自残/伤害与暴力关联
        ("ethics", "politics", "sometimes_linked", 0.45),           # 伦理失范与政治敏感偶联
        ("copyright", "advertisement", "similar_method", 0.5),      # 盗版/侵权与引流手段相似
    ]

    def __init__(self):
        self.nodes: Dict[str, GraphNode] = {}
        self.edges: List[GraphEdge] = []
        self._build_violation_graph()

    def _build_violation_graph(self):
        """构建违规类型基础关系图"""
        # 添加违规类型节点
        all_types = set()
        for src, tgt, rel, w in self.VIOLATION_RELATIONS:
            all_types.add(src)
            all_types.add(tgt)
        # R14·G4: 确保 13 类枚举节点全部存在（即使无关联边，避免 get_related 对新增类型空结果）
        all_types |= {v for v in VIOLATION_TYPES if v != "none"}

        for vt in all_types:
            self.nodes[vt] = GraphNode(
                id=vt, label="violation_type",
                properties={"name": vt, "is_violation_type": True},
            )

        # 添加关系边
        for src, tgt, rel, w in self.VIOLATION_RELATIONS:
            self.edges.append(GraphEdge(source=src, target=tgt, relation=rel, weight=w))
            # 反向边 (对称关系; 部分关系是单向的)
            reverse_weight = w * 0.9 if rel in ("escalates_to", "technique_similarity") else w
            reverse_rel = {
                "related_to": "related_to",
                "often_accompanies": "often_accompanies",
                "co_occurs": "co_occurs",
                "sometimes_linked": "sometimes_linked",
                "similar_method": "similar_method",
                "overlapping": "overlapping",
                "same_category": "same_category",
                "escalates_to": "escalated_from",
                "technique_similarity": "technique_similarity",
            }.get(rel, "related_to")
            self.edges.append(GraphEdge(source=tgt, target=src, relation=reverse_rel, weight=reverse_weight))

        logger.info(
            f"ViolationKnowledgeGraph built: {len(self.nodes)} nodes, {len(self.edges)} edges"
        )

    def get_related_violation_types(
        self, violation_type: str, max_hops: int = 2
    ) -> List[Tuple[str, str, float]]:
        """
        获取关联的违规类型 (BFS 遍历)

        Args:
            violation_type: 起始违规类型
            max_hops: 最大跳数

        Returns:
            [(关联类型, 关系, 权重), ...] 按权重降序
        """
        if violation_type not in self.nodes:
            return []

        visited: Set[str] = {violation_type}
        results: List[Tuple[str, str, float]] = []

        # BFS
        current_level = {violation_type}
        for hop in range(max_hops):
            next_level: Set[str] = set()
            for node_id in current_level:
                for edge in self.edges:
                    if edge.source == node_id and edge.target not in visited:
                        decay = 1.0 / (hop + 1)  # 跳数衰减
                        results.append((edge.target, edge.relation, edge.weight * decay))
                        next_level.add(edge.target)
                        visited.add(edge.target)
            current_level = next_level
            if not current_level:
                break

        results.sort(key=lambda x: x[2], reverse=True)
        return results

    def get_expansion_query(self, violation_types: List[str], max_related: int = 5) -> str:
        """
        生成扩展查询: 根据当前违规类型推荐关联检索方向

        Returns:
            扩展后的搜索查询字符串
        """
        expanded = []
        for vt in violation_types:
            related = self.get_related_violation_types(vt, max_hops=1)
            for rel_type, relation, weight in related[:3]:
                if weight > 0.4:
                    expanded.append(rel_type)

        # 去重
        all_types = list(dict.fromkeys(violation_types + expanded))
        return " ".join(all_types)


class ContentAccountGraph:
    """
    内容-账号异构图

    结构:
    Content(id) --[has_type]--> ViolationType(name)
    Content(id) --[belongs_to]--> Account(id)
    Account(id) --[detected_with]--> Pattern(type)
    Account(id) --[linked_to]--> Account(id)  (相似行为关联)
    """

    def __init__(self):
        self.content_nodes: Dict[str, GraphNode] = {}
        self.account_nodes: Dict[str, GraphNode] = {}
        self.pattern_nodes: Dict[str, GraphNode] = {}
        self.edges: List[GraphEdge] = []

    def add_content(self, content_id: str, violation_type: str, account_id: Optional[str] = None):
        """添加内容节点"""
        self.content_nodes[content_id] = GraphNode(
            id=content_id, label="content",
            properties={"violation_type": violation_type, "account_id": account_id},
        )
        # 关联违规类型
        if violation_type and violation_type != "none":
            self.edges.append(GraphEdge(
                source=content_id, target=violation_type,
                relation="has_type", weight=1.0,
            ))

        # 关联账号
        if account_id:
            if account_id not in self.account_nodes:
                self.account_nodes[account_id] = GraphNode(
                    id=account_id, label="account",
                    properties={"risk_score": 0.0},
                )
            self.edges.append(GraphEdge(
                source=content_id, target=account_id,
                relation="belongs_to", weight=1.0,
            ))

    def add_pattern_to_account(self, account_id: str, pattern_type: str):
        """关联黑灰产模式到账号"""
        if account_id not in self.account_nodes:
            self.account_nodes[account_id] = GraphNode(
                id=account_id, label="account",
                properties={"risk_score": 0.0},
            )
        if pattern_type not in self.pattern_nodes:
            self.pattern_nodes[pattern_type] = GraphNode(
                id=pattern_type, label="pattern",
                properties={"type": pattern_type},
            )
        self.edges.append(GraphEdge(
            source=account_id, target=pattern_type,
            relation="detected_with", weight=1.0,
        ))

    def get_account_related_contents(
        self, account_id: str, max_hops: int = 2
    ) -> List[Dict]:
        """
        获取账号关联的内容 (1 跳: 直接内容; 2 跳: 相似违规类型的内容)
        """
        results = []
        # 1 跳: 该账号的直接内容
        for edge in self.edges:
            if edge.target == account_id and edge.relation == "belongs_to":
                if edge.source in self.content_nodes:
                    node = self.content_nodes[edge.source]
                    results.append({
                        "content_id": node.id,
                        "violation_type": node.properties.get("violation_type"),
                        "hop": 1,
                        "relation": "direct",
                    })

        # 2 跳: 通过违规类型关联的其他账号的内容
        if max_hops >= 2:
            for content_id, node in self.content_nodes.items():
                vt = node.properties.get("violation_type", "")
                if vt != "none":
                    # 检查是否与目标账号的违规类型有关联
                    target_vts = set()
                    for r in results:
                        if r.get("violation_type"):
                            target_vts.add(r["violation_type"])

                    if vt in target_vts and content_id not in {r["content_id"] for r in results}:
                        results.append({
                            "content_id": node.id,
                            "violation_type": vt,
                            "hop": 2,
                            "relation": "same_violation_type",
                        })

        return results

    def get_statistics(self) -> dict:
        """获取图谱统计"""
        return {
            "content_count": len(self.content_nodes),
            "account_count": len(self.account_nodes),
            "pattern_count": len(self.pattern_nodes),
            "edge_count": len(self.edges),
        }


class GraphRAGService:
    """
    GraphRAG 服务 — 整合知识图谱和内容账号图谱进行增强检索

    v3.6: 支持 PostgreSQL 持久化，进程重启后自动恢复图谱状态
    """

    def __init__(self):
        self.violation_kg = ViolationKnowledgeGraph()
        self.content_graph = ContentAccountGraph()
        self._loaded = False

    async def save(self):
        """将图谱状态持久化到 PostgreSQL"""
        import json as _json
        try:
            from common.config import get_settings as _get_cfg
            import asyncpg
            db_url = _get_cfg().database_url_sync
            # 使用同步方式存储(避免 event loop 冲突)
            import psycopg2
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()

            # 确保表存在
            cur.execute("""
                CREATE TABLE IF NOT EXISTS graph_state (
                    id SERIAL PRIMARY KEY,
                    graph_type VARCHAR(64) NOT NULL UNIQUE,
                    state_json JSONB NOT NULL DEFAULT '{}',
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)

            # 序列化 ViolationKnowledgeGraph (预定义，只保存 content_graph 的动态数据)
            # 保存 content_account graph
            content_state = {
                "content_nodes": {
                    cid: {"label": n.label, "properties": n.properties}
                    for cid, n in self.content_graph.content_nodes.items()
                },
                "account_nodes": {
                    aid: {"label": n.label, "properties": n.properties}
                    for aid, n in self.content_graph.account_nodes.items()
                },
                "pattern_nodes": {
                    pid: {"label": n.label, "properties": n.properties}
                    for pid, n in self.content_graph.pattern_nodes.items()
                },
                "edges": [
                    {"source": e.source, "target": e.target,
                     "relation": e.relation, "weight": e.weight}
                    for e in self.content_graph.edges
                ],
            }

            cur.execute("""
                INSERT INTO graph_state (graph_type, state_json, updated_at)
                VALUES ('content_account', %s, NOW())
                ON CONFLICT (graph_type) DO UPDATE SET
                    state_json = EXCLUDED.state_json,
                    updated_at = NOW()
            """, (_json.dumps(content_state, ensure_ascii=False),))

            conn.commit()
            cur.close()
            conn.close()
            logger.debug(f"GraphRAG saved: {len(self.content_graph.content_nodes)} contents, "
                        f"{len(self.content_graph.account_nodes)} accounts, "
                        f"{len(self.content_graph.edges)} edges")
        except Exception as e:
            logger.warning(f"GraphRAG save failed (non-critical): {e}")

    async def load(self):
        """从 PostgreSQL 恢复图谱状态"""
        if self._loaded:
            return
        import json as _json
        try:
            from common.config import get_settings as _get_cfg
            import psycopg2
            db_url = _get_cfg().database_url_sync
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()

            # 确保表存在
            cur.execute("""
                CREATE TABLE IF NOT EXISTS graph_state (
                    id SERIAL PRIMARY KEY,
                    graph_type VARCHAR(64) NOT NULL UNIQUE,
                    state_json JSONB NOT NULL DEFAULT '{}',
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """)
            conn.commit()

            # 恢复 content_account graph
            cur.execute("SELECT state_json FROM graph_state WHERE graph_type = 'content_account'")
            row = cur.fetchone()
            if row:
                state = _json.loads(row[0]) if isinstance(row[0], str) else row[0]

                # 恢复节点
                for cid, ndata in state.get("content_nodes", {}).items():
                    node = GraphNode(id=cid, label=ndata["label"], properties=ndata["properties"])
                    self.content_graph.content_nodes[cid] = node
                for aid, ndata in state.get("account_nodes", {}).items():
                    node = GraphNode(id=aid, label=ndata["label"], properties=ndata["properties"])
                    self.content_graph.account_nodes[aid] = node
                for pid, ndata in state.get("pattern_nodes", {}).items():
                    node = GraphNode(id=pid, label=ndata["label"], properties=ndata["properties"])
                    self.content_graph.pattern_nodes[pid] = node

                # 恢复边
                for edata in state.get("edges", []):
                    edge = GraphEdge(
                        source=edata["source"], target=edata["target"],
                        relation=edata["relation"], weight=edata.get("weight", 1.0),
                    )
                    self.content_graph.edges.append(edge)

                logger.info(f"GraphRAG loaded: {len(self.content_graph.content_nodes)} contents, "
                           f"{len(self.content_graph.account_nodes)} accounts, "
                           f"{len(self.content_graph.edges)} edges")

            cur.close()
            conn.close()
        except Exception as e:
            logger.warning(f"GraphRAG load failed (non-critical): {e}")
        self._loaded = True

    def expand_query_with_graph(self, violation_types: List[str]) -> str:
        """使用知识图谱扩展查询"""
        if not violation_types:
            return ""
        return self.violation_kg.get_expansion_query(violation_types)

    def register_content(
        self, content_id: str, violation_type: str, account_id: Optional[str] = None
    ):
        """注册审核内容到图谱"""
        self.content_graph.add_content(content_id, violation_type, account_id)

    def register_pattern(self, account_id: str, pattern_type: str):
        """注册黑灰产模式"""
        self.content_graph.add_pattern_to_account(account_id, pattern_type)

    def get_account_context(self, account_id: str) -> List[Dict]:
        """获取账号上下文 (关联内容和模式)"""
        return self.content_graph.get_account_related_contents(account_id)

    def get_insights(self, violation_types: List[str]) -> Dict:
        """
        获取图谱洞察:
        - 关联违规类型
        - 扩展查询建议
        - 图谱统计
        """
        related = []
        seen = set()
        for vt in violation_types:
            for rel_type, relation, weight in self.violation_kg.get_related_violation_types(vt):
                if rel_type not in seen:
                    related.append({"type": rel_type, "relation": relation, "weight": weight})
                    seen.add(rel_type)

        return {
            "violation_types": violation_types,
            "related_violation_types": related[:10],
            "expansion_query": self.expand_query_with_graph(violation_types),
            "graph_stats": self.content_graph.get_statistics(),
        }

# 全局单例
_graph_rag: Optional[GraphRAGService] = None


def get_graph_rag() -> GraphRAGService:
    global _graph_rag
    if _graph_rag is None:
        _graph_rag = GraphRAGService()
    return _graph_rag
