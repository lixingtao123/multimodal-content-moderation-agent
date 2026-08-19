"""
测试阿里云 MaaS Qwen3.6-plus 多模态图片理解
用法: python test_qwen_vl.py [/workspace/111.jpg]
"""
import sys
import os
import base64
from pathlib import Path
from openai import OpenAI

# ====== 直接加载 .env 文件 ======
ENV_FILE = Path(__file__).parent / "src" / "backend" / ".env"
env_vars = {}
if ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                env_vars[key.strip()] = val.strip()

QWEN_VL_API_KEY  = env_vars.get("QWEN_VL_API_KEY", "")
QWEN_VL_BASE_URL = env_vars.get("QWEN_VL_BASE_URL", "https://{workspace-id}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")
QWEN_VL_MODEL    = env_vars.get("QWEN_VL_MODEL", "qwen3.6-plus")

if not QWEN_VL_API_KEY:
    print("❌ 未设置 QWEN_VL_API_KEY。请先在 src/backend/.env 配置后重试。", file=sys.stderr)
    sys.exit(1)

print(f"API Base URL: {QWEN_VL_BASE_URL}")
print(f"Model:        {QWEN_VL_MODEL}")
key_preview = QWEN_VL_API_KEY[:10] + "..." if len(QWEN_VL_API_KEY) > 10 else "(empty)"
print(f"API Key:      {key_preview}")

# ====== 图片路径 ======
image_path = sys.argv[1] if len(sys.argv) > 1 else "/workspace/111.jpg"
print(f"Image:        {image_path}")

if not os.path.exists(image_path):
    print(f"ERROR: 图片不存在: {image_path}")
    sys.exit(1)

with open(image_path, "rb") as f:
    image_data = f.read()

img_b64 = base64.b64encode(image_data).decode("utf-8")

fmt = "jpeg"
if image_path.lower().endswith(".png"):
    fmt = "png"
elif image_path.lower().endswith(".webp"):
    fmt = "webp"

data_url = f"data:image/{fmt};base64,{img_b64}"
print(f"Image size:   {len(image_data)} bytes ({len(image_data)/1024:.1f} KB)")

# ====== 创建客户端并调用 ======
client = OpenAI(
    api_key=QWEN_VL_API_KEY,
    base_url=QWEN_VL_BASE_URL,
)

print("\n========== 调用 Qwen3.6-plus 多模态 API ==========")

try:
    response = client.chat.completions.create(
        model=QWEN_VL_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                    {
                        "type": "text",
                        "text": "请详细描述这张图片的内容。包括：1.图片里有什么 2.主要元素 3.可能的场景或用途",
                    },
                ],
            },
        ],
        max_tokens=1000,
        temperature=0.1,
    )

    print("\n✅ API 调用成功！\n")
    print("=" * 60)
    print("模型返回：")
    print("=" * 60)
    print(response.choices[0].message.content)
    print("=" * 60)

    if hasattr(response, "usage"):
        print(f"\nToken 用量: {response.usage}")

except Exception as e:
    print(f"\n❌ API 调用失败: {e}")
    sys.exit(1)
