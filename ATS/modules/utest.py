"""utest 模块：跑一个固件 utest testcase，取框架 result 行作判据。

协议定义：ATS/drivers/utest_commands.py（命令、result 行正则、每项超时映射）。
测试编排：Scenario 的多个 utest task + override.testcase；模块不做循环、不感知场景。

判据（ADR-012）：唯一判据 = testcase 级 result 行（固件已汇总单元结果），
不扫 unit 级业务输出、不扫 ``fail``/``error`` 关键字（``qspi_test`` 的
``1 lane fail!`` 是合法中间态）。``utest_run`` 是同步阻塞命令，仍用 ``exec_sync`` +
显式传 result 行 expect——哨兵只定界，result 行才是业务判据（红线「哨兵 ≠ 业务完成」）。
"""
import re

from .base import TestModule, register
from ..core import logger
from ..core.result import TestResult, Timer
from ..drivers import utest_commands as commands


@register("utest")
class UtestModule(TestModule):
    """固件 utest 自检：一次动作 = 跑一个 testcase。"""

    depends = []

    def __init__(self, config):
        super().__init__(config)
        self._testcase = None   # 本次执行的 testcase（供结果命名，run 时赋值）

    def run(self, ctx, console, params=None):
        cfg = self._merge(params)
        timer = Timer().start()

        testcase = cfg.get("testcase")
        if not isinstance(testcase, str) or not testcase:
            return self._mk("ERROR", "缺少 testcase 参数（scenario task 需 override.testcase）",
                            "", timer)
        self._testcase = testcase

        # 超时：override.timeout 单项覆盖 > 协议表默认值
        timeout = self._resolve_timeout(cfg.get("timeout"), testcase)
        if timeout is None:
            return self._mk("ERROR", f"未知 testcase {testcase!r} 且未提供 timeout",
                            "", timer)

        cmd = commands.UTEST_RUN_COMMAND.format(name=testcase)
        logger.step(f"  utest: {testcase}")

        # 显式传 result 行 expect：避开 serial_console 默认 _ERROR_RE 兜底，
        # 防止 qspi_test 的 "1 lane fail!" 被误判为失败。
        r = console.exec_sync(cmd, expect=commands.UTEST_RESULT_RE, timeout=timeout)
        if r.success:
            # 框架 result 行已命中。matched 取该 result 行的 status 字段。
            status = (r.matched or "").strip().upper()
            return self._mk_from_status(status, testcase, r.clean, timer)

        # exec_sync 失败（哨兵超时 / 无 result 行）。result 行一旦出现即代表业务
        # 已完成，哨兵超时只是跑得慢，故先用白名单 UTEST_RESULT_RE 对 r.clean 重判：
        # 命中白名单状态 → 按 status 出 PASS/FAIL/ERROR/SKIP。
        wl_m = re.search(commands.UTEST_RESULT_RE, r.clean or "")
        if wl_m:
            return self._mk_from_status(
                wl_m.group("status").strip().upper(), testcase, r.clean, timer)

        # 白名单未命中。区分：
        # (1) result 行存在但状态非白名单（如固件未来打印 PANIC）→ 未知状态，_error 兜底。
        # (2) 真无 result 行（或哨兵超时）→ FAIL。
        any_m = re.search(commands.UTEST_RESULT_ANY_RE, r.clean or "")
        if any_m:
            return self._mk(
                "ERROR",
                f"testcase {testcase} result 状态未知: {any_m.group('status')!r}",
                self._result_line(r.clean, testcase), timer)
        # 保留完整输出供排查（含各 unit 业务输出与框架日志）。
        return self._mk("FAIL", f"testcase {testcase} 无 result 行或执行异常",
                        (r.clean or r.error or "")[-300:], timer)

    # ---------- 内部 ----------

    def _mk_from_status(self, status, testcase, clean, timer):
        """把框架 result 行 status 映射为脚本侧 TestResult。

        PASSED → PASS；FAILED → FAIL；ERROR → ERROR；SKIPPED → SKIP。
        """
        if status == "PASSED":
            return self._mk("PASS", f"testcase {testcase} PASSED",
                            self._result_line(clean, testcase), timer)
        # FAILED → FAIL；ERROR → ERROR；SKIPPED → SKIP（脚本侧状态名）。
        st = "FAIL" if status == "FAILED" else status
        return self._mk(st, f"testcase {testcase} {status}",
                        self._result_line(clean, testcase), timer)

    def _resolve_timeout(self, override, testcase):
        """返回脚本侧超时（float）或 None（testcase 未知且无 override）。"""
        if override is not None:
            try:
                value = float(override)
                if value > 0:
                    return value
            except (TypeError, ValueError):
                logger.warn(f"utest: 忽略非法 timeout override={override!r}")
        try:
            return commands.script_timeout_for(testcase)
        except commands.UnknownTestcaseError:
            return None

    def _result_line(self, clean, testcase):
        """从 clean 输出中截取该 testcase 的 result 行（用于 detail 展示）。"""
        for ln in (clean or "").splitlines():
            if "testcase" in ln and f"({testcase})" in ln:
                return ln.strip()
        return ""

    def _mk(self, status, msg, detail, timer):
        testcase = getattr(self, "_testcase", None)
        name = f"utest[{testcase}]" if testcase else "utest"
        return TestResult(name=name, module="utest", status=status,
                          message=msg, detail=detail, elapsed_ms=timer.elapsed_ms())
