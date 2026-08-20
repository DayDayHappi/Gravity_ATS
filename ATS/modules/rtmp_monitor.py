"""RTMP 推流持续运行检测器（heartbeat 机制）。

独立于 serial / console / test case / report，只负责「分析 RTMP 运行状态」：

- **输入**：串口原始数据（通过 ``SerialConsole.add_listener`` 订阅，串口层只转发原始文本）
- **输出**：RTMP 状态事件（ALIVE / TIMEOUT），不判 PASS/FAIL、不写文件、不碰串口

heartbeat 依据：板端推流期间的 ``[RTMP] f_index = N, f_len = M`` 日志，代表「编码完成 +
发送流程运行」，即 RTMP 线程仍在工作。实测正常推流该日志约每 2~4s 出现一次；若超过
``heartbeat_timeout``（默认 30s）无新 f_index，判定 RTMP 异常停止（如 ImuThread 崩溃导致
画面卡住）。

设计原则：本模块只管「检测」，最终 PASS/FAIL 由 rtmp 模块结合 ffprobe 主判据决定。
"""
import re
import time

# heartbeat 日志正则：板端 RTMP 发送侧的帧索引（代表编码+发送仍在进行）。
# 实测格式 "[RTMP] f_index = 0, f_len = 39"，f_len 可缺失，行前可能有 ANSI 残留。
_HEARTBEAT_RE = re.compile(r"\[RTMP\]\s+f_index\s*=")

# 状态常量
ALIVE = "ALIVE"
TIMEOUT = "TIMEOUT"


class RTMPMonitor:
    """RTMP 推流 heartbeat 检测器。

    用法：:

        monitor = RTMPMonitor(timeout=30.0)
        monitor.start()                       # 记录起点，并视为已有一次心跳
        console.add_listener(monitor.update)  # 订阅串口原始数据
        ...
        if monitor.check_timeout():           # 周期检查是否超时
            # 推流异常停止
        console.remove_listener(monitor.update)
        monitor.stop()
    """

    def __init__(self, timeout: float = 30.0):
        self.timeout = float(timeout)
        self._started = False
        self._start_time = 0.0        # monotonic
        self._start_clock = ""        # 人读 HH:MM:SS
        self._last_frame_time = 0.0   # monotonic
        self._last_frame_clock = ""   # 人读 HH:MM:SS
        self._frame_count = 0
        self._status = ALIVE
        self._reason = ""

    def start(self):
        """启动检测。起点记为「已有一次心跳」，避免推流刚上线、首个 f_index 尚未到来就被误判超时。"""
        now = time.monotonic()
        self._started = True
        self._start_time = now
        self._start_clock = time.strftime("%H:%M:%S")
        self._last_frame_time = now
        self._last_frame_clock = self._start_clock
        self._frame_count = 0
        self._status = ALIVE
        self._reason = ""

    def update(self, text: str):
        """喂入串口原始数据（由读线程回调），匹配到 heartbeat 则刷新 last_frame_time。

        线程安全：仅在读线程调用，只做正则匹配 + 标量赋值，极轻量。
        """
        if not self._started or not text:
            return
        if _HEARTBEAT_RE.search(text):
            now = time.monotonic()
            self._last_frame_time = now
            self._last_frame_clock = time.strftime("%H:%M:%S")
            self._frame_count += 1

    def check_timeout(self) -> bool:
        """检查距上次 heartbeat 是否超过 timeout。超时则置状态为 TIMEOUT 并返回 True。"""
        if not self._started:
            return False
        if (time.monotonic() - self._last_frame_time) > self.timeout:
            self._status = TIMEOUT
            self._reason = f"RTMP heartbeat timeout（>{self.timeout:.0f}s 无 [RTMP] f_index）"
            return True
        return False

    def get_status(self) -> dict:
        """返回结构化状态（供 rtmp 模块写入 TestResult / report）。

        字段：status / reason / start_time / last_frame_time / timeout / duration / frame_count
        """
        now = time.monotonic()
        duration = now - self._start_time if self._started else 0.0
        return {
            "status": self._status,
            "reason": self._reason or ("OK" if self._status == ALIVE else ""),
            "start_time": self._start_clock,
            "last_frame_time": self._last_frame_clock,
            "timeout": self.timeout,
            "duration": duration,
            "frame_count": self._frame_count,
        }

    def stop(self):
        """停止检测（无资源需释放，保留接口统一）。"""
        self._started = False
