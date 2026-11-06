"""photo 大小阈值按产物类型分档的离线单测（BUG-008，Level 1）。

固件缩略图 `Image_<ts>_thum.jpg`（480×360，亮场景约 9KB）与 HEIC（6.9–83KB）
不适用主图的 `photo_min_size_kb: 10`。本测试锁定：

- `_classify_image` 分类：`*_thum.jpg` → thumbnail；`.heic/.heif` → heif；其余 → main。
- `_min_kb_by_kind` 缺省值：主图 10 / 缩略图 4 / HEIC 4（老配置不写新增键也安全）。
- 阈值语义：缩略图 9KB 通过、截断到 3KB 失败；主图 12KB 通过、9KB 失败；
  HEIC 7KB 且 ftyp 合法通过、无 ftyp 失败。
- 格式头校验仍在：缩略图头损坏即使大小达标也失败。
"""
import os
import tempfile
import unittest

from ATS.modules.photo import (
    _KIND_HEIF,
    _KIND_MAIN,
    _KIND_THUMBNAIL,
    _classify_image,
    _min_kb_by_kind,
    PhotoModule,
)

_JPEG_HEAD = b"\xff\xd8\xff\xe0\x00\x10JFIF"
_HEIF_HEAD = (12).to_bytes(4, "big") + b"ftypheic"


def _payload(head, size):
    """构造指定字节数的文件内容（头部为格式魔数）。"""
    return head + b"\x00" * (size - len(head))


def _write(path, data):
    with open(path, "wb") as f:
        f.write(data)


class PhotoKindClassifyTest(unittest.TestCase):

    def test_thumbnail_classification(self):
        self.assertEqual(_classify_image("Image_20260101_000100_0095_thum.jpg"),
                         _KIND_THUMBNAIL)
        # 后缀大小写不敏感
        self.assertEqual(_classify_image("Image_20260101_000100_0095_THUM.JPG"),
                         _KIND_THUMBNAIL)

    def test_heif_classification(self):
        self.assertEqual(_classify_image("Image_20260101_000100_0095_0.heic"), _KIND_HEIF)
        self.assertEqual(_classify_image("Image_20260101_000100_0095_0.heif"), _KIND_HEIF)

    def test_main_classification(self):
        self.assertEqual(_classify_image("Image_20260101_000100_0095_0.jpg"), _KIND_MAIN)
        # 名字里含 thum 但不是后缀 → 仍算主图
        self.assertEqual(_classify_image("thum_0001.jpg"), _KIND_MAIN)

    def test_default_thresholds(self):
        # 老配置（不写新增两键）→ 使用缺省值
        self.assertEqual(_min_kb_by_kind({}),
                         {_KIND_MAIN: 10, _KIND_THUMBNAIL: 4, _KIND_HEIF: 4})

    def test_config_overrides_thresholds(self):
        cfg = {"photo_min_size_kb": 12,
               "photo_thumb_min_size_kb": 5,
               "photo_heif_min_size_kb": 6}
        self.assertEqual(_min_kb_by_kind(cfg),
                         {_KIND_MAIN: 12, _KIND_THUMBNAIL: 5, _KIND_HEIF: 6})


class PhotoSizeThresholdTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._module = PhotoModule({})
        self._min_kb = _min_kb_by_kind({})

    def _verify(self, name, data):
        path = os.path.join(self._tmp, name)
        _write(path, data)
        return self._module._verify_image(
            path, _classify_image(name), self._min_kb)

    def test_thumbnail_9kb_passes(self):
        # 真实样本：亮场景缩略图约 9KB（480×360）
        ok, msg = self._verify("Image_20260101_000100_0095_thum.jpg",
                               _payload(_JPEG_HEAD, 9 * 1024))
        self.assertTrue(ok, msg)
        self.assertIn("缩略图", msg)

    def test_thumbnail_truncated_3kb_fails(self):
        ok, msg = self._verify("Image_20260101_000100_0095_thum.jpg",
                               _payload(_JPEG_HEAD, 3 * 1024))
        self.assertFalse(ok)
        self.assertIn("文件过小", msg)
        self.assertIn("缩略图", msg)

    def test_thumbnail_bad_header_fails(self):
        # 大小达标但头不是 JPEG → 仍须失败（不得只跳大小校验）
        ok, msg = self._verify("Image_20260101_000100_0095_thum.jpg",
                               _payload(b"\x00" * 8, 9 * 1024))
        self.assertFalse(ok)
        self.assertIn("JPEG 头校验失败", msg)

    def test_main_12kb_passes(self):
        ok, msg = self._verify("Image_20260101_000100_0095_0.jpg",
                               _payload(_JPEG_HEAD, 12 * 1024))
        self.assertTrue(ok, msg)
        self.assertIn("主图", msg)

    def test_main_9kb_still_fails(self):
        # 证明未放宽主图阈值（缩略图档位只对 thumbnail 生效）
        ok, msg = self._verify("Image_20260101_000100_0095_0.jpg",
                               _payload(_JPEG_HEAD, 9 * 1024))
        self.assertFalse(ok)
        self.assertIn("文件过小", msg)
        self.assertIn("主图", msg)

    def test_heic_7kb_with_ftyp_passes(self):
        ok, msg = self._verify("Image_20260101_000100_0095_0.heic",
                               _payload(_HEIF_HEAD, 7 * 1024))
        self.assertTrue(ok, msg)
        self.assertIn("HEIF", msg)

    def test_heic_8kb_without_ftyp_fails(self):
        ok, msg = self._verify("Image_20260101_000100_0095_0.heic",
                               _payload(b"\x00" * 8, 8 * 1024))
        self.assertFalse(ok)
        self.assertIn("HEIF 头校验失败", msg)


if __name__ == "__main__":
    unittest.main()
