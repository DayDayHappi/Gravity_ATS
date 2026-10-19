"""photo heif 下载与校验离线单测（BUG/Level 1：固件产出 .heic，下载过滤 + 校验分支）。

覆盖：
- `_list_jpgs` 扩展名过滤纳入 .jpg/.heic/.heif（大小写不敏感），不再漏 heif 产物。
- `_verify_jpeg` 按扩展名分支：.heic/.heif 走 HEIF（ftyp）盒头校验；.jpg 保持 JPEG 魔数。
- 反例：.heic 内容不是 HEIF（无 ftyp）→ 校验失败，不被误判为 JPEG 也不被放过。
- 回归：.jpg 正常走 JPEG 魔数校验。
"""
import os
import tempfile
import unittest

from ATS.modules.photo import PhotoModule


class _FakeFtp:
    def __init__(self, entries):
        self._entries = entries

    def list_files(self, path):
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

    def _path(self, name):
        return os.path.join(self._tmp, name)

    def test_list_jpgs_includes_heic_heif(self):
        ftp = _FakeFtp(["a.jpg", "b.HEIC", "c.heif", "d.png", "e.txt"])
        self.assertEqual(self._module._list_jpgs(ftp, "/x"),
                         ["a.jpg", "b.HEIC", "c.heif"])

    def test_verify_heic_follows_heif_branch(self):
        p = self._path("img.heic")
        _write(p, _heif_bytes())
        ok, msg = self._module._verify_jpeg(p, 0)
        self.assertTrue(ok, msg)
        self.assertIn("HEIF", msg)

    def test_verify_heif_extension_also_branches(self):
        p = self._path("img.heif")
        _write(p, _heif_bytes())
        ok, msg = self._module._verify_jpeg(p, 0)
        self.assertTrue(ok, msg)
        self.assertIn("HEIF", msg)

    def test_verify_heic_not_heif_fails(self):
        # .heic 内容不是 HEIF（无 ftyp）→ 必须失败，不能误判 JPEG 也不能放过
        p = self._path("bad.heic")
        _write(p, b"\xff\xd8\xff" + b"\x00" * 100)
        ok, msg = self._module._verify_jpeg(p, 0)
        self.assertFalse(ok)
        self.assertIn("HEIF", msg)

    def test_verify_jpg_still_jpeg_branch(self):
        p = self._path("img.jpg")
        _write(p, b"\xff\xd8\xff" + b"\x00" * 100)
        ok, msg = self._module._verify_jpeg(p, 0)
        self.assertTrue(ok, msg)
        self.assertIn("JPEG", msg)

    def test_verify_bad_jpg_fails(self):
        p = self._path("bad.jpg")
        _write(p, b"\x00" * 100)
        ok, msg = self._module._verify_jpeg(p, 0)
        self.assertFalse(ok)
        self.assertIn("JPEG", msg)


if __name__ == "__main__":
    unittest.main()
