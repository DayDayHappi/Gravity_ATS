"""录像参数矩阵离线单测：取值域、组合计数、命令拼装与非法值拒绝。

覆盖任务单 §5 离线验收：
- 全排列生成数量（bitrate/gop 各单值、vui 3 值）；
- 4k / 3k 仅 30fps（用户 2026-11-10 更正）、3k 仅 eis 2；
- 非法值（bitrate 越界 / gop 越界 / 3k+eis 0 / 未知 res / 缺键）抛 VideoParamsError；
- 命令字段顺序与每档组合数。
"""
import unittest

from ATS.drivers import video_commands as vc


class VideoParamsMatrixTest(unittest.TestCase):

    def test_total_combinations(self):
        """方案 A 默认取值域：6 档 × fps（4k/3k 仅 30）× eis（3k 仅 2）= 168。"""
        params = list(vc.iter_video_params())
        self.assertEqual(len(params), 168)

    def test_per_resolution_counts(self):
        params = list(vc.iter_video_params())
        counts = {}
        for p in params:
            counts[p.res] = counts.get(p.res, 0) + 1
        self.assertEqual(counts, {
            "4k": 18, "3k": 6, "1080p": 36,
            "sd1080p": 36, "720p": 36, "480p": 36,
        })

    def test_4k_and_3k_only_30fps(self):
        for p in vc.iter_video_params():
            if p.res in ("4k", "3k"):
                self.assertEqual(p.fps, 30, f"{p.res} 不应生成 60fps")

    def test_3k_only_eis_2(self):
        for p in vc.iter_video_params():
            if p.res == "3k":
                self.assertEqual(p.eis, 2)

    def test_other_resolutions_have_three_eis(self):
        for res in ("4k", "1080p", "sd1080p", "720p", "480p"):
            eis = {p.eis for p in vc.iter_video_params() if p.res == res}
            self.assertEqual(eis, {0, 1, 2}, f"{res} eis 取值应齐全")

    def test_all_combinations_unique(self):
        params = list(vc.iter_video_params())
        self.assertEqual(len({p.key for p in params}), len(params))

    def test_command_field_order_and_length(self):
        p = vc.resolve_video_params({
            "res": "4k", "fps": 30, "eis": 0, "codec": "h264",
            "bitrate": 8000000, "gop": 30, "vui": "709",
        })
        self.assertEqual(
            p.command,
            "cam_set video 4k 30 eis 0 h264 bitrate 8000000 gop 30 vui 709")
        # 任务单示例标注 63 字节（含行尾 CRLF）；命令本体 61 字节。
        self.assertEqual(len(p.command), 61)

    def test_longest_command_fits_chunked_write(self):
        """最长组合应远小于一次写入缓冲风险区间，由 32B 分片覆盖。"""
        longest = max((p.command for p in vc.iter_video_params()), key=len)
        self.assertLessEqual(len(longest), 70)
        self.assertGreater(len(longest), 32)

    def test_key_format(self):
        p = vc.resolve_video_params({
            "res": "4k", "fps": 30, "eis": 0, "codec": "h265",
            "bitrate": 8000000, "gop": 30, "vui": "709",
        })
        self.assertEqual(p.key, "4k-30-e0-h265-b8m-g30-v709")


class VideoParamsRejectTest(unittest.TestCase):

    def _valid(self, **kw):
        base = {"res": "1080p", "fps": 30, "eis": 2, "codec": "h265",
                "bitrate": 8000000, "gop": 30, "vui": "709"}
        base.update(kw)
        return base

    def test_bitrate_below_range(self):
        with self.assertRaises(vc.VideoParamsError):
            vc.resolve_video_params(self._valid(bitrate=49999))

    def test_bitrate_above_range(self):
        with self.assertRaises(vc.VideoParamsError):
            vc.resolve_video_params(self._valid(bitrate=25000001))

    def test_gop_out_of_range(self):
        with self.assertRaises(vc.VideoParamsError):
            vc.resolve_video_params(self._valid(gop=1001))

    def test_3k_with_eis_0(self):
        with self.assertRaises(vc.VideoParamsError):
            vc.resolve_video_params(self._valid(res="3k", eis=0))

    def test_3k_with_eis_1(self):
        with self.assertRaises(vc.VideoParamsError):
            vc.resolve_video_params(self._valid(res="3k", eis=1))

    def test_4k_with_60fps(self):
        with self.assertRaises(vc.VideoParamsError):
            vc.resolve_video_params(self._valid(res="4k", fps=60))

    def test_unknown_resolution(self):
        for bad in ("hd1080p", "3k_2", "sd1080p_0", "4K"):
            with self.assertRaises(vc.VideoParamsError):
                vc.resolve_video_params(self._valid(res=bad))

    def test_unknown_codec(self):
        with self.assertRaises(vc.VideoParamsError):
            vc.resolve_video_params(self._valid(codec="h266"))

    def test_unknown_vui(self):
        with self.assertRaises(vc.VideoParamsError):
            vc.resolve_video_params(self._valid(vui="2020"))

    def test_missing_key(self):
        params = self._valid()
        del params["gop"]
        with self.assertRaises(vc.VideoParamsError):
            vc.resolve_video_params(params)

    def test_bool_rejected_as_int(self):
        with self.assertRaises(vc.VideoParamsError):
            vc.resolve_video_params(self._valid(fps=True))

    def test_none_params(self):
        with self.assertRaises(vc.VideoParamsError):
            vc.resolve_video_params(None)

    def test_vui_int_normalized(self):
        """YAML 里 vui: 709 会解析为 int，应与 \"709\" 等价。"""
        p = vc.resolve_video_params(self._valid(vui=709))
        self.assertEqual(p.vui, "709")
        self.assertIn("vui 709", p.command)


class VideoSetErrorTest(unittest.TestCase):

    def test_busy_is_error(self):
        import re
        self.assertIsNotNone(re.search(vc.VIDEO_SET_ERROR, "cam_set video: device busy"))
        self.assertIsNotNone(re.search(vc.VIDEO_SET_ERROR, "BUSY"))

    def test_normal_output_not_error(self):
        import re
        self.assertIsNone(re.search(vc.VIDEO_SET_ERROR, "cam_set video 4k 30 ok"))


if __name__ == "__main__":
    unittest.main()
