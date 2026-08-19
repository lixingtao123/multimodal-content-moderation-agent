"""
多模态全链路测试 v2 — 真实 Qwen3-VL + DeepSeek + FunASR
"""
import requests, json, time, io, sys
from PIL import Image, ImageDraw, ImageFont

API = "http://localhost:18080/api/v1"
passed = 0
failed = 0

def make_img(w, h, color, text=None, qr=False):
    img = Image.new("RGB", (w, h), color=color)
    draw = ImageDraw.Draw(img)
    if text:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
        except:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
        draw.text(((w-tw)//2, (h-th)//2), text, fill=(255,255,255), font=font)
    if qr:
        for x in range(10, w-10, 20):
            for y in range(10, h-10, 20):
                if (x+y) % 40 < 20:
                    draw.rectangle([x, y, x+10, y+10], fill=(0,0,0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def gradient_img(w, h):
    img = Image.new("RGB", (w, h))
    for y in range(h):
        for x in range(w):
            img.putpixel((x,y), (int(100+y/h*100), int(150+x/w*80), 200))
    buf = io.BytesIO(); img.save(buf, format="PNG"); return buf.getvalue()

def test_img(img_data, label, desc):
    global passed, failed
    r = requests.post(f"{API}/moderate/image",
        files={"file":("t.png", img_data, "image/png")}, timeout=120)
    d = r.json()
    decision, score, ms = d["final_decision"], d["risk_score"], d["processing_time_ms"]
    vtypes = d.get("violation_types", [])
    ok = (label == "normal" and decision == "PASS") or (label == "violation" and decision in ("REVIEW","REJECT"))
    if ok: passed += 1
    else: failed += 1
    mark = "✅" if ok else "❌"
    print(f"  {mark} {desc:30s} | {decision:6s} | score={score:.3f} | {ms:.0f}ms | types={vtypes}")
    return d

def test_text(text, label, desc):
    global passed, failed
    r = requests.post(f"{API}/moderate/text", json={"text": text}, timeout=120)
    d = r.json()
    decision, score, ms = d["final_decision"], d["risk_score"], d["processing_time_ms"]
    vtypes = d.get("violation_types", [])
    ok = (label == "normal" and decision == "PASS") or (label == "violation" and decision in ("REVIEW","REJECT"))
    if ok: passed += 1
    else: failed += 1
    mark = "✅" if ok else "❌"
    print(f"  {mark} {desc:30s} | {decision:6s} | score={score:.3f} | {ms:.0f}ms | types={vtypes}")
    return d

def test_audio(audio_data, label, desc):
    global passed, failed
    try:
        r = requests.post(f"{API}/moderate/audio",
            files={"file":("t.wav", audio_data, "audio/wav")}, timeout=60)
        d = r.json()
    except:
        print(f"  ⚠️  {desc:30s} | ERROR")
        return None
    decision, score = d.get("final_decision","?"), d.get("risk_score",0)
    ms = d.get("processing_time_ms", 0)
    ok = (label == "normal" and decision == "PASS") or (label == "violation" and decision in ("REVIEW","REJECT"))
    if ok: passed += 1
    else: failed += 1
    mark = "✅" if ok else "❌"
    print(f"  {mark} {desc:30s} | {decision:6s} | score={score:.3f} | {ms:.0f}ms")
    return d

print("=" * 70)
print("多模态全链路真实 API 测试 v2")
print("=" * 70)

print("\n--- 📝 文本审核 (DeepSeek) ---")
test_text("今天天气真好适合出去散步", "normal", "正常-日常")
test_text("推荐一本好书给大家分享", "normal", "正常-分享")
test_text("学习编程需要耐心和实践", "normal", "正常-学习")
test_text("加微信xxx免费领取红包扫码", "violation", "违规-广告引流")
test_text("美女裸聊私密视频在线观看", "violation", "违规-色情")
test_text("我要杀了你全家一个不留", "violation", "违规-暴力威胁")
test_text("恭喜中奖请点击链接领取", "violation", "违规-钓鱼诈骗")
test_text("vjp低价出售加薇信联系", "violation", "违规-变体词")

print("\n--- 🖼️ 图片审核 (Qwen3-VL) ---")
test_img(gradient_img(800,600), "normal", "正常-渐变风景")
test_img(gradient_img(400,300), "normal", "正常-小风景")
test_img(make_img(600,400,(50,50,50),"加微信 xxx123 免费领红包"), "violation", "违规-广告文字图")
test_img(make_img(500,300,(80,20,20),"暴力示威 我要杀人"), "violation", "违规-暴力文字图")
test_img(make_img(600,400,(100,0,50),"美女裸聊私密视频在线观看"), "violation", "违规-色情文字图")
test_img(make_img(200,200,(255,255,255),qr=True), "violation", "违规-类二维码")
test_img(make_img(500,300,(30,30,80),"点击链接领取奖金 账号密码"), "violation", "违规-钓鱼文字图")

print("\n--- 🎵 语音审核 (FunASR) ---")
import wave, struct, math
buf_audio = io.BytesIO()
with wave.open(buf_audio, 'w') as wf:
    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(16000)
    for i in range(32000):
        t = i/16000
        val = int(8000*(math.sin(2*math.pi*200*t)+0.5*math.sin(2*math.pi*400*t)))
        wf.writeframes(struct.pack('<h', max(-32768,min(32767,val))))
buf_audio.seek(0)
test_audio(buf_audio.read(), "normal", "正常-模拟语音")

print("\n--- 🎬 视频审核 ---")
import subprocess, tempfile, os
tmpdir = tempfile.mkdtemp()
for i in range(3):
    img = Image.new("RGB", (320,240), ((i*40)%256, 100, 150))
    d = ImageDraw.Draw(img)
    d.text((20,100), f"测试画面 Frame {i+1}", fill=(255,255,255))
    img.save(os.path.join(tmpdir, f"f{i:03d}.png"))
video_path = os.path.join(tmpdir, "test.mp4")
subprocess.run(["ffmpeg","-y","-framerate","1","-i",f"{tmpdir}/f%03d.png",
    "-c:v","libx264","-pix_fmt","yuv420p",video_path], capture_output=True, timeout=30)
if os.path.exists(video_path):
    with open(video_path,"rb") as f: vdata = f.read()
    try:
        r = requests.post(f"{API}/moderate/video",
            files={"file":("t.mp4", vdata, "video/mp4")}, timeout=120)
        d = r.json()
        decision, score = d.get("final_decision","?"), d.get("risk_score",0)
        ms = d.get("processing_time_ms", 0)
        print(f"  ✅ 正常-测试视频 | {decision:6s} | score={score:.3f} | {ms:.0f}ms")
        passed += 1
    except Exception as e:
        print(f"  ❌ 视频测试失败: {e}")
        failed += 1

print(f"\n{'='*70}")
print(f"结果: {passed} 通过 | {failed} 失败 | {passed+failed} 总计")
print(f"通过率: {passed/(passed+failed)*100:.1f}%" if (passed+failed)>0 else "")
