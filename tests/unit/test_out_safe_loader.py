"""
单元测试 — OutSafeDatasetLoader（R2·D1）
真实数据断言基于扫描事实：中文 1800 + 英文 2400、图 900、视频 90、音频 90。
"""
import pytest

from eval.datasets.out_safe_loader import OutSafeDatasetLoader, OutSafeSample

# 每类期望数量（扫描确认）
TEXT_ZH_PER_CAT = 200
TEXT_EN_PER_CAT = 200  # 第 6 类英文 800，故用"至少"
IMG_PER_CAT = 100
VID_PER_CAT = 10
AUD_PER_CAT = 10


@pytest.fixture(scope="module")
def loader():
    return OutSafeDatasetLoader()


class TestOutSafeLoader:
    def test_categories_9(self, loader):
        assert len(loader.categories()) == 9

    def test_text_zh_total(self, loader):
        """中文文本 1800 条"""
        samples = loader.load_text("zh")
        assert len(samples) == 1800

    def test_text_en_total(self, loader):
        """英文文本 2400 条（第 6 类 800）"""
        samples = loader.load_text("en")
        assert len(samples) == 2400

    def test_each_cat_zh_200(self, loader):
        """每类中文 200 条"""
        from collections import Counter
        counts = Counter(s.category for s in loader.load_text("zh"))
        assert all(c == TEXT_ZH_PER_CAT for c in counts.values()), counts

    def test_images_900(self, loader):
        assert len(loader.load_images()) == 900

    def test_video_90(self, loader):
        assert len(loader.load_video()) == 90

    def test_audio_90(self, loader):
        assert len(loader.load_audio()) == 90

    def test_each_cat_modal_counts(self, loader):
        """每类图片 100 / 视频 10 / 音频 10"""
        from collections import Counter
        assert all(c == IMG_PER_CAT for c in Counter(s.category for s in loader.load_images()).values())
        assert all(c == VID_PER_CAT for c in Counter(s.category for s in loader.load_video()).values())
        assert all(c == AUD_PER_CAT for c in Counter(s.category for s in loader.load_audio()).values())

    def test_violation_type_mapping(self, loader):
        """类别 → 13 类枚举映射正确"""
        first_of_cat = {}
        for s in loader.load_text("zh"):
            if s.category not in first_of_cat:
                first_of_cat[s.category] = s.violation_type
        assert first_of_cat["1Privacy_and_Property"] == "privacy"
        assert first_of_cat["5Violence_and_Hatred"] == "violence"
        assert first_of_cat["7Polity_Sensibility"] == "politics"
        assert first_of_cat["9Copyright_and_Intellectual_Property"] == "copyright"

    def test_sample_structure(self, loader):
        """样本结构：source / modality / id"""
        s = loader.load_text("zh")[0]
        assert isinstance(s, OutSafeSample)
        assert s.source == "out_safe"
        assert s.modality == "text"
        assert ":" in s.id

    def test_lazy_cache_same_object(self, loader):
        """懒加载缓存：重复访问返回同一列表对象"""
        assert loader.load_text("zh") is loader.load_text("zh")
        assert loader.load_images() is loader.load_images()

    def test_read_bytes_modal(self, loader):
        """模态文件可读 bytes（非空）"""
        img = loader.load_images()[0]
        data = img.read_bytes()
        assert isinstance(data, bytes) and len(data) > 0

    def test_text_read_bytes_empty(self, loader):
        """文本样本 read_bytes 返回空"""
        assert loader.load_text("zh")[0].read_bytes() == b""

    def test_invalid_language(self, loader):
        with pytest.raises(ValueError):
            loader.load_text("fr")

    def test_stats(self, loader):
        stats = loader.stats()
        assert stats["text_zh"] == 1800
        assert stats["text_en"] == 2400
        assert stats["image"] == 900
        assert stats["video"] == 90
        assert stats["audio"] == 90
