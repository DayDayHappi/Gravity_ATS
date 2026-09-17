"""utest 公共基类：result 行判据 + D1 叠加校验模板。

每个 case 模块继承 ``UtestCaseModule``，设置：
    testcase      固件 testcase 名（如 ``"efuse_test"``）
    business_res  业务关键串正则列表（D1 叠加校验，来自 ``<case>_commands.py``）

D1 叠加判据语义（实施以此为准）：
1. **result 行优先**：FAILED→FAIL、ERROR→ERROR、SKIPPED→SKIP，业务串不反向救回。
2. result 行 **PASSED** 前提下，再校验业务关键串：齐全→PASS；缺失/不符→FAIL
   （detail 记录缺失串）。
3. **无 result 行** → FAIL（兜底，同原单模块行为）。

哨兵只定界，result 行 + 业务串才是业务判据（红线「哨兵 ≠ 业务完成」）。
``utest_run`` 是同步阻塞命令，用 ``exec_sync`` + 显式传 result 行 expect，
避开 serial_console 默认 ``_ERROR_RE`` 兜底（``qspi_test`` 的 ``1 lane fail!``、
``filesystem`` 的 ``not a mountpoint!`` 均为合法中间态，绝不判失败）。
"""
import re

from ..base import TestModule
from ...core import logger
from ...core.result import TestResult, Timer
from ...drivers.utest import _common as commands


class UtestCaseModule(TestModule):
    """固件 utest 单个 testcase：一次动作 = 跑一个 testcase 并叠加校验。"""

    testcase = ""           # 子类设置：固件 testcase 名
    business_res = []       # 子类设置：业务关键串正则列表（D1 叠加）
    depends = []

    def run(self, ctx, console, params=None):
        cfg = self._merge(params)
        timer = Timer().start()
        testcase = self.testcase

        timeout = self._resolve_timeout(cfg.get("timeout"), testcase)
        if timeout is None:
            return self._mk("ERROR", f"未知 testcase {testcase!r} 且未提供 timeout",
                            "", timer)

        cmd = commands.UTEST_RUN_COMMAND.format(name=testcase)
        logger.step(f"  {self.name}: {testcase}")

        # 显式传 result 行 expect：避开 serial_console 默认 _ERROR_RE 兜底，
        # 防止 qspi 的 "1 lane fail!"、filesystem 的 "not a mountpoint!" 被误判。
        r = console.exec_sync(cmd, expect=commands.UTEST_RESULT_RE, timeout=timeout)

        # D1 步骤 1：result 行优先。统一对 r.clean 重判（哨兵成功与否不影响 status
        # 提取；哨兵超时但 result 行已出现时，r.clean 仍含完整 result 行）。
        status = self._extract_status(r.clean)
        if status is None:
            any_m = re.search(commands.UTEST_RESULT_ANY_RE, r.clean or "")
            if any_m:
                return self._mk(
                    "ERROR",
                    f"testcase {testcase} result 状态未知: {any_m.group('status')!r}",
                    self._result_line(r.clean, testcase), timer)
            # 保留完整输出供排查（含各 unit 业务输出与框架日志）。
            return self._mk("FAIL", f"testcase {testcase} 无 result 行或执行异常",
                            (r.clean or r.error or "")[-300:], timer)

        if status != "PASSED":
            return self._mk_from_status(status, testcase, r.clean, timer)

        # D1 步骤 2：result 行 PASSED，叠加业务关键串校验（补充校验）。
        missing = self._collect_missing(r.clean, cfg)
        if missing:
            detail = self._result_line(r.clean, testcase)
            detail += "\n缺失业务关键串: " + ", ".join(missing)
            return self._mk("FAIL", f"testcase {testcase} PASSED 但业务关键串缺失",
                            detail, timer)
        return self._mk("PASS", f"testcase {testcase} PASSED",
                        self._result_line(r.clean, testcase), timer)

    # ---------- 可覆盖钩子 ----------

    def _extra_missing(self, clean, cfg):
        """子类可覆盖：返回额外缺失判据描述（如 flash_xip_speed 阈值不达标）。"""
        return []

    # ---------- 内部 ----------

    def _collect_missing(self, clean, cfg):
        """汇总缺失判据：业务串正则未命中 + 子类额外校验。"""
        missing = []
        for pat in self.business_res:
            if not re.search(pat, clean or ""):
                missing.append(pat)
        missing.extend(self._extra_missing(clean, cfg))
        return missing

    def _extract_status(self, clean):
        """从 clean 输出提取白名单 result 行 status；无则返回 None。"""
        m = re.search(commands.UTEST_RESULT_RE, clean or "")
        if m:
            return m.group("status").strip().upper()
        return None

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
                logger.warn(f"{self.name}: 忽略非法 timeout override={override!r}")
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
        return TestResult(name=self.name, module=self.name, status=status,
                          message=msg, detail=detail, elapsed_ms=timer.elapsed_ms())
