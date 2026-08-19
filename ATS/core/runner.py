"""测试编排器：依赖排序、执行、重试、fail-fast。

职责：
1. 按 ``enabled_modules`` 实例化已注册模块。
2. 拓扑排序：按 ``depends`` 把被依赖模块排前面，保证执行顺序正确。
3. 依次执行 setup/run/teardown。
4. 失败处理：
   - 某模块失败 -> 重试 retry_on_fail 次
   - 仍失败且 fail_fast -> 依赖它的后续模块标记 SKIP
   - photo 这种返回多结果的模块，单条失败不影响其他（模块自身处理）
5. 收集所有 TestResult，交 reporter 输出。

runner 不感知具体模块逻辑，只通过 TestModule 接口和 ctx 调度，保持与模块解耦。
"""
import datetime as _dt
import time

from . import logger
from .result import TestResult, PASSED, FAILED, SKIPPED, ERROR


class RunnerError(Exception):
    pass


class TestRunner:
    """测试编排器。"""

    def __init__(self, config, console, ctx):
        self.config = config
        self.console = console
        self.ctx = ctx
        self.ctx.console = console
        self.results: list = []           # 所有 TestResult
        self.module_status: dict = {}     # module name -> PASS/FAIL/SKIP/ERROR
        self.retry = int(config.get("test", {}).get("retry_on_fail", 1))
        self.fail_fast = bool(config.get("test", {}).get("fail_fast", True))
        self.enabled = list(config.get("test", {}).get("enabled_modules", []))

    def run(self) -> list:
        """执行全部已启用模块，返回 TestResult 列表。"""
        from ..modules.base import get_module_cls
        # 触发模块注册（导入 modules 包）
        import importlib
        importlib.import_module("ATS.modules")

        # 1. 拓扑排序
        ordered = self._topo_sort(self.enabled)
        logger.info(f"本次执行模块顺序: {ordered}")

        # 2. 依次执行
        for name in ordered:
            cls = get_module_cls(name)
            if cls is None:
                logger.error(f"未注册的模块: {name}（跳过）")
                self._record(TestResult(name=name, module=name, status=ERROR,
                                        message="模块未注册"))
                continue

            # fail_fast: 若依赖的模块失败/出错，本模块跳过
            # 注意：依赖模块 SKIP 不算阻断（如 wifi_check 已联网后 wifi_scan 主动 SKIP，
            # 不应连累 wifi_join；wifi_join 自身的 run() 会再次检查 ctx.skip_wifi 决定是否 SKIP）
            deps = getattr(cls, "depends", []) or []
            blocked = [d for d in deps if self.module_status.get(d) in (FAILED, ERROR)]
            if blocked:
                self._record(TestResult(
                    name=name, module=name, status=SKIPPED,
                    message=f"依赖模块未通过: {blocked}",
                ))
                self.module_status[name] = SKIPPED
                continue

            self._run_module(name, cls)

        return self.results

    def _run_module(self, name, cls):
        """执行单个模块：实例化 -> setup -> run(带重试) -> teardown。

        开始时打印并计时，结束时（无论成功/失败/异常）打印本模块总耗时，
        便于确认脚本在持续推进、定位慢模块或疑似卡住。
        """
        mod_start = time.monotonic()
        logger.step(f">>> 模块 [{name}] 开始执行")
        try:
            # 取该模块的配置段（按模块名取小写段，如 wifi/emmc/ftp/camera/rtmp）
            mod_cfg = self._module_config(name, cls)
            module = cls(mod_cfg)

            # setup
            try:
                module.setup(self.ctx, self.console)
            except Exception as e:
                logger.error(f"[{name}] setup 异常: {e}")
                self._record(TestResult(name=name, module=name, status=ERROR,
                                        message=f"setup 异常: {e}"))
                self.module_status[name] = ERROR
                return

            # run（带重试）
            result = None
            last_err = None
            for attempt in range(1, self.retry + 1):
                try:
                    logger.step(f"    - 执行模块: {name}" + (f" (尝试 {attempt})" if attempt > 1 else ""))
                    result = module.run(self.ctx, self.console)
                    # 判定本次是否整体通过
                    if self._overall_pass(result):
                        break
                except Exception as e:
                    last_err = e
                    logger.warn(f"[{name}] 第 {attempt} 次执行异常: {e}")
                    result = TestResult(name=name, module=name, status=ERROR,
                                        message=f"执行异常: {e}")
                if attempt < self.retry:
                    logger.info(f"[{name}] 失败，重试中...")

            # teardown
            try:
                module.teardown(self.ctx, self.console)
            except Exception as e:
                logger.warn(f"[{name}] teardown 异常: {e}")

            # 记录结果
            self._record_results(name, result, last_err)
            # 模块状态：取返回结果的真实状态（PASS/SKIP 视为通过，不阻断依赖）
            if isinstance(result, list):
                st = PASSED if any(r.status in (PASSED, SKIPPED) for r in result) else FAILED
            elif result is not None:
                st = result.status
            else:
                st = FAILED
            self.module_status[name] = st
        finally:
            elapsed = time.monotonic() - mod_start
            status = self.module_status.get(name, "?")
            logger.step(f"<<< 模块 [{name}] 结束，耗时 {elapsed:.1f}s（结果 {status}）")

    def _record_results(self, name, result, last_err):
        """把模块返回的结果（单条或多条）记录进 self.results 并打印。"""
        if result is None:
            self._record(TestResult(name=name, module=name, status=FAILED,
                                    message="模块未返回结果"))
            return
        if isinstance(result, list):
            for r in result:
                self._record(r)
        else:
            self._record(result)

    def _record(self, r: TestResult):
        r.timestamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.results.append(r)
        logger.result_line(r.status, r.name, r.elapsed_ms, r.message)

    def _overall_pass(self, result) -> bool:
        """判断模块返回结果是否整体通过。

        SKIP 视为通过（主动跳过不算失败，如 wifi_scan 在已联网时 SKIP）。
        """
        if result is None:
            return False
        if isinstance(result, list):
            if not result:
                return False
            # photo: 任一通过即视为模块通过（部分模式失败不影响链路）
            return any(r.status in (PASSED, SKIPPED) for r in result)
        return result.status in (PASSED, SKIPPED)

    def _module_config(self, name, cls):
        """从总配置取出该模块对应的配置段。

        映射规则：模块名 -> 配置段名。部分模块名与段名不同：
          wifi_scan/wifi_join -> wifi
          ftp_server -> ftp
          emmc -> emmc, camera(拍照录像共用)
          rtmp -> rtmp
        """
        cfg = self.config
        # 模块名到配置段的映射
        mapping = {
            "wifi_check": "wifi", "wifi_scan": "wifi", "wifi_join": "wifi",
            "ftp": "ftp", "ftp_server": "ftp",
            "emmc": "emmc", "emmc_mount": "emmc",
            "photo": "camera", "video": "camera",
            "rtmp": "rtmp", "rtmp_stream": "rtmp",
        }
        section = mapping.get(name, name)
        mod_cfg = dict(cfg.get(section, {}) or {})
        # 把全局串口/wifi 等也带一点进来，方便模块取（如 wifi 段）
        return mod_cfg

    def _topo_sort(self, names: list) -> list:
        """按依赖拓扑排序。被依赖的模块排在前面。"""
        from ..modules.base import get_module_cls
        result = []
        visited = set()
        temp = set()

        def visit(n):
            if n in visited:
                return
            if n in temp:
                logger.warn(f"检测到模块依赖环: {n}（忽略该依赖）")
                return
            temp.add(n)
            cls = get_module_cls(n)
            if cls is not None:
                for dep in (getattr(cls, "depends", []) or []):
                    if dep in names:  # 只排已启用的依赖
                        visit(dep)
            temp.discard(n)
            visited.add(n)
            result.append(n)

        for n in names:
            visit(n)
        return result
