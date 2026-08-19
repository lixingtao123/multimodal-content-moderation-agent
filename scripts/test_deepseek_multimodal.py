"""
DeepSeek V4 Pro 多模态能力验证
使用 OpenAI 兼容的 Vision API 格式
"""
import asyncio, base64, json, os, sys
from io import BytesIO
from openai import AsyncOpenAI

BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")

# API Key 只能从环境变量读取
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not DEEPSEEK_API_KEY:
    print("❌ 请先设置 DEEPSEEK_API_KEY 环境变量")
    print("   export DEEPSEEK_API_KEY=sk-xxx")
    sys.exit(1)

# 测试图片（DeepSeek 官方示例 + 1x1 像素红色 PNG 作为 fallback）
TEST_IMAGES = [
    ("DeepSeek 官方示例猫图", "https://public.deepseekcdn.com/sample-cat.png"),
]


def create_test_image() -> bytes:
    """1x1 红色像素 PNG"""
    import struct, zlib
    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b"")


async def test_vision(client: AsyncOpenAI, label: str, image_input: str):
    """用 vision format 调 API"""
    print(f"\n{'='*60}")
    print(f"📸 测试: {label}")
    print(f"   Model: {MODEL}")

    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": image_input}},
            {"type": "text", "text": "请用中文描述这张图片的内容，包括里面有什么物体、颜色、场景等。"},
        ]
    }]

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=500,
        )
        answer = response.choices[0].message.content
        usage = response.usage
        print(f"   ✅ 成功！")
        print(f"   Token 用量: prompt={usage.prompt_tokens}, completion={usage.completion_tokens}")
        print(f"   回复内容:\n---\n{answer}\n---")
        return True
    except Exception as e:
        print(f"   ❌ 失败: {e}")
        return False


async def test_pure_text(client: AsyncOpenAI):
    """纯文本测试（验证 API 基本连通性）"""
    print(f"\n{'='*60}")
    print(f"📝 测试: 纯文本 (验证 API 连通性)")
    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "你好，请说一个词"}],
            max_tokens=20,
        )
        print(f"   ✅ 连通: {response.choices[0].message.content}")
        return True
    except Exception as e:
        print(f"   ❌ 失败: {e}")
        return False


async def main():
    print(f"🔍 DeepSeek V4 Pro 多模态能力验证")
    print(f"   Base URL: {BASE_URL}")
    print(f"   API Key:  {DEEPSEEK_API_KEY[:10]}...{DEEPSEEK_API_KEY[-4:]}")

    client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=BASE_URL)

    # 1. 纯文本连通性
    if not await test_pure_text(client):
        print("\n⛔ API 基本连通性失败，请检查 API Key 和网络")
        return

    # 2. URL 图片
    for label, url in TEST_IMAGES:
        await test_vision(client, label, url)

    # 3. Base64 图片
    img_b64 = base64.b64encode(create_test_image()).decode("utf-8")
    await test_vision(client, "1x1 红色像素 PNG (base64)", f"data:image/png;base64,{img_b64}")

    print(f"\n{'='*60}")
    print("✅ 验证完成")


if __name__ == "__main__":
    asyncio.run(main())
