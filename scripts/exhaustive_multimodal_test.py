"""
穷举 DeepSeek 多模态 API 的所有可能调用方式
"""
import os, sys, requests, base64
from io import BytesIO

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not API_KEY:
    env_file = "src/backend/.env"
    if os.path.exists(env_file):
        for line in open(env_file):
            if line.startswith("DEEPSEEK_API_KEY="):
                API_KEY = line.strip().split("=", 1)[1]
                break

# 生成测试图
from PIL import Image, ImageDraw
img = Image.new("RGB", (200, 200), color="orange")
draw = ImageDraw.Draw(img)
draw.rectangle([20, 20, 80, 80], fill="blue")
draw.ellipse([100, 100, 180, 180], fill="red")
buf = BytesIO()
img.save(buf, format="PNG")
IMG_B64 = base64.b64encode(buf.getvalue()).decode()

# 注意: DeepSeek 文档中的模型名可能有多个版本
MODELS = ["deepseek-chat-v4", "deepseek-v4-pro", "deepseek-v4-flash", "deepseek-chat"]

# 不同的 header 组合
HEADER_VARIANTS = {
    "基础": {"Content-Type": "application/json"},
    "multipart/mixed": {"Content-Type": "application/json", "Accept": "multipart/mixed"},
    "text/event-stream": {"Content-Type": "application/json", "Accept": "text/event-stream"},
}

# 不同的 content 格式
CONTENT_VARIANTS = {
    "image_url(base64)": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{IMG_B64}"}}, {"type": "text", "text": "描述这张图片"}],
    "text+image_url(base64)": [{"type": "text", "text": "描述这张图片"}, {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{IMG_B64}"}}],
    "image_url(url)": [{"type": "image_url", "image_url": {"url": "https://public.deepseekcdn.com/sample-cat.png"}}, {"type": "text", "text": "描述这张图片"}],
    "纯text": "描述一张橙色背景上有蓝色方块和红色圆形的图片",
}

def test(model, header_name, headers, content_name, content):
    payload = {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": 150}
    try:
        r = requests.post("https://api.deepseek.com/v1/chat/completions",
                          headers={**headers, "Authorization": f"Bearer {API_KEY}"},
                          json=payload, timeout=30)
        status = r.status_code
        if status == 200:
            data = r.json()
            reply = data["choices"][0]["message"]["content"][:150]
            usage = data.get("usage", {})
            return f"✅ {status} | tokens={usage.get('prompt_tokens','?')}/{usage.get('completion_tokens','?')} | {reply}"
        else:
            err = r.json().get("error", {}).get("message", r.text)[:120]
            return f"❌ {status} | {err}"
    except Exception as e:
        return f"💥 {e}"

print(f"🔬 DeepSeek 多模态穷举测试")
print(f"   图片 base64 长度: {len(IMG_B64)}")
print(f"   {len(MODELS)} 模型 × {len(HEADER_VARIANTS)} header × {len(CONTENT_VARIANTS)} content = {len(MODELS)*len(HEADER_VARIANTS)*len(CONTENT_VARIANTS)} 组合\n")

for model in MODELS:
    for h_name, h in HEADER_VARIANTS.items():
        for c_name, c in CONTENT_VARIANTS.items():
            result = test(model, h_name, h, c_name, c)
            print(f"[{model}] [{h_name}] [{c_name}] → {result}")
    print()
