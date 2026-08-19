"""
音频/视频域扩展工具（R19·MCP 扩展批 4）

确定性规则 + 文件元数据解析（不调外部 ASR/VL API）：
  - audio_metadata_check   音频元数据（时长/采样率/格式）
  - video_frame_plan       视频抽帧策略（按时长分布抽帧点）
  - media_toxic_estimate   媒体违规概率估计（文件特征+可用信号综合）

说明：解析失败/无依赖时返回 degraded 标注（诚实降级）。
"""
import os
from typing import List, Optional
from pydantic import BaseModel


class AudioMetadataResult(BaseModel):
    duration_sec: Optional[float]
    sample_rate: Optional[int]
    format: str
    degraded: bool
    summary: str


class AudioMetadataCheckTool:
    name = "audio_metadata_check"
    description = "解析音频元数据（时长/采样率/格式），无 mutagen 时按文件头估算"

    async def execute(self, audio_path: str = "", file_bytes: str = "") -> AudioMetadataResult:
        if audio_path and os.path.exists(audio_path):
            size = os.path.getsize(audio_path)
            ext = os.path.splitext(audio_path)[1].lower()
            try:
                import mutagen
                mf = mutagen.File(audio_path)
                dur = getattr(mf.info, "length", None)
                sr = getattr(mf.info, "sample_rate", None)
                return AudioMetadataResult(
                    duration_sec=round(dur, 2) if dur else None, sample_rate=sr,
                    format=ext.lstrip(".") or "unknown", degraded=False,
                    summary=f"时长 {dur:.1f}s" if dur else "未知时长",
                )
            except ImportError:
                # 无 mutagen：按文件大小粗估（16kHz 16bit 单声道 ≈ 32KB/s）
                est = size / 32000 if size else None
                return AudioMetadataResult(
                    duration_sec=round(est, 2) if est else None, sample_rate=None,
                    format=ext.lstrip(".") or "unknown", degraded=True,
                    summary=f"无 mutagen，按大小粗估 {est:.1f}s" if est else "无法解析",
                )
        return AudioMetadataResult(duration_sec=None, sample_rate=None, format="", degraded=True, summary="无有效音频输入")


class FramePoint(BaseModel):
    at_sec: float
    reason: str


class VideoFramePlanResult(BaseModel):
    total_duration_sec: Optional[float]
    frames: List[FramePoint]
    strategy: str


class VideoFramePlanTool:
    name = "video_frame_plan"
    description = "生成视频抽帧策略（按总时长均匀+分段关键点采样）"

    async def execute(self, duration_sec: float = 60.0, frame_count: int = 9) -> VideoFramePlanResult:
        duration_sec = max(duration_sec, 1.0)
        frame_count = min(max(int(frame_count), 1), 24)
        points = []
        if duration_sec <= frame_count:
            for i in range(int(duration_sec)):
                points.append(FramePoint(at_sec=round(i + 0.5, 2), reason="逐秒"))
        else:
            step = duration_sec / frame_count
            for i in range(frame_count):
                points.append(FramePoint(at_sec=round(step * (i + 0.5), 2), reason="均匀采样"))
            # 追加关键段（开头/结尾/中段）用于内容突变检测
            marks = [1.0, max(1.0, duration_sec / 2), max(2.0, duration_sec - 1.0)]
            for m in marks:
                if all(abs(p.at_sec - m) > step / 2 for p in points):
                    points.append(FramePoint(at_sec=round(m, 2), reason="关键段"))
        points.sort(key=lambda p: p.at_sec)
        return VideoFramePlanResult(
            total_duration_sec=duration_sec, frames=points,
            strategy=f"{frame_count} 均匀帧 + 关键段",
        )


class MediaToxicResult(BaseModel):
    estimate: float
    signals: List[str]
    degraded: bool
    summary: str


class MediaToxicEstimateTool:
    """媒体违规概率估计 — 使用可用信号（文件名/音频文本）启发式，诚实标注局限"""

    name = "media_toxic_estimate"
    description = "媒体违规概率估计（文件名/伴随文本信号启发式）"

    TOXIC_KEYWORDS = ["色情", "裸", "淫", "暴力", "血腥", "恐怖", "诈骗", "赌博", "毒品", "违禁"]

    async def execute(self, filename: str = "", transcript: str = "") -> MediaToxicResult:
        signals, score = [], 0.0
        hay = f"{filename} {transcript}"
        for kw in self.TOXIC_KEYWORDS:
            if kw in hay:
                score += 0.25
                signals.append(f"命中关键词: {kw}")
        score = min(score, 1.0)
        return MediaToxicResult(
            estimate=round(score, 3), signals=signals,
            degraded=not transcript,  # 无转写时精度有限，如实标注
            summary=f"启发式估计 {score:.0%}" + ("（无转写，仅文件名）" if not transcript else ""),
        )
