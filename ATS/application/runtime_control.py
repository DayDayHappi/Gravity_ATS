"""运行时协同控制（RuntimeControl，ADR-016 Phase 5）。

长时间 Task 的协作式取消：业务模块在长等待处用 ``runtime.wait()`` 替代
``time.sleep()``，内部按小周期 sleep + 检查全局 recovery request，实现
cooperative cancellation——板卡失去响应时，长等待任务能提前结束，交 Runner
在安全点做主动 probe 与恢复，而不是干等剩余时长。

红线：业务模块仍不能直接执行 recovery，只能「提前结束等待」；recovery 的
决策与执行由 Runner / RecoveryCoordinator 完成。本模块只提供一个全局中断标志。
"""
import threading
import time

# 分段 sleep 步长（秒）。业务模块长等待按此粒度检查中断标志。
_WAIT_STEP = 1.0


class RuntimeControl:
    """全局恢复请求标志 + 分段等待。"""

    def __init__(self):
        self._recovery_requested = False
        self._lock = threading.Lock()

    def request_recovery(self):
        """置位恢复请求（由 BoardHealthMonitor 检测到 SUSPECTED/UNRESPONSIVE 时调用）。"""
        with self._lock:
            self._recovery_requested = True

    def clear_recovery(self):
        """清除恢复请求（probe 成功回 HEALTHY / 恢复完成后调用）。"""
        with self._lock:
            self._recovery_requested = False

    def is_recovery_requested(self) -> bool:
        with self._lock:
            return self._recovery_requested

    def wait(self, duration: float, step: float = None) -> bool:
        """分段 sleep，期间若收到恢复请求则提前返回 True。

        Args:
            duration: 总等待时长（秒）。
            step: 分段粒度（秒）；None 用 ``_WAIT_STEP``。

        Returns:
            True 表示因恢复请求提前结束（等待未满）；False 表示正常等待完毕。
        """
        step = step or _WAIT_STEP
        deadline = time.monotonic() + max(0.0, duration)
        while time.monotonic() < deadline:
            if self.is_recovery_requested():
                return True
            time.sleep(min(step, max(0.0, deadline - time.monotonic())))
        return False


# 模块级单例：业务模块与 Monitor/Runner 通过全局函数共享同一标志。
_runtime = RuntimeControl()


def request_recovery():
    """置位全局恢复请求。"""
    _runtime.request_recovery()


def clear_recovery():
    """清除全局恢复请求。"""
    _runtime.clear_recovery()


def is_recovery_requested() -> bool:
    """查询全局恢复请求。"""
    return _runtime.is_recovery_requested()


def wait(duration: float, step: float = None) -> bool:
    """分段 sleep + 检查全局恢复请求（cooperative cancellation）。"""
    return _runtime.wait(duration, step)
