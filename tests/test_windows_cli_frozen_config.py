"""Windows CLI 打包 frozen 路径解析单元测试（feature/windows-cli，T1/T3）。

覆盖：
- config._resolve_config_dir：非 frozen / frozen exe 同级命中 / frozen 回退内置备份。
- portal_upload._PROJECT_ROOT：非 frozen 为源码工程根，frozen 为 exe 同级目录。
- config_dir 透传（T2）：load_module_config 显式 config_dir 优先于默认 CONFIG_DIR。

纯离线，不依赖真机 / Windows。
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

from ATS.core import config as cfg
from ATS.application import portal_upload as pu


class ConfigFrozenResolutionTest(unittest.TestCase):
    """T1：CONFIG_DIR / _resolve_config_dir 的 frozen 感知。"""

    def tearDown(self):
        cfg.CONFIG_DIR = cfg._resolve_config_dir()

    def test_non_frozen_uses_source_config(self):
        with mock.patch.object(sys, "frozen", False, create=True):
            self.assertEqual(cfg._resolve_config_dir(), cfg._INTERNAL_CONFIG_DIR)

    def test_frozen_exe_side_wins_when_system_yaml_exists(self):
        with tempfile.TemporaryDirectory() as exe_dir, \
             tempfile.TemporaryDirectory() as meipass:
            os.makedirs(os.path.join(exe_dir, "config"))
            with open(os.path.join(exe_dir, "config", "system.yaml"), "w",
                      encoding="utf-8") as f:
                f.write("serial:\n  port: auto\n  baudrate: 2000000\n")

            with mock.patch.object(sys, "frozen", True, create=True), \
                 mock.patch.object(sys, "executable", os.path.join(exe_dir, "AtsCli.exe")):
                self.assertEqual(cfg._resolve_config_dir(),
                                 os.path.join(exe_dir, "config"))

    def test_frozen_falls_back_to_internal_when_missing_system_yaml(self):
        with tempfile.TemporaryDirectory() as exe_dir, \
             tempfile.TemporaryDirectory() as meipass:
            # exe 同级 config 存在但缺 system.yaml -> 回退内置备份
            os.makedirs(os.path.join(exe_dir, "config"))
            internal = os.path.join(meipass, "ATS", "config")
            os.makedirs(internal)

            with mock.patch.object(sys, "frozen", True, create=True), \
                 mock.patch.object(sys, "executable", os.path.join(exe_dir, "AtsCli.exe")), \
                 mock.patch.object(cfg, "_INTERNAL_CONFIG_DIR", internal):
                self.assertEqual(cfg._resolve_config_dir(), internal)

    def test_explicit_config_dir_overrides_module_level(self):
        """T2：load_module_config 的显式 config_dir 优先。"""
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "modules"))
            with open(os.path.join(d, "modules", "video.yaml"), "w",
                      encoding="utf-8") as f:
                f.write("video_resolution: 3k_2\n")
            loaded = cfg.load_module_config("video", d)
            self.assertEqual(loaded["video_resolution"], "3k_2")


class PortalProjectRootTest(unittest.TestCase):
    """T3：portal_upload._PROJECT_ROOT 的 frozen 感知。"""

    def test_non_frozen_project_root_points_to_source_root(self):
        # 非 frozen 时 _PROJECT_ROOT 为 ATS/ 上一级（工程根），可用 _resolve_from_project_root 验证：
        # 工程根下应存在 ATS 目录。
        self.assertTrue(os.path.isdir(os.path.join(pu._PROJECT_ROOT, "ATS")))

    def test_frozen_project_root_points_to_exe_dir(self):
        with tempfile.TemporaryDirectory() as exe_dir:
            with mock.patch.object(sys, "frozen", True, create=True), \
                 mock.patch.object(sys, "executable", os.path.join(exe_dir, "AtsCli.exe")):
                import importlib
                importlib.reload(pu)
                self.assertEqual(pu._PROJECT_ROOT, exe_dir)
        # 还原模块真实状态（reload 会重建常量，避免污染其他测试）
        importlib.reload(pu)


if __name__ == "__main__":
    unittest.main()
