"""
ChromaDB 向量数据库服务 — 历史违规案例检索 + 相似内容搜索
使用本地 bge-small-zh-v1.5 生成 Embedding
"""
import time
import logging
from typing import List, Dict, Optional
import chromadb
from chromadb.utils import embedding_functions
from common.config import get_settings

logger = logging.getLogger(__name__)


class ChromaService:
    """ChromaDB 向量检索服务"""

    # R19: 升级 v2 collection（1024 维 embedding 统一维度）。
    # 旧 512 维 collection 保留不删（模拟数据不清空），新写入/检索走 v2。
    COLLECTION_NAME = "moderation_cases_v2"
    CORE_COLLECTION_NAME = "core_memory_v2"

    def __init__(self):
        self.client: Optional[chromadb.HttpClient] = None
        self.collection = None
        self._core_collection = None
        self.embedding_fn = None

    async def connect(self):
        """连接到 ChromaDB 并初始化集合"""
        import os
        settings = get_settings()

        # R22·D2: 本地模式显式声明 CHROMA_PERSIST_DIR → 直连嵌入式 PersistentClient，
        # 不尝试 HTTP（避免连不存在的 18001）；Docker 模式不设此变量 → HTTP 模式。
        # 注意：只决定 client 来源，之后统一走 embedding/collection 初始化（不可提前 return）。
        persist_dir = os.environ.get("CHROMA_PERSIST_DIR")
        if persist_dir:
            self.client = chromadb.PersistentClient(path=persist_dir)
            logger.info(f"ChromaDB using PersistentClient (path={persist_dir})")
        else:
            # 优先尝试 HTTP 模式，失败则用内嵌 PersistentClient
            import re
            host_port = settings.chroma_url.replace("http://", "").replace("https://", "")
            if ":" in host_port:
                host, port = host_port.split(":")
            else:
                host, port = host_port, str(settings.chroma_port)

            try:
                self.client = chromadb.HttpClient(host=host, port=int(port))
                self.client.heartbeat()
                logger.info(f"ChromaDB connected via HTTP ({host}:{port})")
            except Exception:
                # 回退到内嵌模式
                self.client = chromadb.PersistentClient(path="/workspace/data/chroma")
                logger.info("ChromaDB using PersistentClient (path=/workspace/data/chroma)")

        # v3.6: 多级 Embedding 模型回退策略
        # bge-m3 (1024维, Matryoshka) → bge-large-zh-v1.5 (1024维) → bge-small-zh-v1.5 (384维)
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"

        import os as _os
        _model_path = None
        _model_name_display = ""
        # 从配置读取 embedding 模型名 (默认自动检测)
        try:
            _cfg_embed = getattr(get_settings(), "embedding_model", "")
        except Exception:
            _cfg_embed = ""

        _candidates = []
        if _cfg_embed:
            _candidates.append(_cfg_embed)
        # R19 修复：优先使用本地 HuggingFace hub 缓存的 bge-m3（1024 维），
        # 避免 "No model found" 时随机初始化导致维度漂移（512/1024 不稳定）
        import glob as _glob
        try:
            _hf_bge_m3 = _glob.glob("/root/.cache/huggingface/hub/models--BAAI--bge-m3/snapshots/*/")
            if _hf_bge_m3:
                _candidates.insert(0, _hf_bge_m3[0])
        except Exception:
            pass
        # 按优先级: bge-m3(1024d) → bge-large-zh-v1.5(1024d) → bge-small-zh-v1.5(384d)
        _candidates += [
            "/root/.cache/modelscope/BAAI/bge-m3",
            "BAAI/bge-m3",
            "/root/.cache/modelscope/BAAI/bge-large-zh-v1___5",
            "BAAI/bge-large-zh-v1.5",
            "/root/.cache/modelscope/BAAI/bge-small-zh-v1___5",
            "BAAI/bge-small-zh-v1.5",
        ]
        for _cand in _candidates:
            try:
                self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name=_cand,
                    device=device,
                )
                _model_path = _cand
                _model_name_display = _cand.split("/")[-1]
                break
            except Exception as _e:
                logger.warning(f"embedding candidate failed: {_cand[:80]} -> {str(_e)[:200]}")
                continue

        if _model_path:
            logger.info(f"{_model_name_display} embedding loaded on {device} (path={_model_path})")
        else:
            # 最终兜底
            self.embedding_fn = embedding_functions.DefaultEmbeddingFunction()
            logger.warning("bge-small-zh-v1.5 unavailable, using ChromaDB default embedding")

        # 获取或创建集合
        self.collection = self.client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            embedding_function=self.embedding_fn,
            metadata={"description": "内容审核历史案例库"},
        )
        logger.info(f"ChromaDB collection '{self.COLLECTION_NAME}' ready")

        # 核心记忆 collection (高重要性案例长期保留)
        self._core_collection = self.client.get_or_create_collection(
            name=self.CORE_COLLECTION_NAME,
            embedding_function=self.embedding_fn,
            metadata={"description": "高重要性审核案例核心记忆"},
        )
        logger.info(f"ChromaDB collection '{self.CORE_COLLECTION_NAME}' ready")

    async def add_case(self, case_id: str, content: str, violation_type: str, decision: str,
                      modality: str = "text", ocr_text: str = "", scene_description: str = ""):
        """添加审核案例到向量库 (v3.6: 支持多模态 metadata)"""
        meta = {
            "violation_type": violation_type,
            "decision": decision,
            "timestamp": time.time(),
            "modality": modality,
        }
        if ocr_text:
            meta["ocr_text"] = ocr_text[:500]
        if scene_description:
            meta["scene_description"] = scene_description[:500]
        self.collection.add(
            ids=[case_id],
            documents=[content],
            metadatas=[meta],
        )

    async def add_image_case(self, case_id: str, ocr_text: str, scene_description: str,
                             violation_type: str, decision: str, risk_score: float = 0.5):
        """添加图片审核案例 (v3.6: 模拟 VL 提取结果)"""
        # 拼接 OCR + 场景描述作为可检索内容
        document = f"[图片OCR] {ocr_text[:300]}\n[场景] {scene_description[:300]}"
        self.collection.add(
            ids=[case_id],
            documents=[document],
            metadatas=[{
                "violation_type": violation_type,
                "decision": decision,
                "modality": "image",
                "ocr_text": ocr_text[:500],
                "scene_description": scene_description[:500],
                "risk_score": risk_score,
                "timestamp": time.time(),
                "source": "seed_data",
            }],
        )

    async def add_core_case(self, case_id: str, content: str, violation_type: str,
                            decision: str, importance: float):
        """添加高重要性案例到核心记忆 collection"""
        if self._core_collection:
            self._core_collection.add(
                ids=[case_id],
                documents=[content],
                metadatas=[{
                    "violation_type": violation_type,
                    "decision": decision,
                    "importance": importance,
                    "timestamp": time.time(),
                }],
            )

    async def add_cases_batch(self, cases: List[Dict]):
        """批量添加案例
        cases: [{"id": ..., "content": ..., "violation_type": ..., "decision": ...}]
        """
        if not cases:
            return
        self.collection.add(
            ids=[c["id"] for c in cases],
            documents=[c["content"] for c in cases],
            metadatas=[{
                "violation_type": c.get("violation_type", "unknown"),
                "decision": c.get("decision", "UNKNOWN"),
                "timestamp": time.time(),
            } for c in cases],
        )

    async def search_similar(self, query: str, top_k: int = 5) -> List[Dict]:
        """检索相似历史案例"""
        results = self.collection.query(
            query_texts=[query],
            n_results=top_k,
        )

        cases = []
        if results["ids"] and results["ids"][0]:
            for i in range(len(results["ids"][0])):
                distance = results["distances"][0][i] if results["distances"] else 0
                meta = results["metadatas"][0][i] or {}
                cases.append({
                    "id": results["ids"][0][i],
                    "content": results["documents"][0][i] if results["documents"] else "",
                    "violation_type": meta.get("violation_type", ""),
                    "decision": meta.get("decision", ""),
                    "similarity": 1.0 - distance,  # distance → similarity
                    # R19 修复：完整透传 metadata（source/source_dataset/timestamp/
                    # no_decay/ground_truth），供来源加权与 no_decay 生效
                    "metadata": meta,
                })

        return cases

    async def delete_case(self, case_id: str):
        """删除案例"""
        self.collection.delete(ids=[case_id])

    async def count(self) -> int:
        """集合中的案例数"""
        return self.collection.count()


# 全局单例
_chroma_service: Optional[ChromaService] = None


def get_chroma_service() -> ChromaService:
    global _chroma_service
    if _chroma_service is None:
        _chroma_service = ChromaService()
    return _chroma_service
