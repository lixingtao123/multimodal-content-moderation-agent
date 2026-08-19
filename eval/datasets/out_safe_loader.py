"""
OutSafe-Bench 数据集加载器（R2·D1）

真实数据源：data/OutSafe-Bench/，9 类风险目录。
- 每类 `Chinese Text.xlsx`(200) + `English Text.xlsx`(200，第6类 800)
- pictures/ (100) / video/ (10) / audio/ (10)
- xlsx 单列 `prompt`，目录名即类别标签

实际总量：中文 1800 + 英文 2400 文本、900 图、90 视频、90 音频。

设计要点：
- 懒加载缓存（首次访问读盘，之后缓存）
- 模态内容默认存文件路径（轻量），下游按需 read_bytes()
- 类别 → 13 类枚举复用 violation_types.map_outsafe_category（D3 单一来源）
"""
import glob
import os
from dataclasses import dataclass, field
from typing import Optional

from agent_moderation.violation_types import map_outsafe_category

# 默认数据根目录（相对于项目根 /workspace/data/OutSafe-Bench）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_ROOT = os.path.join(_PROJECT_ROOT, "data", "OutSafe-Bench")

SUPPORTED_LANGS = ("zh", "en")
SUPPORTED_MODALITIES = ("text", "image", "video", "audio")

# modality → 实际目录名（image 在磁盘上叫 pictures）
MODALITY_DIR = {"image": "pictures", "video": "video", "audio": "audio"}


@dataclass
class OutSafeSample:
    """单条 OutSafe 样本（懒加载：模态内容为文件路径）"""
    id: str
    category: str  # OutSafe 目录名（如 "1Privacy_and_Property"）
    violation_type: str  # 13 类枚举
    modality: str  # text / image / video / audio
    language: str  # zh / en（文本类）或 ''（模态类）
    path: str  # 文件路径（文本类为 xlsx 来源标识；模态类为真实文件）
    content: str = ""  # 文本类：prompt 文本
    source: str = "out_safe"

    def read_bytes(self) -> bytes:
        """读取模态文件内容（图片/音频/视频），文本类返回空"""
        if self.modality == "text":
            return b""
        with open(self.path, "rb") as f:
            return f.read()


class OutSafeDatasetLoader:
    """OutSafe-Bench 数据集加载器（懒加载 + 缓存）"""

    def __init__(self, root_dir: Optional[str] = None):
        self.root_dir = root_dir or DEFAULT_ROOT
        self._cache: dict = {}

    # ------------------------------------------------------------
    # 元信息
    # ------------------------------------------------------------
    def categories(self) -> list[str]:
        """9 个类别目录名（数字前缀有序）"""
        if not os.path.isdir(self.root_dir):
            raise FileNotFoundError(f"OutSafe-Bench 目录不存在: {self.root_dir}")
        return sorted(
            d for d in os.listdir(self.root_dir)
            if os.path.isdir(os.path.join(self.root_dir, d))
            and not d.startswith(".")
        )

    def stats(self) -> dict:
        """数据集统计（每类各模态数量）"""
        return {
            "categories": len(self.categories()),
            "text_zh": len(self.load_text("zh")),
            "text_en": len(self.load_text("en")),
            "image": len(self.load_images()),
            "video": len(self.load_video()),
            "audio": len(self.load_audio()),
        }

    # ------------------------------------------------------------
    # 文本（xlsx）
    # ------------------------------------------------------------
    def load_text(self, language: str = "zh") -> list[OutSafeSample]:
        """加载全部类别的文本样本（懒加载缓存）"""
        if language not in SUPPORTED_LANGS:
            raise ValueError(f"language 必须是 {SUPPORTED_LANGS}")
        key = f"text_{language}"
        if key in self._cache:
            return self._cache[key]

        import openpyxl

        samples: list[OutSafeSample] = []
        for cat in self.categories():
            xlsx_name = "Chinese Text.xlsx" if language == "zh" else "English Text.xlsx"
            path = os.path.join(self.root_dir, cat, xlsx_name)
            if not os.path.exists(path):
                continue
            wb = openpyxl.load_workbook(path, read_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            # 跳过表头
            for idx, row in enumerate(rows[1:], 1):
                prompt = row[0]
                if not prompt or not str(prompt).strip():
                    continue
                samples.append(OutSafeSample(
                    id=f"{cat}:{language}:{idx}",
                    category=cat,
                    violation_type=map_outsafe_category(cat),
                    modality="text",
                    language=language,
                    path=path,
                    content=str(prompt).strip(),
                ))
            wb.close()
        self._cache[key] = samples
        return samples

    # ------------------------------------------------------------
    # 模态（图片/视频/音频）
    # ------------------------------------------------------------
    def _load_modal(self, modality: str) -> list[OutSafeSample]:
        key = modality
        if key in self._cache:
            return self._cache[key]
        if modality not in SUPPORTED_MODALITIES:
            raise ValueError(f"modality 必须是 {SUPPORTED_MODALITIES}")

        samples: list[OutSafeSample] = []
        dir_name = MODALITY_DIR[modality]
        for cat in self.categories():
            dir_path = os.path.join(self.root_dir, cat, dir_name)
            files = sorted(glob.glob(os.path.join(dir_path, "*")))
            for idx, f in enumerate(files, 1):
                if not os.path.isfile(f):
                    continue
                samples.append(OutSafeSample(
                    id=f"{cat}:{modality}:{idx}",
                    category=cat,
                    violation_type=map_outsafe_category(cat),
                    modality=modality,
                    language="",
                    path=f,
                ))
        self._cache[key] = samples
        return samples

    def load_images(self) -> list[OutSafeSample]:
        return self._load_modal("image")

    def load_video(self) -> list[OutSafeSample]:
        return self._load_modal("video")

    def load_audio(self) -> list[OutSafeSample]:
        return self._load_modal("audio")

    # ------------------------------------------------------------
    # 汇总
    # ------------------------------------------------------------
    def load_all(self) -> list[OutSafeSample]:
        """全部文本 + 模态样本"""
        return (self.load_text("zh") + self.load_text("en")
                + self.load_images() + self.load_video() + self.load_audio())
