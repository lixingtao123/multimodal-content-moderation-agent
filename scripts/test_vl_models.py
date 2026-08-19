"""Test which Qwen models support vision"""
import os, sys, base64, json, asyncio
# API key 从环境/backend .env 读取，不硬编码（R22·D3）
from pathlib import Path
_env_file = Path(__file__).parent.parent / "src" / "backend" / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
if not os.environ.get('QWEN_VL_API_KEY'):
    print("❌ 未设置 QWEN_VL_API_KEY。请先在 src/backend/.env 配置后重试。", file=sys.stderr)
    sys.exit(1)
from openai import AsyncOpenAI
from PIL import Image, ImageDraw
import io

async def test_model(model_name):
    client = AsyncOpenAI(api_key=os.environ['QWEN_VL_API_KEY'], base_url=os.environ['QWEN_VL_BASE_URL'])
    img = Image.new('RGB', (200, 100), (50, 50, 50))
    draw = ImageDraw.Draw(img)
    draw.text((20, 40), 'Hello World', fill=(255, 255, 255))
    buf = io.BytesIO(); img.save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode()
    try:
        resp = await client.chat.completions.create(
            model=model_name,
            messages=[{'role': 'user', 'content': [
                {'type': 'image_url', 'image_url': {'url': f'data:image/png;base64,{b64}'}},
                {'type': 'text', 'text': '描述这张图片'}
            ]}],
            max_tokens=100, timeout=30,
        )
        content = resp.choices[0].message.content
        print(f'{model_name}: ✅ {content[:80]}')
        return True
    except Exception as e:
        print(f'{model_name}: ❌ {str(e)[:120]}')
        return False

async def main():
    models = ['qwen3.6-plus', 'qwen-vl-plus', 'qwen3-vl-plus', 'qwen-vl-max', 'qwen2.5-vl-72b-instruct']
    for m in models:
        await test_model(m)

asyncio.run(main())
