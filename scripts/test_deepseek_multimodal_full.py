"""
测试 DeepSeek Anthropic 兼容接口的多模态能力
"""
import asyncio, base64, os, sys, json
from openai import AsyncOpenAI

ANTHROPIC_BASE = "https://api.deepseek.com/anthropic"
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = "deepseek-v4-pro"

if not API_KEY:
    print("❌ DEEPSEEK_API_KEY 未设置")
    sys.exit(1)

# 创建测试图片
def create_test_image() -> bytes:
    import struct, zlib
    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b"")

async def test_openai_vision():
    """OpenAI 兼容接口 + vision format"""
    print("\n1️⃣ OpenAI 兼容接口 vision format")
    client = AsyncOpenAI(api_key=API_KEY, base_url="https://api.deepseek.com")
    img_b64 = base64.b64encode(create_test_image()).decode()
    try:
        r = await client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                {"type": "text", "text": "这是什么颜色？"}
            ]}],
            max_tokens=50,
        )
        print(f"   ✅: {r.choices[0].message.content}")
        return True
    except Exception as e:
        print(f"   ❌: {e}")
        return False

async def test_openai_image_param():
    """OpenAI 兼容接口 + image 参数（GPT-4o 风格）"""
    print("\n2️⃣ OpenAI 兼容接口 + image 字段（顶层）")
    client = AsyncOpenAI(api_key=API_KEY, base_url="https://api.deepseek.com")
    img_b64 = base64.b64encode(create_test_image()).decode()
    try:
        r = await client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                {"type": "text", "text": "这是什么颜色？"}
            ]}],
            max_tokens=50,
        )
        print(f"   ✅: {r.choices[0].message.content}")
        return True
    except Exception as e:
        print(f"   ❌: {e}")
        return False

async def test_deepseek_native():
    """DeepSeek 原生多模态格式"""
    print("\n3️⃣ DeepSeek 原生格式 (file + type) ")
    client = AsyncOpenAI(api_key=API_KEY, base_url="https://api.deepseek.com")
    img_b64 = base64.b64encode(create_test_image()).decode()
    try:
        r = await client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": [
                {"type": "file", "file": {"data": img_b64, "mime_type": "image/png"}},
                {"type": "text", "text": "这是什么颜色？"}
            ]}],
            max_tokens=50,
        )
        print(f"   ✅: {r.choices[0].message.content}")
        return True
    except Exception as e:
        print(f"   ❌: {e}")
        return False

async def test_deepseek_url():
    """DeepSeek 多模态 + HTTP URL"""
    print("\n4️⃣ DeepSeek + HTTP URL（非 base64）")
    client = AsyncOpenAI(api_key=API_KEY, base_url="https://api.deepseek.com")
    try:
        r = await client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "https://public.deepseekcdn.com/sample-cat.png"}},
                {"type": "text", "text": "描述这张图片"}
            ]}],
            max_tokens=100,
        )
        print(f"   ✅: {r.choices[0].message.content}")
        return True
    except Exception as e:
        print(f"   ❌: {e}")
        return False

async def test_anthropic_messages():
    """通过 Anthropic Messages API 测试多模态"""
    print("\n5️⃣ Anthropic Messages API（/anthropic 端点）")
    import httpx

    img_b64 = base64.b64encode(create_test_image()).decode()
    headers = {
        "x-api-key": API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": MODEL,
        "max_tokens": 100,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                {"type": "text", "text": "这是什么颜色？"}
            ]
        }]
    }
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{ANTHROPIC_BASE}/v1/messages", headers=headers, json=body)
            if r.status_code == 200:
                data = r.json()
                # Anthropic 格式：content 是 list
                content = data.get("content", [])
                text = " ".join([b.get("text", "") for b in content if b.get("type") == "text"])
                print(f"   ✅: {text}")
                return True
            else:
                print(f"   ❌ HTTP {r.status_code}: {r.text[:300]}")
                return False
    except Exception as e:
        print(f"   ❌: {e}")
        return False

async def main():
    print("🔍 DeepSeek 多模态能力全面探测")
    print(f"   API Key: {API_KEY[:10]}...{API_KEY[-4:]}")

    results = {}
    results["openai_vision"] = await test_openai_vision()
    results["openai_image_param"] = await test_openai_image_param()
    results["deepseek_native"] = await test_deepseek_native()
    results["deepseek_url"] = await test_deepseek_url()
    results["anthropic"] = await test_anthropic_messages()

    print("\n" + "="*60)
    print("📋 结论:")
    for name, ok in results.items():
        print(f"   {'✅' if ok else '❌'} {name}")

    if not any(results.values()):
        print("\n⚠️  所有方式均失败。DeepSeek V4 Pro 多模态 API 可能尚未在 API 端点开放。")
        print("   截图中的 curl 示例可能是即将上线的文档预览。")
    else:
        print(f"\n🎉 至少一种方式成功！可统一使用 DeepSeek 替代 Qwen3-VL")

if __name__ == "__main__":
    asyncio.run(main())
