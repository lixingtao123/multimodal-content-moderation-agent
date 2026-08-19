"""
FunASR 语音转文本 HTTP 客户端 — 调用 FunASR 服务
"""
import logging
from typing import Optional

import httpx
from common.config import get_settings

logger = logging.getLogger(__name__)


class FunASRClient:
    """FunASR STT 客户端"""

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.funasr_url.rstrip("/")
        self._available: Optional[bool] = None
        self._last_health_check: float = 0.0

    async def health(self, force: bool = False) -> bool:
        """检查 FunASR 服务可用性（缓存 30s，避免每次都 HTTP 探测；失败后 5s 重试）"""
        import time as _time
        now = _time.time()
        # 成功缓存 30s，失败只缓存 5s（允许服务恢复后快速重连）
        cache_ttl = 30.0 if self._available else 5.0
        if not force and self._available is not None and (now - self._last_health_check) < cache_ttl:
            return self._available
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.base_url}/health", timeout=5.0)
                self._available = resp.status_code == 200
                self._last_health_check = now
                return self._available
        except Exception:
            self._available = False
            self._last_health_check = now
            return False

    async def transcribe(self, audio_bytes: bytes, filename: str = "audio.wav") -> dict:
        """语音转文本，返回 {'text': str, 'success': bool, 'error': str|None}"""
        if not await self.health():
            return {"text": "", "success": False, "error": "FunASR service unavailable"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                files = {"file": (filename, audio_bytes, "audio/wav")}
                resp = await client.post(f"{self.base_url}/transcribe", files=files)
                resp.raise_for_status()
                data = resp.json()
                text = data.get("text", "")
                logger.info(f"FunASR transcription: '{text[:100]}...' ({len(text)} chars)")
                return {"text": text, "success": True, "error": None}
        except httpx.HTTPError as e:
            logger.error(f"FunASR HTTP error: {e}")
            return {"text": "", "success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"FunASR unexpected error: {e}")
            return {"text": "", "success": False, "error": str(e)}


# 全局单例
_funasr_client: FunASRClient = None


def get_funasr_client() -> FunASRClient:
    global _funasr_client
    if _funasr_client is None:
        _funasr_client = FunASRClient()
    return _funasr_client
