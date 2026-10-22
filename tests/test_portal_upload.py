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

# 内嵌自签名测试证书（仅测试用，CN=ats-portal-test，与任何生产证书无关）。
# 用于 _build_ssl_context 的 cafile 用例，避免测试运行时依赖 openssl/外部文件。
_SELF_SIGNED_CERT_PEM = """-----BEGIN CERTIFICATE-----
MIIDFTCCAf2gAwIBAgIUYpMRSODTyMZoYrPJIAFytIwhgucwDQYJKoZIhvcNAQEL
BQAwGjEYMBYGA1UEAwwPYXRzLXBvcnRhbC10ZXN0MB4XDTI2MTAxOTA1MTUzN1oX
DTI2MTExODA1MTUzN1owGjEYMBYGA1UEAwwPYXRzLXBvcnRhbC10ZXN0MIIBIjAN
BgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA49jHSm6qPPxUHhWsW8ddPTzWSQjp
WkRg4xV8X94OLmg0N3KLe3/4826es147DKYlIc3aaopdbSOQ+SWtGjb3MrofEe8I
RcT+MGDFdXKTHQP3mD/tbg7sZiXsm4yqzEqgfgAGKas9eYANleiJ3l/6H+5F33RA
+lWY9+XaW5E0y/pX9tlLk0JwOKW4Kpu2oifEa0zFwtBUVKp3mrej4hMP68G0iAg5
Ui19uD7JQcteFKt1w0fJmi8ONW6vEXVIvy3SQW/mUthxD2Rs7vpa8fAsoSrRyWbI
XzAimFrs0mSr0RfGzNpLtvywZjUfM0BHeb5eSGI2iYnENSVyOC85mqgkswIDAQAB
o1MwUTAdBgNVHQ4EFgQU3N/Z8Z0pFPbmpFVyQySelzhEfW8wHwYDVR0jBBgwFoAU
3N/Z8Z0pFPbmpFVyQySelzhEfW8wDwYDVR0TAQH/BAUwAwEB/zANBgkqhkiG9w0B
AQsFAAOCAQEAI5JJjxv9dDiIaGC1hXf5k2o3KA/oiOUOXZgrRxWMekhMrcCRdVd3
91CGmns8rqX7rOnGQDnW/jtLqzl4L1ikYloj/Aqlg5sWjyh5gSubu37ZGameJuss
/4r+h1lEEyfu7L5/Z6VD75uVnmytc1kl97Hxb612U4A2+91fwJIz0rGYIwBgRlVg
qdwdvx700lc23aQ6x4ChFPdyplkOBr8kS1Ph8zgtFB3kYi6VIbWeP3JKvayiOfT6
1XF4+autdCGzTR0KxouGo1FtAfl0keKStHLr9Cx2kdXhjgx72taXnhenAO86pkOe
f0/6qNuliIuSrBAIfA3vTxfNnMSIj3OKsQ==
-----END CERTIFICATE-----
"""


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
        def fake(method, url, token, data=None, headers=None, timeout=60.0, ssl_ctx=None):
            calls.append((method, url, data, ssl_ctx))
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


class SslContextTest(unittest.TestCase):
    """方案 2-b：upload.ca_cert 构建 SSL context（空→None；有→cafile 断言）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_build_ssl_context_empty_returns_none(self):
        self.assertIsNone(pu._build_ssl_context({}))
        self.assertIsNone(pu._build_ssl_context({"ca_cert": ""}))
        self.assertIsNone(pu._build_ssl_context({"ca_cert": "   "}))

    def test_build_ssl_context_with_cert(self):
        cert_path = os.path.join(self.tmp, "portal.crt")
        with open(cert_path, "w", encoding="utf-8") as f:
            f.write(_SELF_SIGNED_CERT_PEM)
        ctx = pu._build_ssl_context({"ca_cert": cert_path})
        self.assertIsNotNone(ctx)
        # Python 3.12 的 SSLContext 无 .cafile 属性，用 get_ca_certs 断言证书已加载
        self.assertGreater(len(ctx.get_ca_certs()), 0)

    def test_build_ssl_context_relative_path_anchored_to_project_root(self):
        # 相对路径应归一化到工程根目录（_PROJECT_ROOT），而非当前 cwd。
        # mock ssl.create_default_context 捕获 cafile，避免依赖工程根实际存在该文件。
        import ssl as ssl_mod
        import unittest.mock as mock
        rel = "portal.crt"
        with mock.patch.object(ssl_mod, "create_default_context", return_value="CTX") as m:
            ctx = pu._build_ssl_context({"ca_cert": rel})
        self.assertEqual(ctx, "CTX")
        m.assert_called_once_with(cafile=os.path.join(pu._PROJECT_ROOT, rel))

    def test_resolve_from_project_root(self):
        self.assertEqual(pu._resolve_from_project_root(""), "")
        self.assertEqual(pu._resolve_from_project_root(None), None)
        abs_path = os.path.abspath("x.txt")
        self.assertEqual(pu._resolve_from_project_root(abs_path), abs_path)
        self.assertEqual(
            pu._resolve_from_project_root("upload.token"),
            os.path.join(pu._PROJECT_ROOT, "upload.token"))

    def test_resolve_from_project_root_expands_tilde(self):
        # ~ 应展开为用户主目录（跨机器可移植，不暴露具体用户名）。
        # Windows 下 expanduser 可能返回混合分隔符，用 normpath 归一化比较。
        resolved = pu._resolve_from_project_root("~/.config/ats-portal/portal.crt")
        expected = os.path.normpath(
            os.path.join(os.path.expanduser("~"), ".config", "ats-portal", "portal.crt"))
        self.assertEqual(os.path.normpath(resolved), expected)
        self.assertTrue(os.path.isabs(resolved))

    def test_upload_run_passes_ssl_ctx_through(self):
        # ssl_ctx 应被透传到 _request 的每次调用（此处不真正请求，仅断言透传）
        os.environ["ATS_PORTAL_TOKEN"] = "test-token"
        open(os.path.join(self.tmp, "run.log"), "w").write("hello log\n")
        cert_path = os.path.join(self.tmp, "portal.crt")
        with open(cert_path, "w", encoding="utf-8") as f:
            f.write(_SELF_SIGNED_CERT_PEM)

        received = []
        orig = pu._request

        def fake(method, url, token, data=None, headers=None, timeout=60.0, ssl_ctx=None):
            received.append((method, url, ssl_ctx))
            if method == "POST" and url.endswith("/runs"):
                return 201, json.dumps({"run_id": "x", "upload_state": "receiving"}).encode()
            if method == "PUT":
                return 200, b"{}"
            if method == "POST" and url.endswith("/finalize"):
                return 200, json.dumps({"upload_state": "complete"}).encode()
            return 200, b"{}"

        pu._request = fake
        try:
            cfg = {"server": "http://127.0.0.1:8080", "timeout": 60,
                   "ca_cert": cert_path,
                   "artifacts": [{"name": "run.log", "kind": "log"}]}
            ok = pu.upload_run(cfg, "n", self.tmp, self.tmp, "a", "b", "completed")
        finally:
            pu._request = orig

        self.assertTrue(ok)
        self.assertTrue(received)
        for _, _, ssl_ctx in received:
            self.assertIsNotNone(ssl_ctx)
            self.assertGreater(len(ssl_ctx.get_ca_certs()), 0)


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
