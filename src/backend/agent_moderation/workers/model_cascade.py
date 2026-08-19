"""
模型级联路由（R16·M1）— 小模型优先，大模型兜底

原则：便宜的先上，贵的兜底。
- 小模型（本地/量化，可训练替换）：先判，输出 {decision, confidence}
- confidence < 升级阈值 或 明确 needs_upgrade → 升级大模型（DeepSeek）
- 升级阈值由 ECE 校准曲线决定（现状用可配置默认，校准接入 T1 后）

模型客户端是**接口**（async judge(text) -> dict），可注入/替换——按可训练设计（R1 后小模型换微调版，接口不变）。
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_UPGRADE_THRESHOLD = 0.6  # ECE 校准前默认；接入 T1 校准曲线后动态


class CascadeRouter:
    """级联路由：小模型优先，低置信度升级大模型"""

    def __init__(self, small_client=None, large_client=None,
                 upgrade_threshold: float = DEFAULT_UPGRADE_THRESHOLD):
        self.small = small_client
        self.large = large_client
        self.upgrade_threshold = upgrade_threshold
        self._stats = {"small": 0, "upgraded": 0, "large_only": 0}

    async def route(self, text: str) -> dict:
        """级联判定。返回含 used_small / upgraded / decision / confidence。"""
        if self.small is None:
            # 无小模型 → 直接大模型
            self._stats["large_only"] += 1
            return await self._use_large(text, reason="无小模型")

        try:
            small_result = await self.small(text)
        except Exception as e:
            logger.warning(f"[cascade] 小模型异常，升级大模型: {e}")
            self._stats["upgraded"] += 1
            return await self._use_large(text, reason=f"小模型异常: {e}")

        conf = float(small_result.get("confidence", 0.0))
        needs_upgrade = bool(small_result.get("needs_upgrade", False)) or conf < self.upgrade_threshold

        if needs_upgrade:
            self._stats["upgraded"] += 1
            large_result = await self._use_large(text, reason=f"小模型低置信度({conf:.2f})")
            large_result["small_confidence"] = conf
            return large_result

        self._stats["small"] += 1
        small_result["used_small"] = True
        small_result["upgraded"] = False
        return small_result

    async def _use_large(self, text: str, reason: str = "") -> dict:
        if self.large is None:
            return {"decision": "UNKNOWN", "confidence": 0.0, "upgraded": False,
                    "error": "无大模型", "reason": reason}
        result = await self.large(text)
        result["used_small"] = False
        result["upgraded"] = True
        result["reason"] = reason
        return result

    def stats(self) -> dict:
        return dict(self._stats)
