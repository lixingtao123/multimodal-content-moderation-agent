"""
Multi-Modal RAG v1.0 — 多模态检索增强生成

支持:
  1. 图片→文本描述 → 文本RAG
  2. 图片→向量 (CLIP风格) → 跨模态检索
  3. 多模态融合: 文本+视觉联合检索
  4. 与现有 HybridRetriever 无缝集成

技术参考:
  - Google Gemini RAG (2025): Multi-modal retrieval
  - CLIP (Radford et al., 2021): Contrastive Language-Image Pre-training
  - DenseAV (2024): Multi-modal fusion for retrieval
"""
import logging
import base64
from io import BytesIO
from typing import List, Dict, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MultiModalResult:
    """多模态检索结果"""
    id: str
    content: str           # 文本描述或OCR文字
    score: float           # 融合得分
    text_score: float = 0.0
    visual_score: float = 0.0
    modality: str = "text"  # text / image / fused
    metadata: Dict = field(default_factory=dict)


class MultiModalRAG:
    """
    多模态 RAG 检索器

    架构:
      文本查询 → [文本Retriever] ─┐
                                  ├→ RRF Fusion → 最终结果
      图片输入 → [视觉特征提取] ─┘

    当输入包含图片时:
      1. 提取 OCR 文字 → 文本 RAG
      2. 生成图片描述 → 文本 RAG (可选, 需要 VL API)
      3. 计算视觉特征 → 跨模态检索 (可选, 需要 CLIP)
    """

    def __init__(self, hybrid_retriever=None, chroma_service=None):
        self.hybrid_retriever = hybrid_retriever
        self.chroma = chroma_service
        self._clip_model = None
        self._clip_processor = None
        self._vl_client = None

    def set_vl_client(self, client):
        """设置 VL 客户端用于图片描述生成"""
        self._vl_client = client

    def _load_clip(self):
        """延迟加载 CLIP 模型。

        注意：CLIP 输出 512 维向量，而文本案例 collection（moderation_cases_v2）
        用 bge-m3 存 1024 维。CLIP 向量无法直接查询该 collection —— 若直接查询
        会反复抛 "expecting dimension 1024, got 512"。因此仅在 collection 维度
        与 CLIP 兼容时才启用视觉检索，否则诚实降级到文本 RAG（OCR 文本路径），
        避免每个图像审核都产生失败日志。
        """
        if self._clip_model is not None:
            return True
        # 维度预检：只有 1024 维文本 collection 时不启用 CLIP 视觉检索
        if self.chroma and self.chroma.collection:
            try:
                dim = self._collection_dim()
                if dim and dim != 512:
                    logger.info(
                        f"CLIP visual search disabled: collection dim={dim} != 512 "
                        "(bge-m3 文本向量 collection，视觉检索走 OCR 文本降级)")
                    return False
            except Exception:
                pass
        try:
            from transformers import CLIPProcessor, CLIPModel
            import torch
            model_name = "openai/clip-vit-base-patch32"
            self._clip_model = CLIPModel.from_pretrained(model_name)
            self._clip_processor = CLIPProcessor.from_pretrained(model_name)
            self._clip_model.eval()
            logger.info(f"CLIP model loaded: {model_name}")
            return True
        except ImportError:
            logger.warning("transformers not available, CLIP disabled")
            return False
        except Exception as e:
            logger.warning(f"CLIP model load failed: {e}")
            return False

    def _collection_dim(self):
        """探测文本案例 collection 的向量维度（用于 CLIP 兼容性判断）。"""
        try:
            ef = self.chroma.collection._embedding_function
            model = getattr(ef, "_model", None)
            if model is not None and hasattr(model, "get_sentence_embedding_dimension"):
                return model.get_sentence_embedding_dimension()
            # 回退：用一条空查询探测 collection 期望维度
            try:
                self.chroma.collection.query(query_texts=["维度探测"], n_results=1)
                return None
            except Exception as e:
                import re
                m = re.search(r"dimension of (\d+)", str(e))
                return int(m.group(1)) if m else None
        except Exception:
            return None

    async def retrieve_with_image(
        self,
        text_query: str,
        image_data: bytes = None,
        top_k: int = 5,
        use_visual: bool = True,
    ) -> List[MultiModalResult]:
        """
        文本+图片联合检索 (v3.6: CLIP 不可用时回退到文本 RAG)

        Args:
            text_query: 文本查询 (如OCR文字)
            image_data: 原始图片字节
            top_k: 返回结果数
            use_visual: 是否使用视觉特征
        """
        results = []

        # 1. 文本检索 (OCR 文本 → Hybrid RAG + 图片案例集合优先)
        if text_query and self.hybrid_retriever:
            try:
                # 优先检索图片案例 (modality=image 的案例)
                text_results = await self.hybrid_retriever.search(
                    query=text_query,
                    top_k=top_k,
                    use_bm25=True,
                    use_vector=True,
                    use_rerank=True,
                )
                for r in text_results:
                    results.append(MultiModalResult(
                        id=r.id, content=r.content[:200],
                        score=r.score, text_score=r.score,
                        visual_score=0.0, modality="text",
                        metadata=r.metadata if hasattr(r, 'metadata') else {},
                    ))
            except Exception as e:
                logger.warning(f"Text retrieval failed: {e}")

        # 2. 文本回退检索 (无 OCR 文本时用场景描述)
        if not text_query and self.hybrid_retriever:
            try:
                # 尝试用"违规图片"作为通用查询
                fallback_results = await self.hybrid_retriever.search(
                    query="违规内容 可疑图片 广告 色情 暴力",
                    top_k=top_k,
                    use_bm25=True,
                    use_vector=True,
                    use_rerank=False,
                )
                for r in fallback_results:
                    results.append(MultiModalResult(
                        id=r.id, content=r.content[:200],
                        score=r.score * 0.5, text_score=r.score * 0.5,
                        visual_score=0.0, modality="text_fallback",
                    ))
            except Exception as e:
                logger.warning(f"Text fallback retrieval failed: {e}")

        # 2. 视觉特征检索 (如果启用)
        if use_visual and image_data and self._load_clip():
            try:
                visual_results = await self._visual_search(image_data, top_k)
                # 融合文本和视觉结果
                results = self._fuse_results(results, visual_results)
            except Exception as e:
                logger.warning(f"Visual retrieval failed: {e}")

        # 按融合得分排序
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    async def _visual_search(self, image_data: bytes, top_k: int) -> List[MultiModalResult]:
        """基于视觉特征的检索"""
        # 从图片生成CLIP向量
        from PIL import Image
        import torch

        img = Image.open(BytesIO(image_data)).convert("RGB")
        inputs = self._clip_processor(images=img, return_tensors="pt")
        with torch.no_grad():
            image_features = self._clip_model.get_image_features(**inputs)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)

        # 转为列表用于检索
        query_vector = image_features.squeeze().tolist()

        # 在 ChromaDB 中搜索视觉相似案例
        visual_results = []
        if self.chroma and self.chroma.collection:
            try:
                chroma_results = self.chroma.collection.query(
                    query_embeddings=[query_vector],
                    n_results=min(top_k, 20),
                )
                for idx, (doc_id, doc_text, distance) in enumerate(zip(
                    chroma_results["ids"][0],
                    chroma_results["documents"][0],
                    chroma_results["distances"][0],
                )):
                    similarity = 1.0 - distance
                    visual_results.append(MultiModalResult(
                        id=doc_id, content=doc_text[:200],
                        score=similarity, text_score=0.0,
                        visual_score=similarity, modality="image",
                    ))
            except Exception as e:
                logger.warning(f"ChromaDB visual search failed: {e}")

        return visual_results

    def _fuse_results(
        self, text_results: List[MultiModalResult], visual_results: List[MultiModalResult]
    ) -> List[MultiModalResult]:
        """融合文本和视觉检索结果 (RRF)"""
        RRF_K = 60
        all_results = {}

        for rank, r in enumerate(text_results):
            rrf_score = 1.0 / (RRF_K + rank + 1)
            if r.id not in all_results:
                all_results[r.id] = r
                all_results[r.id].score = rrf_score
            else:
                all_results[r.id].score += rrf_score
                all_results[r.id].visual_score = r.visual_score
                all_results[r.id].modality = "fused"

        for rank, r in enumerate(visual_results):
            rrf_score = 1.0 / (RRF_K + rank + 1)
            if r.id not in all_results:
                all_results[r.id] = r
                all_results[r.id].score = rrf_score
            else:
                all_results[r.id].score += rrf_score
                all_results[r.id].text_score = r.text_score
                all_results[r.id].modality = "fused"

        return list(all_results.values())

    async def generate_image_description(self, image_data: bytes) -> Optional[str]:
        """
        使用 VL API 生成图片描述，用于增强文本检索
        """
        if not self._vl_client:
            return None
        try:
            import base64 as b64
            from PIL import Image
            img = Image.open(BytesIO(image_data))
            fmt = (img.format or "jpeg").lower()
            img_b64 = b64.b64encode(image_data).decode("utf-8")
            data_url = f"data:image/{fmt};base64,{img_b64}"

            response = await self._vl_client.chat.completions.create(
                model="qwen3.6-plus",
                messages=[
                    {"role": "system", "content": "用一句话描述图片内容，用于内容审核检索。关注：人物、场景、文字、可疑元素。"},
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": "请用中文一句话描述这个图片"},
                    ]},
                ],
                max_tokens=100,
                temperature=0.1,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"Image description generation failed: {e}")
            return None


# 全局单例
_multimodal_rag: Optional[MultiModalRAG] = None


def get_multimodal_rag(hybrid_retriever=None, chroma_service=None) -> MultiModalRAG:
    global _multimodal_rag
    if _multimodal_rag is None:
        from memory.chroma_service import get_chroma_service
        _multimodal_rag = MultiModalRAG(
            hybrid_retriever=hybrid_retriever,
            chroma_service=chroma_service or get_chroma_service(),
        )
    return _multimodal_rag
