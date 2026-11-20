"""拍照参数结构化离线单测（ADR-018）：枚举校验、命令拼装、key 命名、硬切拒绝。

覆盖任务单 §8 离线验收：
- 合法 mode/size/num → 命令字段顺序正确、size 关键字存在性正确；
- key 命名无空格（single-12m / hdr-n0 / auto）；
- 非法 mode/size、缺 mode、num 非整数/负数、旧字符串元素 → PhotoParamsError。
"""
import unittest

from ATS.drivers import photo_commands as pc


class PhotoParamsCommandTest(unittest.TestCase):

    def test_auto_no_size_no_num(self):
        p = pc.resolve_photo_params({"mode": "auto"})
        self.assertEqual(p.command, "cam_set photo auto")
        self.assertEqual(p.key, "auto")

    def test_single_default_no_size(self):
        """单拍不带 size：仅默认 12m/30（固件隐式）。"""
        p = pc.resolve_photo_params({"mode": "single"})
        self.assertEqual(p.command, "cam_set photo single")
        self.assertEqual(p.key, "single")

    def test_single_with_size_includes_keyword(self):
        """关键修复：size 必须带 size 关键字，不能是裸 token（ADR-018）。"""
        p = pc.resolve_photo_params({"mode": "single", "size": "1080p"})
        self.assertEqual(p.command, "cam_set photo single size 1080p")
        self.assertEqual(p.key, "single-1080p")

    def test_single_size_12m(self):
        p = pc.resolve_photo_params({"mode": "single", "size": "12m"})
        self.assertEqual(p.command, "cam_set photo single size 12m")
        self.assertEqual(p.key, "single-12m")

    def test_hdr_with_num(self):
        p = pc.resolve_photo_params({"mode": "hdr", "num": 2})
        self.assertEqual(p.command, "cam_set photo hdr 2")
        self.assertEqual(p.key, "hdr-n2")

    def test_single_with_size_and_num(self):
        """size 在 num 之前（固件语法 [size <SIZE>] [num]）。"""
        p = pc.resolve_photo_params({"mode": "single", "size": "8m", "num": 30})
        self.assertEqual(p.command, "cam_set photo single size 8m 30")
        self.assertEqual(p.key, "single-8m-n30")

    def test_key_has_no_spaces(self):
        for entry in ({"mode": "auto"}, {"mode": "single", "size": "480p"},
                      {"mode": "hdr", "num": 0}, {"mode": "single", "size": "8m", "num": 60}):
            self.assertNotIn(" ", pc.resolve_photo_params(entry).key)


class PhotoParamsRejectTest(unittest.TestCase):

    def test_string_entry_rejected(self):
        """硬切：旧字符串形式（单字符串元素）一律拒绝，不做双读。"""
        for bad in ("auto", "single 12m", "hdr 0", ""):
            with self.assertRaises(pc.PhotoParamsError):
                pc.resolve_photo_params(bad)

    def test_none_entry_rejected(self):
        with self.assertRaises(pc.PhotoParamsError):
            pc.resolve_photo_params(None)

    def test_missing_mode(self):
        with self.assertRaises(pc.PhotoParamsError):
            pc.resolve_photo_params({"size": "12m"})

    def test_unknown_mode(self):
        for bad in ("raw", "burst", "AUTO", ""):
            with self.assertRaises(pc.PhotoParamsError):
                pc.resolve_photo_params({"mode": bad})

    def test_unknown_size(self):
        for bad in ("16m", "2k", "12M", ""):
            with self.assertRaises(pc.PhotoParamsError):
                pc.resolve_photo_params({"mode": "single", "size": bad})

    def test_num_not_int(self):
        for bad in ("0", 1.5, [0], {"n": 0}):
            with self.assertRaises(pc.PhotoParamsError):
                pc.resolve_photo_params({"mode": "hdr", "num": bad})

    def test_num_bool_rejected(self):
        with self.assertRaises(pc.PhotoParamsError):
            pc.resolve_photo_params({"mode": "hdr", "num": True})

    def test_num_negative_rejected(self):
        with self.assertRaises(pc.PhotoParamsError):
            pc.resolve_photo_params({"mode": "hdr", "num": -1})


if __name__ == "__main__":
    unittest.main()
