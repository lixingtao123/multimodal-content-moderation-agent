"""
Video Agent — 视频内容审核
1. ffmpeg 抽帧（关键帧采样）
2. 逐帧视觉审核（Qwen3-VL，阿里云 MaaS / Mock）
3. 音频轨道提取 + FunASR 语音转文本
4. 时间轴风险对齐 + 综合评分

环境变量控制：
  IMAGE_AGENT_MOCK=false  → 启用真实 VL API 调用
  QWEN_VL_API_KEY         → API Key（阿里云 MaaS 控制台获取）
  QWEN_VL_BASE_URL        → API 端点（兼容 OpenAI 格式）
  QWEN_VL_MODEL           → 模型名（默认 qwen3-vl-plus）
"""
import os
import io
import json
import logging
import tempfile
import subprocess
import base64
from agent_moderation.state import ModerationState
from agent_moderation.agents.base import BaseAgent
from memory.manager import get_memory_manager
from common.funasr_client import get_funasr_client
from common.config import get_settings

logger = logging.getLogger(__name__)

# 抽帧参数
MAX_FRAMES = 10          # 最多抽 10 帧
FRAME_INTERVAL = 5       # 每 5 秒抽一帧


class VideoAgent(BaseAgent):
    """视频审核 Agent — ffmpeg 抽帧 + VL + FunASR"""

    def __init__(self):
        super().__init__("video_agent")
        self.memory = get_memory_manager()
        self.funasr = get_funasr_client()
        settings = get_settings()
        self._mock_mode = settings.image_agent_mock
        self._vl_client = None
        if not self._mock_mode:
            try:
                from common.api_clients import get_vl_model_client
                self._vl_client = get_vl_model_client()
                logger.info("VideoAgent: VL client initialized (REAL MODE)")
            except Exception as e:
                # R22: 不静默回退 mock（禁止伪造结果）
                logger.error(f"VideoAgent: VL client init failed (NO mock fallback): {e}")
                self._vl_client = None
        else:
            logger.info("VideoAgent: Mock mode (显式配置 IMAGE_AGENT_MOCK=true)")

    async def process(self, state: ModerationState) -> ModerationState:
        """视频审核全流程"""
        content = state.get("content", {})
        video_data = content.get("video") or content.get("video_data") or b""

        if not video_data:
            state["video_result"] = {"error": "empty video", "overall_risk_score": 0.0}
            return state

        content_id = state.get("content_id", "unknown")
        self.log_step(f"Analyzing video: {len(video_data)} bytes (mock={self._mock_mode})")
        await self.memory.update_task_step(content_id, "video_agent")

        # 1. 保存到临时文件
        video_path = None
        try:
            suffix = self._detect_format(video_data)
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(video_data)
                video_path = f.name
        except Exception as e:
            logger.error(f"Failed to save video temp file: {e}")
            state["video_result"] = {"error": f"temp file error: {e}", "overall_risk_score": 0.0}
            return state

        try:
            # 2. 获取视频元信息
            video_info = self._get_video_info(video_path)
            self.log_step(f"Video: {video_info.get('duration', 0):.1f}s, "
                          f"{video_info.get('width', 0)}x{video_info.get('height', 0)}")

            # 3. 抽取关键帧
            frames = self._extract_frames(video_path, video_info)

            # 4. 逐帧分析
            # R22: 真实模式下 VL client 缺失 → 显式 error（禁止 mock 伪造）
            if not self._mock_mode and self._vl_client is None:
                state["video_result"] = {
                    "error": "VL client unavailable (image_agent_mock=false 但 QWEN_VL_API_KEY 未配置)",
                    "overall_risk_score": 0.0, "mock_mode": False,
                }
                return state
            frame_results = []
            for frame in frames:
                if self._mock_mode:
                    result = self._mock_analyze_frame(frame)
                else:
                    result = await self._vl_analyze_frame(frame, content_id)
                frame_results.append(result)

            # 5. 音频抽取 + 转文本
            audio_bytes = self._extract_audio(video_path)
            audio_text = ""
            if audio_bytes and len(audio_bytes) > 100:
                stt_result = await self.funasr.transcribe(audio_bytes, filename="video_audio.wav")
                audio_text = stt_result.get("text", "") if stt_result.get("success") else ""

            # 6. 综合评分
            risk_score, risk_timeline = self._calculate_video_risk(frame_results, audio_text, video_info)

            state["video_result"] = {
                "video_info": video_info,
                "frame_count": len(frames),
                "frames_analyzed": len(frame_results),
                "frame_results": frame_results,
                "audio_text": audio_text[:500] if audio_text else "",
                "risk_timeline": risk_timeline,
                "overall_risk_score": risk_score,
                "mock_mode": self._mock_mode,
            }

        finally:
            # 清理临时文件
            if video_path and os.path.exists(video_path):
                try:
                    os.unlink(video_path)
                except Exception:
                    pass

        return state

    def _detect_format(self, video_data: bytes) -> str:
        """检测视频格式"""
        # 简单检测常见格式头
        if video_data[:4] == b'\x00\x00\x00\x1c' or video_data[:4] == b'\x00\x00\x00\x20':
            return ".mp4"
        elif video_data[:3] == b'\x1a\x45\xdf':
            return ".webm"
        elif video_data[:4] == b'RIFF':
            return ".avi"
        return ".mp4"

    def _get_video_info(self, video_path: str) -> dict:
        """获取视频元信息"""
        info = {"duration": 0, "width": 0, "height": 0, "fps": 0, "codec": "unknown"}
        try:
            # ffprobe JSON 输出
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet", "-print_format", "json",
                    "-show_format", "-show_streams", video_path,
                ],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                probe = json.loads(result.stdout)
                # 获取时长
                fmt_info = probe.get("format", {})
                info["duration"] = float(fmt_info.get("duration", 0))
                info["bitrate"] = int(fmt_info.get("bit_rate", 0))
                # 获取视频流信息
                for stream in probe.get("streams", []):
                    if stream.get("codec_type") == "video":
                        info["width"] = stream.get("width", 0)
                        info["height"] = stream.get("height", 0)
                        info["codec"] = stream.get("codec_name", "unknown")
                        fps_str = stream.get("r_frame_rate", "0/1")
                        num, den = fps_str.split("/") if "/" in fps_str else (fps_str, "1")
                        info["fps"] = round(float(num) / max(float(den), 1), 2)
                        break
        except FileNotFoundError:
            logger.warning("ffprobe not found — video analysis degraded")
        except Exception as e:
            logger.warning(f"ffprobe failed: {e}")
        return info

    def _extract_frames(self, video_path: str, video_info: dict) -> list:
        """使用 ffmpeg 抽取关键帧"""
        frames = []
        duration = video_info.get("duration", 0)

        try:
            # 计算抽帧间隔
            if duration > 0:
                interval = max(duration / min(MAX_FRAMES, max(duration / FRAME_INTERVAL, 1)), 1)
            else:
                interval = FRAME_INTERVAL

            with tempfile.TemporaryDirectory() as tmpdir:
                # ffmpeg 抽帧
                result = subprocess.run(
                    [
                        "ffmpeg", "-v", "quiet", "-ss", "1",
                        "-i", video_path,
                        "-vf", f"fps=1/{interval}",
                        "-vframes", str(MAX_FRAMES),
                        "-f", "image2", f"{tmpdir}/frame_%03d.jpg",
                    ],
                    capture_output=True, text=True, timeout=60,
                )

                if result.returncode == 0:
                    import glob
                    frame_files = sorted(glob.glob(f"{tmpdir}/frame_*.jpg"))
                    for i, fpath in enumerate(frame_files):
                        with open(fpath, "rb") as ff:
                            frames.append({
                                "index": i + 1,
                                "timestamp": round((i + 1) * interval, 1),
                                "data": ff.read(),
                            })
        except FileNotFoundError:
            logger.warning("ffmpeg not found — frame extraction skipped")
        except Exception as e:
            logger.error(f"Frame extraction failed: {e}")

        logger.info(f"Extracted {len(frames)} frames from video")
        return frames

    def _extract_audio(self, video_path: str) -> bytes:
        """从视频提取音频轨道"""
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-v", "quiet", "-i", video_path,
                    "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    "-f", "wav", "pipe:1",
                ],
                capture_output=True, timeout=60,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
        except FileNotFoundError:
            logger.warning("ffmpeg not found — audio extraction skipped")
        except Exception as e:
            logger.warning(f"Audio extraction failed: {e}")
        return b""

    def _mock_analyze_frame(self, frame: dict) -> dict:
        """Mock 帧分析"""
        data = frame.get("data", b"")
        size_kb = len(data) / 1024

        # 基础判断
        risk = "none"
        confidence = 0.0
        signals = []

        # 极小帧（可能是黑屏/过渡）
        if size_kb < 2:
            signals.append("可能是黑屏/暗帧")
        # 大帧可能有违规
        if size_kb > 200:
            signals.append("高细节帧，需人工审核")
            confidence = 0.2

        return {
            "frame_index": frame["index"],
            "timestamp": frame["timestamp"],
            "violation_type": risk,
            "confidence": confidence,
            "signals": signals,
            "needs_vl_model": True,
        }

    async def _vl_analyze_frame(self, frame: dict, content_id: str = "") -> dict:
        """调用 Qwen3-VL（阿里云 MaaS）分析单帧"""
        import time as _t
        settings = get_settings()
        model = settings.qwen_vl_model
        data = frame.get("data", b"")
        if not data:
            return {"frame_index": frame["index"], "violation_type": "none", "confidence": 0.0}

        try:
            t0 = _t.time()
            img_b64 = base64.b64encode(data).decode("utf-8")

            # v5.0: 动态注入 Skill 知识
            skill_context = self._load_relevant_skills(
                query="",
                content_type="video",
                max_inject=3,
                content_id=content_id,
            )
            base_prompt = "分析这个视频帧是否包含违规内容（色情/暴力/政治/广告），JSON格式返回"
            full_prompt = f"{base_prompt}\n\n{skill_context}" if skill_context else base_prompt

            response = await self._vl_client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                        {"type": "text", "text": full_prompt},
                    ],
                }],
                response_format={"type": "json_object"},
                max_tokens=300,
            )
            # R22: 多级容错解析 VL 帧响应
            result = self._safe_json_parse(response.choices[0].message.content)
            if result is None:
                raise ValueError("VL frame analysis 响应非 JSON，无法解析")
            usage = response.usage
            self.trace_llm(model, usage.prompt_tokens if usage else 0,
                          usage.completion_tokens if usage else 100, (_t.time()-t0)*1000)
            return {
                "frame_index": frame["index"],
                "timestamp": frame["timestamp"],
                "violation_type": result.get("violation_type", "none"),
                "confidence": result.get("confidence", 0.0),
                "reason": result.get("reason", ""),
            }
        except Exception as e:
            logger.error(f"VL frame analysis failed: {e}")
            return {"frame_index": frame["index"], "violation_type": "none", "confidence": 0.0}

    def _calculate_video_risk(self, frame_results: list, audio_text: str, video_info: dict) -> tuple:
        """计算视频综合风险分 + 时间轴"""
        if not frame_results:
            return 0.0, []

        # 逐帧风险
        max_frame_risk = max(
            (f.get("confidence", 0.0) * (0.8 if f.get("violation_type") != "none" else 0.3))
            for f in frame_results
        )
        avg_frame_risk = sum(
            f.get("confidence", 0.0) for f in frame_results
        ) / max(len(frame_results), 1)

        # 风险时间轴
        risk_timeline = []
        for f in frame_results:
            if f.get("violation_type", "none") != "none" or f.get("confidence", 0) > 0.3:
                risk_timeline.append({
                    "timestamp": f.get("timestamp", 0),
                    "risk": f.get("confidence", 0),
                    "type": f.get("violation_type", "unknown"),
                })

        # 综合：帧分析 0.7 + 音频文字 0.3
        frame_score = max_frame_risk * 0.7 + avg_frame_risk * 0.3

        # 音频部分（如果 FunASR 不可用则跳过）
        audio_score = 0.0
        if audio_text and len(audio_text) > 3:
            # 简单启发式：包含敏感词则加分
            sensitive_patterns = ["广告", "微信", "加群", "赚钱", "免费", "中奖"]
            hits = sum(1 for p in sensitive_patterns if p in audio_text)
            audio_score = min(hits * 0.15, 0.5)

        overall = round(min(frame_score * 0.7 + audio_score * 0.3, 1.0), 4)

        return overall, risk_timeline
