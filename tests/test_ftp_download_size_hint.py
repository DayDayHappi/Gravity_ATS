"""FtpClient.download(size_hint) 离线单测（Level 1：省掉每文件重复 LIST 父目录）。

覆盖：
- `size_hint` 合法 → download() 不再调用 size()（mock 计数）。
- `size_hint=None` → 仍调用 size()（向后兼容，现有调用方零影响）。
- `size_hint=0` / 负数 → 回退 size()。
- 保底复核：传输结束但本地 < hint 时，以服务端真实 size 再判一次（不误判续传）。
- `_list_jpgs` 返回 [(name, size), ...] 且过滤仍只含 .jpg/.heic/.heif。
"""
import os
import tempfile
import unittest
from unittest import mock

from ATS.drivers.ftp_client import FtpClient
from ATS.modules.photo import PhotoModule


class _FakeFtpConn:
    """替身：模拟 _ftp 的 retrbinary，按 content 长度写本地文件。"""

    def __init__(self, content):
        self._content = content

    def retrbinary(self, cmd, callback, rest=None):
        data = self._content[rest or 0:]
        callback(data)


class DownloadSizeHintTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._content = b"x" * 5000
        self._client = FtpClient("127.0.0.1")

    def _run_download(self, size_hint, remote_size=5000, content=None):
        """执行 download()，返回 (ok, size 调用次数, size 返回值列表)。"""
        content = content if content is not None else self._content
        calls = []

        def fake_size(_remote):
            calls.append(_remote)
            return remote_size

        # 替换 connect（避免真连网）与 size（计数）
        with mock.patch.object(self._client, "connect", lambda: None), \
             mock.patch.object(self._client, "size", fake_size):
            self._client._ftp = _FakeFtpConn(content)
            local = os.path.join(self._tmp, "out.bin")
            ok = self._client.download("dir/file.bin", local,
                                       timeout=5, retries=1, size_hint=size_hint)
        return ok, len(calls)

    def test_size_hint_skips_size(self):
        ok, n = self._run_download(size_hint=5000)
        self.assertTrue(ok)
        self.assertEqual(n, 0, "给了合法 size_hint 不应再 LIST 父目录")

    def test_none_hint_still_calls_size(self):
        ok, n = self._run_download(size_hint=None)
        self.assertTrue(ok)
        self.assertEqual(n, 1, "size_hint=None 必须回退到 size()")

    def test_zero_hint_falls_back(self):
        ok, n = self._run_download(size_hint=0)
        self.assertTrue(ok)
        self.assertEqual(n, 1, "size_hint=0 视为缺失，应回退 size()")

    def test_negative_hint_falls_back(self):
        ok, n = self._run_download(size_hint=-1)
        self.assertTrue(ok)
        self.assertEqual(n, 1, "负数 size_hint 应回退 size()")

    def test_stale_hint_recheck_prevents_false_incomplete(self):
        # hint 说 5000，但实际只传了 3000；保底复核发现服务端真实大小就是 3000
        # → 应判成功（而非误判「下载提前结束」并浪费续传）。
        ok, n = self._run_download(size_hint=5000, remote_size=3000,
                                   content=b"y" * 3000)
        self.assertTrue(ok)
        self.assertEqual(n, 1, "hint 不足时应复核一次真实 size")

    def test_genuine_truncation_still_fails(self):
        # 服务端真实大小 5000，只传了 3000 且 retries=1 → 必须判失败
        ok, n = self._run_download(size_hint=5000, remote_size=5000,
                                   content=b"y" * 3000)
        self.assertFalse(ok, "真截断不得因 size_hint 被放过")

    def test_hint_larger_than_real_file_succeeds(self):
        # hint 偏大（如目录 LIST 时文件未写完）但复核后本地已够真实大小 → 成功
        ok, _n = self._run_download(size_hint=9000, remote_size=5000)
        self.assertTrue(ok)


class _FakeFtp:
    def __init__(self, entries):
        self._entries = entries

    def list_files_detail(self, path):
        return list(self._entries)


class ListJpgsReturnsSizeTest(unittest.TestCase):

    def setUp(self):
        self._module = PhotoModule({})

    def test_returns_name_size_tuples(self):
        ftp = _FakeFtp([("a.jpg", 100), ("b.heic", 200), ("c.png", 300)])
        self.assertEqual(self._module._list_jpgs(ftp, "/x"),
                         [("a.jpg", 100), ("b.heic", 200)])

    def test_exception_returns_empty(self):
        class _Boom:
            def list_files_detail(self, path):
                raise OSError("ftp down")
        self.assertEqual(self._module._list_jpgs(_Boom(), "/x"), [])


if __name__ == "__main__":
    unittest.main()
