"""
Agentic RAG v1.0 — 智能检索 Agent

核心能力:
  1. Query Rewriter: LLM 自动改写查询以提高召回率
  2. Retrieval Router: 根据查询类型选择最优检索策略
  3. Self-RAG: 检索后自评质量，不满足则触发重新检索
  4. Multi-hop Reasoning: 链式检索 (结果A → 新查询B → 结果C)

技术参考:
  - Self-RAG (Asai et al., 2024): 检索→评估→决定是否重新检索
  - CRAG (Corrective RAG, 2024): 检索后纠正错误
  - Adaptive RAG (2024): 根据查询复杂度自适应选择检索策略
"""
import json
import re
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from common.api_clients import get_deepseek_model
from json_repair import repair_json

logger = logging.getLogger(__name__)


@dataclass
class QueryRewrite:
    """查询改写结果"""
    original: str
    rewritten: str
    strategy: str  # expand / compress / decompose / none
    reason: str


@dataclass
class SelfRAGResult:
    """Self-RAG 评估结果"""
    retrieved_docs: List[Dict]
    is_sufficient: bool
    confidence: float
    needs_re_retrieval: bool
    re_retrieval_query: Optional[str] = None
    reason: str = ""


class QueryRewriter:
    """
    查询改写器

    策略:
    - expand: 添加同义词和相关概念扩展查询
    - compress: 去除噪音词，保留核心语义
    - decompose: 将复杂查询拆分为多个子查询
    - denoise: 对抗文本归一化 (火星文/拆字/谐音 → 规范中文)
    - none: 保持原查询
    """

    # 对抗文本归一化映射 (火星文/拆字/谐音 → 规范中文)
    ADVERSARIAL_NORMALIZE = {
        # 火星文 → 规范
        "嶶": "微", "亻": "人", "亻言": "信", "釒": "金", "貝": "贝",
        "専": "专", "業": "业", "務": "务", "電": "电", "話": "话",
        "聯": "联", "係": "系", "報": "报", "價": "价", "單": "单",
        "號": "号", "碼": "码", "賬": "账", "寶": "宝", "紅": "红",
        "掃": "扫", "碼": "码", "進": "进", "羣": "群", "領": "领",
        "優": "优", "惠": "惠", "獎": "奖", "勵": "励", "驗": "验",
        "證": "证", "視": "视", "頻": "频", "約": "约", "軟": "软",
        "體": "体", "護": "护", "膚": "肤", "療": "疗", "藥": "药",
        "發": "发", "財": "财", "賺": "赚", "錢": "钱", "幣": "币",
        "資": "资", "險": "险", "購": "购", "買": "买", "賣": "卖",
        "優": "优", "勢": "势", "廣": "广", "告": "告", "營": "营",
        "銷": "销", "課": "课", "程": "程", "職": "职", "業": "业",
        # 拆字/谐音
        "弓虽": "强", "女干": "奸", "扌丁": "打", "亻尔": "你",
        "氵殳": "没", "火暴": "爆", "讠平": "评", "口马": "骂",
        "衤皮": "被", "衤申": "神", "车欠": "软", "亻介": "价",
        "女且": "姐", "女未": "妹", "扌安": "按", "扌莫": "摩",
        "钅戋": "钱", "彳艮": "很", "石马": "码", "丿不": "还",
        "氵殳": "没", "讠上": "让", "衤果": "裸", "衤尞": "聊",
        # 同音替换
        "威信": "微信", "韦礼": "为利", "威少": "微小",
        "宏包": "红包", "富力": "福利", "兼貝只": "兼职",
        "果聊": "裸聊", "視频": "视频", "扫馬": "扫码",
        "進裙": "进群", "領取": "领取", "帳号": "账号",
    }

    # 预定义扩展词典 (违规审核领域)
    EXPANSION_DICT = {
        "广告": ["推广", "营销", "引流", "宣传", "销售", "加微信", "二维码"],
        "色情": ["低俗", "裸露", "色诱", "成人", "私密", "裸聊", "陪睡"],
        "暴力": ["威胁", "恐吓", "打架", "砍人", "杀人", "武器", "殴打"],
        "诈骗": ["中奖", "转账", "冒充", "钓鱼", "欺骗", "套取", "骗钱"],
        "政治": ["敏感", "反动", "分裂", "颠覆", "煽动", "造谣"],
        "赌博": ["赌场", "博彩", "押注", "下注", "赌钱", "彩票"],
        "违禁": ["毒品", "枪支", "管制", "走私", "非法"],
        "辱骂": ["骂人", "侮辱", "人身攻击", "诽谤", "造谣", "恶搞"],
    }

    def __init__(self):
        self._llm_client = None

    def set_llm_client(self, client):
        """设置 LLM 客户端用于高级查询改写"""
        self._llm_client = client

    def normalize_adversarial(self, text: str) -> str:
        """对抗文本归一化: 火星文/拆字/谐音 → 规范中文"""
        result = text
        for adv, normal in self.ADVERSARIAL_NORMALIZE.items():
            if adv in result:
                result = result.replace(adv, normal)
        return result

    def rewrite(self, query: str, strategy: str = "expand") -> QueryRewrite:
        """
        改写查询

        Args:
            query: 原始查询
            strategy: 改写策略

        Returns:
            改写后的查询
        """
        # v3.6: 先执行对抗文本归一化
        normalized = self.normalize_adversarial(query)

        if strategy == "expand":
            return self._expand_query(normalized)
        elif strategy == "compress":
            return self._compress_query(normalized)
        elif strategy == "decompose":
            return self._decompose_query(normalized)
        else:
            return QueryRewrite(
                original=query, rewritten=normalized,
                strategy="denoise" if normalized != query else "none",
                reason="对抗文本归一化" if normalized != query else "保持原查询",
            )

    async def rewrite_with_llm(self, query: str) -> QueryRewrite:
        """使用 LLM 进行智能查询改写"""
        if not self._llm_client:
            return self.rewrite(query, "expand")

        prompt = f"""你是查询优化专家。请改写以下内容安全审核的检索查询，提高检索召回率。

原始查询: {query}

改写规则:
1. 添加同义词和相关概念
2. 展开缩写和变体词
3. 保持核心违规意图不变
4. 生成 1-3 个改写变体

请以JSON格式返回:
{{"rewritten_queries": ["改写1", "改写2"], "strategy": "llm_expand", "reason": "基于语义扩展"}}
"""
        try:
            response = await self._llm_client.chat.completions.create(
                model=get_deepseek_model(),
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=300,
            )
            raw_content = response.choices[0].message.content
            result = self._safe_parse_json(raw_content)
            # 防御: _safe_parse_json 理论上保证返回 dict，但 LLM 输出不可控
            if not isinstance(result, dict):
                logger.warning(f"LLM rewrite returned non-dict: {type(result)}")
                return self.rewrite(query, "expand")
            expanded = result.get("rewritten_queries", [query])
            # 确保 expanded 是 list
            if isinstance(expanded, str):
                expanded = [expanded]
            # 合并所有改写查询
            combined = " | ".join([query] + expanded)
            return QueryRewrite(
                original=query, rewritten=combined,
                strategy="llm_expand",
                reason=result.get("reason", "LLM语义扩展"),
            )
        except Exception as e:
            logger.warning(f"LLM query rewrite failed: {e}")
            return self.rewrite(query, "expand")

    def _safe_parse_json(self, text: str) -> dict:
        """安全解析 LLM 返回的 JSON (json_repair + 三级回退)，保证始终返回 dict"""
        text = text.strip()

        def _ensure_dict(parsed) -> dict:
            """确保返回值是 dict — 如果 LLM 返回了数组，包装成 dict"""
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                logger.debug(f"LLM returned JSON array, wrapping as dict: {str(parsed)[:100]}")
                return {"rewritten_queries": parsed, "strategy": "llm_expand", "reason": "LLM返回数组"}
            return {}

        # 1. 去除 markdown 代码块包裹
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*\n?", "", text)
            text = re.sub(r"\n?```\s*$", "", text)
        # 2. 使用 json_repair 自动修复
        try:
            repaired = repair_json(text)
            return _ensure_dict(json.loads(repaired))
        except Exception:
            pass
        # 3. 尝试直接解析
        try:
            return _ensure_dict(json.loads(text))
        except json.JSONDecodeError:
            pass
        # 4. 尝试提取 JSON 对象/数组（从第一个 { 或 [ 到最后一个 } 或 ]）
        match = re.search(r"[\{\[].*[\}\]]", text, re.DOTALL)
        if match:
            try:
                repaired = repair_json(match.group(0))
                return _ensure_dict(json.loads(repaired))
            except Exception:
                pass
        # 5. 都失败则返回空 dict
        logger.warning(f"Could not parse JSON from LLM response: {text[:200]}")
        return {}

    def _expand_query(self, query: str) -> QueryRewrite:
        """基于词典扩展查询"""
        expanded_terms = []
        for keyword, expansions in self.EXPANSION_DICT.items():
            if keyword in query:
                expanded_terms.extend(expansions[:3])  # 每个关键词添加最多3个扩展

        if expanded_terms:
            rewritten = f"{query} {' '.join(expanded_terms)}"
            return QueryRewrite(
                original=query, rewritten=rewritten,
                strategy="expand",
                reason=f"词典扩展: {expanded_terms[:5]}",
            )
        return QueryRewrite(
            original=query, rewritten=query,
            strategy="none", reason="无匹配扩展词",
        )

    def _compress_query(self, query: str) -> QueryRewrite:
        """压缩查询: 去停用词 + 保留核心"""
        # 简单去停用词
        stopwords = {"的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
                     "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
                     "自己", "这", "他", "她", "它", "们", "那", "些", "什么", "怎么"}
        tokens = [t for t in query if t not in stopwords]
        compressed = "".join(tokens)
        return QueryRewrite(
            original=query, rewritten=compressed if compressed else query,
            strategy="compress",
            reason=f"去停用词: {len(query)-len(compressed)} 字符",
        )

    def _decompose_query(self, query: str) -> QueryRewrite:
        """拆分子查询 (长文本场景)"""
        # 按句子分割
        sentences = query.replace("。", "|").replace("！", "|").replace("？", "|").split("|")
        sentences = [s.strip() for s in sentences if len(s.strip()) > 3]

        if len(sentences) > 1:
            # 返回所有子查询，用特殊分隔符连接
            rewritten = " || ".join(sentences[:5])
            return QueryRewrite(
                original=query, rewritten=rewritten,
                strategy="decompose",
                reason=f"拆分为 {len(sentences[:5])} 个子查询",
            )
        return QueryRewrite(
            original=query, rewritten=query,
            strategy="none", reason="无需拆分",
        )


class SelfRAGEvaluator:
    """
    Self-RAG 自评估器

    评估检索结果是否满足需求:
    1. 相关性: 检索结果与查询的语义匹配度
    2. 充分性: 检索结果是否覆盖了查询的所有方面
    3. 置信度: 整体检索质量的信心水平

    不满足时触发:
    - 查询改写 → 重新检索
    - 切换检索策略 (BM25 ↔ Vector ↔ Hybrid)
    - 扩大 top_k
    """

    RELEVANCE_THRESHOLD = 0.3  # 相关性阈值
    SUFFICIENCY_THRESHOLD = 0.5  # 充分性阈值

    def evaluate(
        self, query: str, results: List[Dict], top_k: int,
    ) -> SelfRAGResult:
        """
        评估检索结果质量

        Returns:
            SelfRAGResult 包含评估结论和必要的重检索建议
        """
        if not results:
            return SelfRAGResult(
                retrieved_docs=[],
                is_sufficient=False,
                confidence=0.0,
                needs_re_retrieval=True,
                re_retrieval_query=query,  # 先用原查询重试
                reason="无检索结果，需扩大检索范围",
            )

        # 1. 计算平均相似度
        avg_similarity = sum(
            r.get("similarity", r.get("score", 0.0)) for r in results
        ) / max(len(results), 1)

        # 2. 检查是否有高相关结果
        high_relevance = [
            r for r in results
            if r.get("similarity", r.get("score", 0.0)) > self.RELEVANCE_THRESHOLD
        ]

        # 3. 检查结果多样性 (简单去重)
        unique_contents = set()
        for r in results:
            content = r.get("content", "")
            if content:
                # 取前50字符作为去重键
                unique_contents.add(content[:50])

        diversity = len(unique_contents) / max(len(results), 1)

        # 4. 综合判断
        is_sufficient = (
            len(high_relevance) >= min(2, top_k // 2)
            and avg_similarity > self.SUFFICIENCY_THRESHOLD
            and diversity > 0.3
        )

        confidence = min(
            avg_similarity / 0.8,
            len(high_relevance) / max(top_k, 1),
            diversity,
        )
        confidence = max(0.0, min(1.0, confidence))

        needs_re_retrieval = not is_sufficient

        # 生成重检索建议
        re_query = None
        if needs_re_retrieval:
            if avg_similarity < 0.2:
                re_query = query  # 保持原查询，可能是 embedding 不匹配
                reason = f"平均相似度 {avg_similarity:.2f} 过低，建议切换检索策略"
            elif diversity < 0.3:
                reason = f"结果多样性不足 ({diversity:.2f})，建议混合检索"
                re_query = query
            else:
                reason = f"高相关结果不足 ({len(high_relevance)}/{top_k})"
                re_query = query
        else:
            reason = f"检索充分: 相似度={avg_similarity:.2f}, 高相关={len(high_relevance)}, 多样性={diversity:.2f}"

        return SelfRAGResult(
            retrieved_docs=results,
            is_sufficient=is_sufficient,
            confidence=confidence,
            needs_re_retrieval=needs_re_retrieval,
            re_retrieval_query=re_query,
            reason=reason,
        )


class RetrievalRouter:
    """
    检索路由器

    根据查询特征选择最优检索策略:
    - 短查询 (<10 字符): BM25 优先 (精确匹配)
    - 长查询 (>50 字符): Vector 优先 (语义匹配)
    - 混合查询: Hybrid
    - 违规类型查询: GraphRAG 增强
    """

    @staticmethod
    def route(query: str, violation_types: List[str] = None) -> Dict:
        """
        路由到最优检索策略

        Returns:
            {
                "use_bm25": bool,
                "use_vector": bool,
                "use_graph": bool,
                "bm25_weight": float,  # BM25 融合权重
                "vector_weight": float,  # Vector 融合权重
                "strategy": str,  # 策略名称
                "reason": str,
            }
        """
        query_len = len(query.strip())
        has_violation_types = bool(violation_types)

        # 超短查询: BM25 主导
        if query_len < 10:
            return {
                "use_bm25": True, "use_vector": True, "use_graph": has_violation_types,
                "bm25_weight": 0.7, "vector_weight": 0.3,
                "strategy": "bm25_dominant",
                "reason": f"短查询({query_len}字符) → BM25 优先",
            }

        # 长查询: Vector 主导
        elif query_len > 100:
            return {
                "use_bm25": True, "use_vector": True, "use_graph": has_violation_types,
                "bm25_weight": 0.3, "vector_weight": 0.7,
                "strategy": "vector_dominant",
                "reason": f"长查询({query_len}字符) → 语义优先",
            }

        # 中等长度: 平衡混合
        else:
            return {
                "use_bm25": True, "use_vector": True, "use_graph": has_violation_types,
                "bm25_weight": 0.5, "vector_weight": 0.5,
                "strategy": "balanced_hybrid",
                "reason": f"中等查询({query_len}字符) → 混合检索",
            }


class AgenticRAG:
    """
    Agentic RAG 主控类

    完整检索决策循环:
    1. Query Rewriter: 改写查询
    2. Retrieval Router: 选择策略
    3. HybridRetriever: 混合检索
    4. Self-RAG Evaluator: 自评质量
    5. 如果不满足 → 回到步骤 1 (最多 3 轮)
    """

    MAX_ROUNDS = 3

    def __init__(self, hybrid_retriever, graph_rag_service=None):
        self.hybrid_retriever = hybrid_retriever
        self.graph_rag = graph_rag_service
        self.query_rewriter = QueryRewriter()
        self.router = RetrievalRouter()
        self.evaluator = SelfRAGEvaluator()

    def set_llm_client(self, client):
        """设置 LLM 客户端"""
        self.query_rewriter.set_llm_client(client)

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        violation_types: List[str] = None,
        auto_refine: bool = True,
    ) -> Dict:
        """
        智能检索

        Args:
            query: 原始查询
            top_k: 返回结果数
            violation_types: 已知的违规类型 (用于 GraphRAG 增强)
            auto_refine: 是否自动优化查询和重新检索

        Returns:
            {
                "results": List[RetrievalResult],
                "rounds": int,  # 检索轮次
                "self_rag": SelfRAGResult,
                "query_rewrite": QueryRewrite,
                "routing": Dict,
            }
        """
        round_results = []
        current_query = query
        final_eval = None
        final_rewrite = None
        final_routing = None

        for round_idx in range(self.MAX_ROUNDS):
            # Step 1: 路由决策
            routing = self.router.route(current_query, violation_types)

            # Step 2: 查询改写 (优先 LLM 改写，回退到词典扩展)
            if round_idx == 0:
                # v3.1 增强: 首轮也优先使用 LLM 改写以获得更好的召回率
                if self.query_rewriter._llm_client:
                    rewrite = await self.query_rewriter.rewrite_with_llm(current_query)
                else:
                    rewrite = self.query_rewriter.rewrite(current_query, "expand")
            else:
                rewrite = await self.query_rewriter.rewrite_with_llm(current_query)

            search_query = rewrite.rewritten

            # Step 3: 混合检索
            results = await self.hybrid_retriever.search(
                query=search_query,
                top_k=top_k,
                use_bm25=routing["use_bm25"],
                use_vector=routing["use_vector"],
                use_rerank=True,
            )

            # Step 4: Self-RAG 评估
            results_dict = [
                {
                    "id": r.id, "content": r.content, "score": r.score,
                    "similarity": r.score, "source": r.source,
                }
                for r in results
            ]
            evaluation = self.evaluator.evaluate(search_query, results_dict, top_k)

            round_results.append({
                "round": round_idx + 1,
                "query": search_query,
                "results": results,
                "evaluation": evaluation,
            })

            final_eval = evaluation
            final_rewrite = rewrite
            final_routing = routing

            # 如果充分或已达到最大轮次，停止
            if evaluation.is_sufficient or not auto_refine:
                break

            # 否则准备下一轮检索
            current_query = evaluation.re_retrieval_query or query

        # Step 5: GraphRAG 增强 (如果有违规类型)
        graph_insights = None
        if self.graph_rag and violation_types:
            graph_insights = self.graph_rag.get_insights(violation_types)

        # 汇总最终结果
        final_results = round_results[-1]["results"] if round_results else []

        return {
            "results": final_results,
            "total_rounds": len(round_results),
            "round_details": round_results,
            "self_rag": {
                "is_sufficient": final_eval.is_sufficient if final_eval else False,
                "confidence": final_eval.confidence if final_eval else 0.0,
                "reason": final_eval.reason if final_eval else "",
            },
            "query_rewrite": {
                "original": query,
                "rewritten": final_rewrite.rewritten if final_rewrite else query,
                "strategy": final_rewrite.strategy if final_rewrite else "none",
            },
            "routing": final_routing,
            "graph_insights": graph_insights,
        }


# 全局单例
_agentic_rag: Optional[AgenticRAG] = None


def get_agentic_rag(hybrid_retriever=None, graph_rag=None) -> AgenticRAG:
    global _agentic_rag
    if _agentic_rag is None:
        _agentic_rag = AgenticRAG(hybrid_retriever, graph_rag)
    return _agentic_rag
