"""
图片哈希工具 — 基于 dHash（差异哈希）检测相似/重复图片
用于识别同图不同尺寸、轻微修改、裁剪等对抗手段
"""
import logging
from typing import List, Dict, Optional
from pydantic import BaseModel
from io import BytesIO

logger = logging.getLogger(__name__)


class ImageHashResult(BaseModel):
    hash_hex: str
    is_duplicate: bool = False
    similar_images: List[Dict] = []
    similarity: float = 0.0


class ImageHashTool:
    """图片 dHash 工具 — 相似图片检测"""

    name = "image_hash"
    description = "基于 dHash 检测相似/重复图片（对抗图片修改）"

    def __init__(self):
        self._hash_store: Dict[str, dict] = {}  # memory cache: hash → info

    def compute_dhash(self, image_data: bytes, hash_size: int = 8) -> str:
        """
        计算图片的 dHash（差异哈希）
        dHash 对图片的缩放、亮度调整不敏感
        """
        try:
            from PIL import Image
            img = Image.open(BytesIO(image_data))
            img = img.convert("L")  # 灰度
            img = img.resize((hash_size + 1, hash_size), Image.LANCZOS)

            pixels = list(img.getdata())
            hash_bits = []
            for row in range(hash_size):
                for col in range(hash_size):
                    left = pixels[row * (hash_size + 1) + col]
                    right = pixels[row * (hash_size + 1) + col + 1]
                    hash_bits.append("1" if left > right else "0")

            # 转十六进制
            hash_int = int("".join(hash_bits), 2)
            return format(hash_int, "x").zfill(hash_size * 2)

        except ImportError:
            logger.warning("PIL not available for image hash")
            return ""
        except Exception as e:
            logger.error(f"dHash computation failed: {e}")
            return ""

    @staticmethod
    def hamming_distance(hash1: str, hash2: str) -> int:
        """计算两个 dHash 的汉明距离"""
        if len(hash1) != len(hash2):
            return 999
        try:
            int1 = int(hash1, 16)
            int2 = int(hash2, 16)
            return bin(int1 ^ int2).count("1")
        except ValueError:
            return 999

    async def execute(self, image_data: bytes, threshold: int = 10) -> ImageHashResult:
        """
        计算图片 dHash 并检查相似图片
        threshold: 汉明距离阈值，≤此值判定为相似（默认10）
        """
        current_hash = self.compute_dhash(image_data)

        if not current_hash:
            return ImageHashResult(hash_hex="", is_duplicate=False, similar_images=[])

        # 与已存储的图片比较
        similar = []
        for stored_hash, info in self._hash_store.items():
            distance = self.hamming_distance(current_hash, stored_hash)
            if distance <= threshold:
                similarity = 1.0 - (distance / 64.0)  # max distance for 64-bit hash
                similar.append({
                    "content_id": info.get("content_id", ""),
                    "hash": stored_hash,
                    "hamming_distance": distance,
                    "similarity": round(max(similarity, 0), 4),
                })

        return ImageHashResult(
            hash_hex=current_hash,
            is_duplicate=len(similar) > 0 and any(s["similarity"] > 0.9 for s in similar),
            similar_images=sorted(similar, key=lambda x: x["similarity"], reverse=True)[:5],
            similarity=max((s["similarity"] for s in similar), default=0.0),
        )

    def store_hash(self, content_id: str, image_data: bytes):
        """存储图片 hash 用于后续比对"""
        hash_hex = self.compute_dhash(image_data)
        if hash_hex:
            self._hash_store[hash_hex] = {
                "content_id": content_id,
                "size": len(image_data),
            }

    def clear_store(self):
        """清空 hash 存储"""
        self._hash_store.clear()
