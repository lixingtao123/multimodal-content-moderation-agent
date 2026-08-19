"""
多模态全链路测试 — 图片+视频+语音+文本
使用真实 API（Qwen3-VL + DeepSeek + FunASR）
"""
import requests
import json
import time
import io
import sys
import os
from PIL import Image, ImageDraw, ImageFont

API = "http://localhost:18080/api/v1"
RESULTS = []

# ============================================================
# 测试图片生成
# ============================================================
def make_image(width, height, color, text=None, draw_pattern=None):
    """创建测试图片"""
    img = Image.new("RGB", (width, height), color=color)
    draw = ImageDraw.Draw(img)
    if text:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((width - tw) // 2, (height - th) // 2), text, fill=(255, 255, 255), font=font)
    if draw_pattern == "qr_like":
        # 画类似二维码的方块图案
        for x in range(10, width - 10, 20):
            for y in range(10, height - 10, 20):
                if (x + y) % 40 < 20:
                    draw.rectangle([x, y, x + 10, y + 10], fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_gradient_image(width, height):
    """创建渐变图片（模拟正常风景）"""
    img = Image.new("RGB", (width, height))
    for y in range(height):
        r = int(100 + (y / height) * 100)
        g = int(150 + (y / height) * 80)
        b = int(200 - (y / height) * 50)
        for x in range(width):
            img.putpixel((x, y), (r, g, b))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_color_blocks():
    """创建色块图（无明确内容）"""
    img = Image.new("RGB", (400, 300), (200, 200, 200))
    draw = ImageDraw.Draw(img)
    for i in range(5):
        x0 = i * 80
        draw.rectangle([x0, 0, x0 + 60, 300], fill=((i * 40) % 256, (i * 60) % 256, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ============================================================
# 测试视频生成
# ============================================================
def make_test_video(duration=3, width=320, height=240, text=""):
    """使用 ffmpeg 生成测试视频"""
    import subprocess, tempfile
    tmpdir = tempfile.mkdtemp()
    video_path = os.path.join(tmpdir, "test_video.mp4")

    # 生成带文字的帧序列
    for i in range(duration):
        img = Image.new("RGB", (width, height), color=((i * 40) % 256, 100, 150))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
        except Exception:
            font = ImageFont.load_default()
        full_text = f"{text} Frame {i+1}" if text else f"Frame {i+1} - 测试画面"
        draw.text((20, height // 2 - 10), full_text, fill=(255, 255, 255), font=font)
        img.save(os.path.join(tmpdir, f"frame_{i:03d}.png"))

    # 用 ffmpeg 合成视频
    try:
        subprocess.run([
            "ffmpeg", "-y", "-framerate", "1", "-i", f"{tmpdir}/frame_%03d.png",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", video_path
        ], capture_output=True, timeout=30)
        if os.path.exists(video_path):
            with open(video_path, "rb") as f:
                data = f.read()
            return data
    except Exception as e:
        print(f"  Video generation failed: {e}")
    return None


# ============================================================
# 测试音频生成
# ============================================================
def make_test_audio():
    """生成简单的 WAV 测试音频"""
    import wave, struct, math
    buf = io.BytesIO()
    sr, dur = 16000, 2.0
    with wave.open(buf, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        for i in range(int(sr * dur)):
            t = i / sr
            val = int(8000 * (math.sin(2 * math.pi * 200 * t) + 0.5 * math.sin(2 * math.pi * 400 * t)))
            wf.writeframes(struct.pack('<h', max(-32768, min(32767, val))))
    buf.seek(0)
    return buf.read()


# ============================================================
# API 测试
# ============================================================
def test_text(text, label=""):
    """测试文本审核"""
    r = requests.post(f"{API}/moderate/text", json={"text": text}, timeout=60)
    result = r.json()
    RESULTS.append({"type": "text", "label": label, "result": result})
    return result


def test_image(img_data, label=""):
    """测试图片审核"""
    r = requests.post(f"{API}/moderate/image",
                      files={"file": ("test.png", img_data, "image/png")},
                      timeout=60)
    result = r.json()
    RESULTS.append({"type": "image", "label": label, "result": result})
    return result


def test_audio(audio_data, label=""):
    """测试音频审核"""
    r = requests.post(f"{API}/moderate/audio",
                      files={"file": ("test.wav", audio_data, "audio/wav")},
                      timeout=60)
    try:
        result = r.json()
    except Exception:
        result = {"error": r.text}
    RESULTS.append({"type": "audio", "label": label, "result": result})
    return result


def test_video(video_data, label=""):
    """测试视频审核"""
    if not video_data:
        return None
    r = requests.post(f"{API}/moderate/video",
                      files={"file": ("test.mp4", video_data, "video/mp4")},
                      timeout=120)
    try:
        result = r.json()
    except Exception:
        result = {"error": r.text}
    RESULTS.append({"type": "video", "label": label, "result": result})
    return result


# ============================================================
# 主流程
# ============================================================
def print_result(item, idx):
    r = item["result"]
    t = item["type"]
    label = item.get("label", "")
    decision = r.get("final_decision", "?")
    score = r.get("risk_score", 0)
    vtypes = r.get("violation_types", [])
    ms = r.get("processing_time_ms", 0)

    verdict = "✅" if (label == "normal" and decision == "PASS") or \
                      (label == "violation" and decision in ("REVIEW", "REJECT")) else "⚠️"

    print(f"  {idx:2d}. [{verdict}] {t:5s} | {decision:6s} | score={score:.3f} | "
          f"types={vtypes} | {ms:.0f}ms | {label}")


def main():
    print("=" * 70)
    print("多模态全链路真实 API 测试")
    print("=" * 70)

    # ---- 文本测试 ----
    print("\n--- 文本模态 ---")
    test_text("今天天气真好，适合出去散步", "normal")
    test_text("推荐一本好书，分享读书心得", "normal")
    test_text("加微信xxx免费领取红包，扫码关注有惊喜", "violation")
    test_text("美女私密视频裸聊在线观看", "violation")
    test_text("我要杀了你全家", "violation")
    test_text("恭喜中奖请点击链接领取奖金", "violation")
    test_text("vjp低价出售加薇信", "violation")  # adversarial

    # ---- 图片测试 ----
    print("\n--- 图片模态 (Qwen3-VL) ---")

    # 正常图片
    img_normal = make_gradient_image(800, 600)
    test_image(img_normal, "normal")

    img_blocks = make_color_blocks()
    test_image(img_blocks, "normal")

    # 含敏感文字的图片
    img_ad_text = make_image(600, 400, (50, 50, 50), "加微信 xxx123 免费领取红包")
    test_image(img_ad_text, "violation")

    img_violent_text = make_image(500, 300, (80, 20, 20), "我要杀人 暴力示威")
    test_image(img_violent_text, "violation")

    # 类二维码图
    img_qr = make_image(200, 200, (255, 255, 255), draw_pattern="qr_like")
    test_image(img_qr, "violation")

    # 色情暗示文字
    img_porn_text = make_image(600, 400, (100, 0, 50), "美女裸聊 私密视频 成人内容")
    test_image(img_porn_text, "violation")

    # ---- 语音测试 ----
    print("\n--- 语音模态 (FunASR) ---")
    audio = make_test_audio()
    test_audio(audio, "normal")

    # ---- 视频测试 ----
    print("\n--- 视频模态 ---")
    video_normal = make_test_video(3, 320, 240, "风景")
    if video_normal:
        test_video(video_normal, "normal")

    video_ad = make_test_video(3, 320, 240, "加微信领红包")
    if video_ad:
        test_video(video_ad, "violation")

    # ---- 结果汇总 ----
    print("\n" + "=" * 70)
    print("测试结果汇总")
    print("=" * 70)
    passed = 0
    failed = 0
    for i, item in enumerate(RESULTS):
        print_result(item, i + 1)
        r = item["result"]
        label = item.get("label", "")
        decision = r.get("final_decision", "?")
        if (label == "normal" and decision == "PASS") or \
           (label == "violation" and decision in ("REVIEW", "REJECT")):
            passed += 1
        else:
            failed += 1

    print(f"\n总计: {passed} 通过, {failed} 失败, {len(RESULTS)} 样本")
    print(f"通过率: {passed/len(RESULTS)*100:.1f}%")

    # 按类别统计
    for t in ["text", "image", "audio", "video"]:
        items = [r for r in RESULTS if r["type"] == t]
        if items:
            normal_items = [r for r in items if r["label"] == "normal"]
            violation_items = [r for r in items if r["label"] == "violation"]
            normal_ok = sum(1 for r in normal_items if r["result"].get("final_decision") == "PASS")
            violation_ok = sum(1 for r in violation_items if r["result"].get("final_decision") in ("REVIEW", "REJECT"))
            print(f"  {t}: 正常 {normal_ok}/{len(normal_items)} | 违规 {violation_ok}/{len(violation_items)}")

    return passed, failed


if __name__ == "__main__":
    main()
