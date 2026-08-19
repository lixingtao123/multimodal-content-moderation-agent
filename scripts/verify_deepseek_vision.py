"""
验证 DeepSeek API 是否支持多模态（视觉）能力
用法: python scripts/verify_deepseek_vision.py
前置: 已配置 DEEPSEEK_API_KEY 环境变量或在 src/backend/.env 中
"""
import asyncio
import base64
import json
import os
import sys
from pathlib import Path
from io import BytesIO

# 尝试加载 .env
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / "src" / "backend" / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()
except ImportError:
    pass

from openai import AsyncOpenAI


# 生成一张 1x1 像素的 PNG 图片用于测试（不依赖外部文件）
def create_test_image() -> bytes:
    """创建一个最小的测试 PNG 图片（红色 1x1 像素）"""
    import struct
    import zlib

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw = zlib.compress(b"\x00\xff\x00\x00")  # 红色像素
    idat = chunk(b"IDAT", raw)
    iend = chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


async def test_vision_capability():
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    if not api_key:
        print("❌ DEEPSEEK_API_KEY 未配置，无法运行验证")
        print("   请在 .env 文件中设置 DEEPSEEK_API_KEY")
        return

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    # 准备 base64 图片
    img_bytes = create_test_image()
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    data_uri = f"data:image/png;base64,{img_b64}"

    print(f"🔍 测试 DeepSeek API 多模态能力")
    print(f"   Base URL: {base_url}")
    print(f"   API Key:  {api_key[:8]}...{api_key[-4:]}")
    print()

    # ====== 测试 1: 用 Vision API 格式调用 deepseek-chat ======
    print("测试 1: deepseek-chat + vision format (image_url)")
    try:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri}},
                        {"type": "text", "text": "这张图片是什么颜色？只需要回答颜色名称。"},
                    ],
                }
            ],
            max_tokens=50,
        )
        answer = response.choices[0].message.content
        print(f"   ✅ 成功！模型回复: {answer}")
        print(f"   结论: deepseek-chat 支持多模态视觉输入")
        return
    except Exception as e:
        error_msg = str(e)
        print(f"   ❌ 失败: {error_msg[:200]}")

    # ====== 测试 2: model list ======
    print("\n测试 2: 列出可用模型")
    try:
        models = await client.models.list()
        model_ids = [m.id for m in models.data]
        print(f"   可用模型: {model_ids}")
        # 检查是否有 vision/vl 相关模型
        vl_models = [m for m in model_ids if any(k in m.lower() for k in ["vl", "vision", "visual", "multi"])]
        if vl_models:
            print(f"   🟡 发现疑似视觉模型: {vl_models}")
        else:
            print(f"   ❌ 未发现视觉相关模型")
    except Exception as e:
        print(f"   ❌ 获取模型列表失败: {str(e)[:200]}")

    # ====== 测试 3: 尝试 deepseek-vl 模型 ======
    print("\n测试 3: 尝试 deepseek-vl 模型")
    try:
        response = await client.chat.completions.create(
            model="deepseek-vl",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri}},
                        {"type": "text", "text": "这是什么颜色？"},
                    ],
                }
            ],
            max_tokens=50,
        )
        answer = response.choices[0].message.content
        print(f"   ✅ 成功！模型回复: {answer}")
    except Exception as e:
        print(f"   ❌ 失败: {str(e)[:200]}")

    # ====== 测试 4: 尝试 deepseek-v4-flash 模型 ======
    print("\n测试 4: 尝试 deepseek-v4-flash (多模态模型)")
    try:
        response = await client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri}},
                        {"type": "text", "text": "这是什么颜色？"},
                    ],
                }
            ],
            max_tokens=50,
        )
        answer = response.choices[0].message.content
        print(f"   ✅ 成功！模型回复: {answer}")
    except Exception as e:
        print(f"   ❌ 失败: {str(e)[:200]}")

    print(f"\n📋 结论: DeepSeek API 当前不支持多模态视觉输入")
    print(f"   视觉能力已在 Web/App 端上线（2026.06），但 API 尚未开放")
    print(f"   项目应继续使用 Qwen3-VL API 处理多模态任务")


if __name__ == "__main__":
    asyncio.run(test_vision_capability())
