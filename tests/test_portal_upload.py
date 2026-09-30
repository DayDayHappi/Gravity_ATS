"""ATS Portal 上传单元测试（ADR-017，unittest 风格）。

覆盖：三步协议（登记→PUT→finalize）、懒加载缺失文件跳过、token 缺失抛错、
文件名 URL 编码、sha256/size 计算。
"""
import json
import os
import tempfile
import unittest
from urllib.parse import quote

from ATS.application import portal_upload as pu
from ATS.application.portal_upload import PortalUploadError, _sha256_size


class PortalUploadTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig_request = pu._request
        # 保存并清除 token 环境变量，避免污染
        self._saved_env = {k: os.environ.get(k) for k in ("ATS_PORTAL_TOKEN", "ATS_PORTAL_TOKEN_FILE")}
        for k in self._saved_env:
            os.environ.pop(k, None)

    def tearDown(self):
        pu._request = self._orig_request
        for k, v in self._saved_env.items():
            if v is not None:
                os.environ[k] = v

    def _mock_request(self, calls):
        def fake(method, url, token, data=None, headers=None, timeout=60.0):
            calls.append((method, url, data))
            if method == "POST" and url.endswith("/runs"):
                return 201, json.dumps({"run_id": "x", "upload_state": "receiving"}).encode()
            if method == "PUT":
                return 200, json.dumps({"name": "x", "verified": True}).encode()
            if method == "POST" and url.endswith("/finalize"):
                return 200, json.dumps({"run_id": "x", "upload_state": "complete"}).encode()
            return 200, b"{}"
        pu._request = fake

    def test_three_step_upload_skips_missing_files(self):
        os.environ["ATS_PORTAL_TOKEN"] = "test-token"
        open(os.path.join(self.tmp, "run.log"), "w").write("hello log\n")
        open(os.path.join(self.tmp, "result.json"), "w").write('{"results": []}')

        calls = []
        self._mock_request(calls)
        cfg = {"enabled": True, "server": "http://127.0.0.1:8080", "timeout": 60,
               "artifacts": [
                   {"name": "run.log", "kind": "log"},
                   {"name": "serial.log", "kind": "log"},
                   {"name": "power_switch.log", "kind": "log"},
                   {"name": "recovery.log", "kind": "log"},
                   {"name": "result.json", "kind": "report"},
               ]}
        ok = pu.upload_run(cfg, "recovery_validation", self.tmp, self.tmp,
                           "2026-09-29T10:00:00+08:00", "2026-09-29T10:10:00+08:00",
                           "completed")
        self.assertTrue(ok)

        post_call = [c for c in calls if c[0] == "POST" and c[1].endswith("/runs")][0]
        manifest = json.loads(post_call[2].decode())
        names = sorted(a["name"] for a in manifest["artifacts"])
        self.assertEqual(names, ["result.json", "run.log"])   # 缺失的 serial/power_switch/recovery 跳过
        self.assertTrue(manifest["run_id"].startswith("ats-"))
        self.assertEqual(manifest["mode"]["id"], "recovery_validation")
        self.assertEqual(manifest["execution_state"], "completed")
        # kind 映射：result.json = report
        kinds = {a["name"]: a["kind"] for a in manifest["artifacts"]}
        self.assertEqual(kinds["result.json"], "report")
        # PUT 2 次 + finalize 1 次
        self.assertEqual(len([c for c in calls if c[0] == "PUT"]), 2)
        self.assertEqual(len([c for c in calls if c[0] == "POST" and c[1].endswith("/finalize")]), 1)

    def test_missing_token_raises(self):
        cfg = {"enabled": True, "token_file": os.path.join(self.tmp, "nonexistent"),
               "artifacts": [{"name": "run.log", "kind": "log"}]}
        open(os.path.join(self.tmp, "run.log"), "w").write("x")
        with self.assertRaises(PortalUploadError):
            pu.upload_run(cfg, "n", self.tmp, self.tmp, "a", "b", "completed")

    def test_filename_url_encoding(self):
        self.assertEqual(quote("a# b中文.log", safe=""),
                         "a%23%20b%E4%B8%AD%E6%96%87.log")

    def test_sha256_size(self):
        p = os.path.join(self.tmp, "f.txt")
        data = b"ATS upload demo\n"
        open(p, "wb").write(data)
        sha, size = _sha256_size(p)
        self.assertEqual(size, len(data))
        self.assertEqual(len(sha), 64)


class UploadLogTest(unittest.TestCase):
    """upload.log 懒加载：close_run_logs 后仍可写，close() 后关闭。"""

    def setUp(self):
        import ATS.core.logger as logger
        self.logger = logger
        self.tmp = tempfile.mkdtemp()
        logger.init_logger(self.tmp)

    def tearDown(self):
        self.logger.close()

    def test_upload_log_survives_close_run_logs(self):
        self.logger.info("normal run")
        self.logger.close_run_logs()
        self.logger.log_upload("upload step 1")
        self.logger.log_upload("upload step 2")
        p = os.path.join(self.logger.log_dir(), "upload.log")
        self.assertTrue(os.path.isfile(p))
        content = open(p, encoding="utf-8").read()
        self.assertIn("upload step 1", content)
        self.assertIn("upload step 2", content)
        # close() 后 _UPLOAD_FP 置 None
        self.logger.close()
        self.assertIsNone(self.logger._UPLOAD_FP)


if __name__ == "__main__":
    unittest.main()
