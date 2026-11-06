"""photo heif 下载与校验离线单测（BUG/Level 1：固件产出 .heic，下载过滤 + 校验分支）。

覆盖：
- `_list_jpgs` 扩展名过滤纳入 .jpg/.heic/.heif（大小写不敏感），不再漏 heif 产物。
- `_verify_image` 按产物类型分支：.heic/.heif 走 HEIF（ftyp）盒头校验；.jpg 保持 JPEG 魔数。
- 反例：.heic 内容不是 HEIF（无 ftyp）→ 校验失败，不被误判为 JPEG 也不被放过。
- 回归：.jpg 正常走 JPEG 魔数校验。

注：BUG-008 起校验入口为 `_verify_image(local, kind, min_kb_by_kind)`，
阈值分档用例见 `tests/test_photo_size_thresholds.py`。
"""
import os
import tempfile
import unittest

from ATS.modules.photo import (
    _KIND_HEIF,
    _KIND_MAIN,
    _KIND_THUMBNAIL,
    PhotoModule,
    _classify_image,
)


class _FakeFtp:
    def __init__(self, entries):
        # entries: [(name, size), ...] 或旧式 [name, ...]（size 记 0）
        self._entries = [(e, 0) if isinstance(e, str) else e for e in entries]

    def list_files(self, path):
        return [n for n, _sz in self._entries]

    def list_files_detail(self, path):
        return list(self._entries)


def _write(path, data):
    with open(path, "wb") as f:
        f.write(data)


def _heif_bytes():
    # ISO BMFF 顶盒：4 字节 box size(=12) + "ftyp" + 4 字节 brand
    return (12).to_bytes(4, "big") + b"ftypheic"


class PhotoHeifTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._module = PhotoModule({})
        # 本文件只测「格式头分支」，故阈值置 0 隔离大小判据；
        # 分档阈值的用例见 tests/test_photo_size_thresholds.py。
        self._min_kb = {_KIND_MAIN: 0, _KIND_THUMBNAIL: 0, _KIND_HEIF: 0}

    def _path(self, name):
        return os.path.join(self._tmp, name)

    def _verify(self, path):
        return self._module._verify_image(
            path, _classify_image(os.path.basename(path)), self._min_kb)

    def test_list_jpgs_includes_heic_heif(self):
        ftp = _FakeFtp([("a.jpg", 111), ("b.HEIC", 222), ("c.heif", 333),
                        ("d.png", 444), ("e.txt", 555)])
        # 返回值带 size，供 download(size_hint=...) 复用，省重复 LIST
        self.assertEqual(self._module._list_jpgs(ftp, "/x"),
                         [("a.jpg", 111), ("b.HEIC", 222), ("c.heif", 333)])

    def test_verify_heic_follows_heif_branch(self):
        p = self._path("img.heic")
        _write(p, _heif_bytes())
        ok, msg = self._verify(p)
        self.assertTrue(ok, msg)
        self.assertIn("HEIF", msg)

    def test_verify_heif_extension_also_branches(self):
        p = self._path("img.heif")
        _write(p, _heif_bytes())
        ok, msg = self._verify(p)
        self.assertTrue(ok, msg)
        self.assertIn("HEIF", msg)

    def test_verify_heic_not_heif_fails(self):
        # .heic 内容不是 HEIF（无 ftyp）→ 必须失败，不能误判 JPEG 也不能放过
        p = self._path("bad.heic")
        _write(p, b"\xff\xd8\xff" + b"\x00" * 100)
        ok, msg = self._verify(p)
        self.assertFalse(ok)
        self.assertIn("HEIF", msg)

    def test_verify_jpg_still_jpeg_branch(self):
        p = self._path("img.jpg")
        _write(p, b"\xff\xd8\xff" + b"\x00" * 100)
        ok, msg = self._verify(p)
        self.assertTrue(ok, msg)
        self.assertIn("JPEG", msg)

    def test_verify_bad_jpg_fails(self):
        p = self._path("bad.jpg")
        _write(p, b"\x00" * 100)
        ok, msg = self._verify(p)
        self.assertFalse(ok)
        self.assertIn("JPEG", msg)


if __name__ == "__main__":
    unittest.main()
