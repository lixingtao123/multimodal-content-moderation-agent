"""
FunASR 语音转文本 HTTP 服务
使用 SenseVoiceSmall 模型（modelscope），GPU 加速
提供 /transcribe + /health 端点
"""
import re
import logging
from fastapi import FastAPI, UploadFile, File, HTTPException
from funasr import AutoModel

logging.basicConfig(level=logging.INFO,
                    format='[FunASR] %(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="FunASR Speech-to-Text Service", version="2.0.0")

# 加载 SenseVoiceSmall 模型（GPU 优先）
model = None
MODEL_DEVICE = "cpu"


def load_model():
    global model, MODEL_DEVICE
    try:
        import torch
        if torch.cuda.is_available():
            MODEL_DEVICE = "cuda:0"
            logger.info(f"GPU detected: {torch.cuda.get_device_name(0)}")
    except ImportError:
        pass

    logger.info(f"Loading SenseVoiceSmall on {MODEL_DEVICE}...")
    model = AutoModel(
        model="iic/SenseVoiceSmall",
        device=MODEL_DEVICE,
        disable_update=True,
    )
    logger.info(f"SenseVoiceSmall loaded on {MODEL_DEVICE}")


def clean_text(raw: str) -> str:
    """清洗 SenseVoiceSmall 输出"""
    # 移除特殊标记: <|zh|>, <|en|>, <|NEUTRAL|>, <|HAPPY|> 等
    cleaned = re.sub(r'<\|[^|]+\|>', '', raw)
    # 移除多余空白
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


@app.on_event("startup")
async def startup():
    load_model()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model": "iic/SenseVoiceSmall",
        "device": MODEL_DEVICE,
        "ready": model is not None,
    }


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    """语音转文本，支持 wav/mp3/flac/ogg 等格式"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    try:
        audio_bytes = await file.read()
        logger.info(f"Transcribing: {file.filename}, {len(audio_bytes)} bytes")

        result = model.generate(input=audio_bytes)

        if result and len(result) > 0:
            raw_text = result[0].get("text", "")
            text = clean_text(raw_text)
            logger.info(f"Result: '{text[:120]}...'" if len(text) > 120 else f"Result: '{text}'")
            return {"text": text, "raw": raw_text}
        else:
            return {"text": "", "raw": ""}

    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")


if __name__ == "__main__":
    import os

    import uvicorn
    uvicorn.run(app, host="0.0.0.0",
                port=int(os.environ.get("FUNASR_PORT", "15001")))
