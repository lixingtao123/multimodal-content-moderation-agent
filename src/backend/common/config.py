"""
应用配置 — 通过 pydantic-settings 加载环境变量
"""
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # ========== API Keys ==========
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"  # flash 模型: 284B/13B, 1M ctx, 快速+经济

    qwen_vl_api_key: str = ""
    qwen_vl_base_url: str = "https://ws-66r3o2tog5uege0b.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    qwen_vl_model: str = "qwen3.6-plus"

    # ========== Database ==========
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:15432/moderation"
    database_url_sync: str = "postgresql://postgres:postgres@localhost:15432/moderation"

    # ========== Redis ==========
    redis_url: str = "redis://localhost:16379/0"

    # ========== ChromaDB ==========
    chroma_url: str = "http://localhost:18001"
    embedding_model: str = ""  # 空=自动检测 (bge-m3 → bge-large → bge-small)

    # ========== Ollama (快车道本地小模型) ==========
    # R20: qwen_judge 的 base_url/model 改为配置驱动（此前硬编码在代码里）
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    # ========== FunASR ==========
    funasr_url: str = "http://localhost:15001"

    # ========== 3D-Speaker (说话人识别) ==========
    speaker_diarization_enabled: bool = True
    speaker_diarization_model: str = "iic/speech_campplus_sv_zh-cn_3dspeaker_16k"
    speaker_diarization_fallback: str = "iic/speech_campplus_speaker-diarization_common"

    # ========== 信号卡压缩 ==========
    signal_card_compression_enabled: bool = True
    signal_card_chunk_threshold: int = 15000   # 超过此字符数走信号卡压缩路径
    signal_card_long_threshold: int = 80000    # 超过此字符数启用 Scout 预扫

    # ========== Mock 模式 ==========
    # R22: 默认关闭 mock（真实 VL API）。仅显式设置 IMAGE_AGENT_MOCK=true 时才启用 mock。
    image_agent_mock: bool = False

    # ========== App ==========
    log_level: str = "INFO"
    environment: str = "development"

    # ========== 端口（可被同名环境变量覆盖，如 BACKEND_PORT=18080） ==========
    # 默认值已选择高位端口，降低与常见服务冲突的概率（规则: 原端口前加前缀 1）
    backend_port: int = 18080
    frontend_port: int = 13000
    funasr_port: int = 15001
    pg_port: int = 15432
    redis_port: int = 16379
    chroma_port: int = 18001

    # ========== CORS ==========
    cors_origins: list[str] = ["http://localhost:13000"]

    @model_validator(mode="after")
    def _sync_frontend_cors(self) -> "Settings":
        """前端端口变化时，CORS 白名单自动跟上（防止只改 FRONTEND_PORT 忘改 CORS）。"""
        origin = f"http://localhost:{self.frontend_port}"
        if origin not in self.cors_origins:
            self.cors_origins = [*self.cors_origins, origin]
        return self


@lru_cache()
def get_settings() -> Settings:
    return Settings()
