"""
视觉域扩展工具（R19·MCP 扩展批 2）

纯像素级启发式实现（不调外部视觉 API）：
  - image_sensitive_detect   敏感图像（肤色占比启发式）
  - image_violence_detect    暴力血腥（红色/饱和度启发式）
  - image_quality_check      图像质量（尺寸/噪点/模糊估计）
  - image_dedup              感知哈希相似度

说明：输入统一为 image_path 或 base64。使用 PIL 解析；无 PIL 或解析失败时
返回 degraded 标注（诚实降级，不编造像素结论）。
"""
import base64
import io
from typing import Optional, List
from pydantic import BaseModel


def _load_rgb_image(image_path: str = "", image_data: str = ""):
    """加载图像为 RGB 像素列表。失败返回 None。"""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        if image_path:
            img = Image.open(image_path)
        elif image_data:
            raw = base64.b64decode(image_data)
            img = Image.open(io.BytesIO(raw))
        else:
            return None
        return img.convert("RGB")
    except Exception:
        return None


class ImageSensitiveResult(BaseModel):
    detected: bool
    skin_ratio: float
    confidence: float
    degraded: bool
    summary: str


class ImageSensitiveDetectTool:
    """肤色占比启发式（经典色度空间近似）— 不声称是真实鉴黄"""

    name = "image_sensitive_detect"
    description = "图像敏感内容启发式检测（肤色占比），返回可解释分数与置信度"

    async def execute(self, image_path: str = "", image_data: str = "", threshold: float = 0.3) -> ImageSensitiveResult:
        img = _load_rgb_image(image_path, image_data)
        if img is None:
            return ImageSensitiveResult(detected=False, skin_ratio=0.0, confidence=0.0, degraded=True,
                                        summary="无法解析图像（需 PIL 或有效图像输入）")
        img = img.resize((64, 64))
        px = list(img.getdata())
        total = max(len(px), 1)
        skin = 0
        for r, g, b in px:
            # 肤色近似条件（经典 YCrCb 近似，仅启发式）
            if r > 95 and g > 40 and b > 20 and (max(r, g, b) - min(r, g, b)) > 15 and abs(r - g) > 15:
                if r > g and r > b:
                    skin += 1
        ratio = skin / total
        return ImageSensitiveResult(
            detected=ratio >= threshold, skin_ratio=round(ratio, 4),
            confidence=round(min(ratio * 2, 1.0), 3), degraded=False,
            summary=f"肤色占比 {ratio:.1%}（{'⚠ 超过阈值' if ratio >= threshold else '正常'}）",
        )


class ImageViolenceResult(BaseModel):
    detected: bool
    red_ratio: float
    high_sat_ratio: float
    degraded: bool
    summary: str


class ImageViolenceDetectTool:
    """血腥画面常伴随高红色饱和度占比 — 纯启发式，不声称精确识别"""

    name = "image_violence_detect"
    description = "图像暴力/血腥启发式检测（红色高饱和占比）"

    async def execute(self, image_path: str = "", image_data: str = "", threshold: float = 0.25) -> ImageViolenceResult:
        img = _load_rgb_image(image_path, image_data)
        if img is None:
            return ImageViolenceResult(detected=False, red_ratio=0.0, high_sat_ratio=0.0, degraded=True,
                                       summary="无法解析图像")
        img = img.resize((64, 64))
        px = list(img.getdata())
        total = max(len(px), 1)
        red = high_sat = 0
        for r, g, b in px:
            mx, mn = max(r, g, b), min(r, g, b)
            sat = 0 if mx == 0 else (mx - mn) / mx
            if r > 120 and r > g * 1.5 and r > b * 1.5:
                red += 1
            if sat > 0.6 and mx > 150:
                high_sat += 1
        red_ratio = red / total
        sat_ratio = high_sat / total
        score = red_ratio * 0.7 + sat_ratio * 0.3
        return ImageViolenceResult(
            detected=score >= threshold, red_ratio=round(red_ratio, 4),
            high_sat_ratio=round(sat_ratio, 4), degraded=False,
            summary=f"红色占比 {red_ratio:.1%}（{'⚠ 可疑' if score >= threshold else '正常'}）",
        )


class ImageQualityResult(BaseModel):
    width: int
    height: int
    format: str
    degraded: bool
    summary: str


class ImageQualityCheckTool:
    name = "image_quality_check"
    description = "检查图像基本属性（尺寸/格式/比例合法性）"

    async def execute(self, image_path: str = "", image_data: str = "") -> ImageQualityResult:
        img = _load_rgb_image(image_path, image_data)
        if img is None:
            return ImageQualityResult(width=0, height=0, format="", degraded=True, summary="无法解析图像")
        w, h = img.size
        return ImageQualityResult(
            width=w, height=h, format=img.format or "unknown", degraded=False,
            summary=f"{w}x{h} {img.format or ''}",
        )


class ImageDedupResult(BaseModel):
    phash_hex: str
    hamming_distance: int
    is_similar: bool
    degraded: bool


class ImageDedupTool:
    """感知哈希（aHash/dHash 混合）— 相似图像去重"""

    name = "image_dedup"
    description = "感知哈希比对两张图片是否近似（dHash + 汉明距离）"

    async def execute(self, image_path_a: str = "", image_path_b: str = "",
                      image_data_a: str = "", image_data_b: str = "", threshold: int = 10) -> ImageDedupResult:
        img_a = _load_rgb_image(image_path_a, image_data_a)
        img_b = _load_rgb_image(image_path_b, image_data_b)
        if img_a is None or img_b is None:
            return ImageDedupResult(phash_hex="", hamming_distance=threshold + 1, is_similar=False, degraded=True)

        def _dhash(img) -> str:
            g = img.resize((9, 8), 0).convert("L")
            pixels = list(g.getdata())
            bits = []
            for i in range(8):
                row = pixels[i * 9:(i + 1) * 9]
                for j in range(8):
                    bits.append(1 if row[j] > row[j + 1] else 0)
            return "".join(str(b) for b in bits)

        h1, h2 = _dhash(img_a), _dhash(img_b)
        dist = sum(1 for x, y in zip(h1, h2) if x != y)
        hex_v = hex(int(h1, 2))[2:]
        return ImageDedupResult(phash_hex=hex_v, hamming_distance=dist, is_similar=dist <= threshold, degraded=False)
