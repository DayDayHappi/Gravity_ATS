"""BUG-007 离线单测：录像前 FTP 死代码删除 + 启动成功回显后清残留恢复标志。

覆盖：
- 方案 A：``_list_video_dirs`` / ``_wait_new_dir`` 死方法及 ``before = set(...)`` 调用已删除。
- 方案 B：``dfs_video_start`` 成功回显后、进入 ``runtime_control.wait()`` 前，
  ``clear_recovery()`` 被调用，清掉残留 SUSPECTED 标志，录像不再被打断。
- 方案 B 反例：wait 期间新置位恢复请求，``wait()`` 仍提前返回（B 不掩盖真恢复）。

mock 控制台走 ``ftp_download=False`` 纯录像分支（不碰 FTP，与有下载分支的
clear_recovery 逻辑逐字一致）。
"""
import inspect
import threading
import time
import unittest

from ATS.application import runtime_control as rc
from ATS.core.context import Context
from ATS.core.result import Response
from ATS.drivers import video_commands as commands
from ATS.modules.video import VideoModule


class _FakeConsole:
    """录像纯分支（no-ftp）所需的最小串口控制台 mock。"""

    def __init__(self):
        self.listeners = set()

    def add_listener(self, cb):
        self.listeners.add(cb)

    def remove_listener(self, cb):
        self.listeners.discard(cb)

    def exec_sync(self, cmd, expect=None, timeout=10.0, error_on_no_sentinel=True):
        return Response(raw="ok", clean="ok", success=True, elapsed_ms=1)

    def exec_async(self, cmd, expect="", send_timeout=5.0, result_timeout=30.0):
        if cmd == commands.VIDEO_START_COMMAND:
            return Response(raw="Gravity_XR Record Start",
                            clean="Gravity_XR Record Start", success=True, elapsed_ms=1)
        # stop：返回最终完成标志 + 完整视频路径（供路径扫描 PASS）。
        return Response(
            raw="/emmc/VIDEO/20261009_001/Video_1_0.h265\nVideo recording completed successfully.",
            clean="/emmc/VIDEO/20261009_001/Video_1_0.h265\nVideo recording completed successfully.",
            success=True, elapsed_ms=1,
        )


def _make_params(duration):
    return {"video_resolution": "sd1080p_0", "video_duration": duration,
            "ftp_download": False}


class VideoBug007Test(unittest.TestCase):

    def test_A_dead_methods_removed(self):
        """方案 A：死方法与其调用点已删除，模块内零残留引用。"""
        self.assertFalse(hasattr(VideoModule, "_list_video_dirs"))
        self.assertFalse(hasattr(VideoModule, "_wait_new_dir"))
        src = inspect.getsource(VideoModule)
        self.assertNotIn("before = set(self._list_video_dirs", src)
        self.assertNotIn("_wait_new_dir(", src)

    def test_B_stale_recovery_flag_cleared_before_wait(self):
        """方案 B：录像前残留恢复标志在 start 成功回显后被清，录像不再被打断。"""
        orig_clear = rc.clear_recovery
        cleared_flag_state = []

        def spy_clear():
            # 记录 clear 调用时刻的 flag 状态，证明清的是「残留」标志而非空操作。
            cleared_flag_state.append(rc.is_recovery_requested())
            orig_clear()

        rc.clear_recovery = spy_clear
        try:
            rc.request_recovery()          # 模拟 watchdog 在录像前误置的残留标志
            module = VideoModule({})
            result = module.run(Context(), _FakeConsole(), _make_params(0.1))
        finally:
            rc.clear_recovery = orig_clear
            rc.clear_recovery()

        self.assertEqual(result.status, "PASS")
        self.assertTrue(cleared_flag_state, "clear_recovery 未被调用")
        self.assertTrue(cleared_flag_state[0], "clear 时残留标志应为置位状态")
        self.assertFalse(rc.is_recovery_requested(), "等待后标志应已被清")

    def test_B_fresh_flag_still_breaks_wait(self):
        """方案 B 反例：wait 期间新置位恢复请求，wait 仍提前返回（不掩盖真恢复）。"""
        rc.clear_recovery()
        flag_set = threading.Event()

        def set_later():
            time.sleep(0.5)
            rc.request_recovery()
            flag_set.set()

        t = threading.Thread(target=set_later, daemon=True)
        start = time.monotonic()
        t.start()
        try:
            module = VideoModule({})
            result = module.run(Context(), _FakeConsole(), _make_params(2.0))
        finally:
            t.join(timeout=3.0)
            rc.clear_recovery()

        elapsed = time.monotonic() - start
        self.assertTrue(flag_set.is_set(), "后台线程未置位恢复标志")
        self.assertEqual(result.status, "PASS")   # mock stop 成功，但 wait 应提前返回
        # 满额 wait 约 2.0s；提前返回应在 ~1.0s 内（wait step=1s），留 0.4s 余量。
        self.assertLess(elapsed, 1.6, "wait 应因新恢复请求提前返回，而非等满时长")


if __name__ == "__main__":
    unittest.main()
