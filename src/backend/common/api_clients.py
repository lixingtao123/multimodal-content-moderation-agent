"""
API 客户端工厂函数 — 统一管理 DeepSeek 和 Qwen3-VL 的 OpenAI 兼容客户端
所有 Agent 通过此模块获取 API 客户端，方便切换供应商

模型配置统一从 config.Settings 读取，支持环境变量覆盖
"""
import os
from openai import AsyncOpenAI
from .config import get_settings


def get_deepseek_model() -> str:
    """获取当前使用的 DeepSeek 模型名称"""
    return get_settings().deepseek_model


def get_deepseek_client() -> AsyncOpenAI:
    """获取 DeepSeek API 客户端 — 用于文本理解和 Agent 推理
    模型：deepseek-v4-flash (284B/13B, 1M context, 快速+经济)
    """
    settings = get_settings()
    api_key = settings.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY", "sk-placeholder")
    return AsyncOpenAI(
        api_key=api_key,
        base_url=settings.deepseek_base_url,
    )


def get_vl_model_client() -> AsyncOpenAI:
    """获取 Qwen3-VL 多模态 API 客户端 — 用于图像/视频帧审核 + OCR
    模型：qwen3-vl-plus（阿里云 PAI-MaaS，OpenAI 兼容格式）
    端点：https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
    """
    settings = get_settings()
    api_key = settings.qwen_vl_api_key or os.environ.get("QWEN_VL_API_KEY", "sk-placeholder")
    return AsyncOpenAI(
        api_key=api_key,
        base_url=settings.qwen_vl_base_url,
    )
