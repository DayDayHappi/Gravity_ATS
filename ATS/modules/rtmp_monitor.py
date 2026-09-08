"""RTMP 推流持续运行检测器（heartbeat 机制）。

独立于 serial / console / test case / report，只负责「分析 RTMP 运行状态」：

- **输入**：串口原始数据（通过 ``SerialConsole.add_listener`` 订阅，串口层只转发原始文本）
- **输出**：RTMP 状态事件（ALIVE / TIMEOUT），不判 PASS/FAIL、不写文件、不碰串口

heartbeat 依据：板端推流期间的 ``f_index = N`` 日志，代表「编码完成 + 发送流程运行」，
即 RTMP 线程仍在工作。固件日志格式历史：8 月为 ``[RTMP] f_index = N, f_len = M``，
9 月变为 ``I/App Rtmp: f_index = N``（见 known_issue）。实测正常推流该日志约每 2~4s
出现一次；若超过 ``heartbeat_timeout``（默认 40s）无新 f_index，判定 RTMP 异常停止
（如 ImuThread 崩溃导致画面卡住）。

设计原则：本模块只管「检测」，最终 PASS/FAIL 由 rtmp 模块结合 ffprobe 主判据决定。
"""
import re
import time

# heartbeat 日志正则：板端 RTMP 发送侧的帧索引（代表编码+发送仍在进行）。
#
# 用裸匹配而非锚定前缀：固件日志格式已从 8 月的 "[RTMP] f_index = N" 变为 9 月的
# "I/App Rtmp: f_index = N"（f_len 可缺失，行前可能有 ANSI 残留），且前缀会被串口
# 分块截断（实测 p: f_index / Rtmp: f_index / 裸 f_index），锚定前缀必失配。
#
# 裸匹配安全前提（窗口隔离）：本 monitor 仅在 rtmp 推流保持窗口内监听，该窗口内串口
# 仅有 Rtmp 一种 f_index（scenario 串行时序保证：photo -> video -> rtmp，video 的 Dfs
# 心跳在 dfs_video_stop 后已停），故无前缀也不会误匹配其它模块的 f_index。
_HEARTBEAT_RE = re.compile(r"f_index\s*=\s*\d+")

# 状态常量
ALIVE = "ALIVE"
TIMEOUT = "TIMEOUT"


class RTMPMonitor:
    """RTMP 推流 heartbeat 检测器。

    用法：:

        monitor = RTMPMonitor(timeout=40.0)
        monitor.start()                       # 记录起点，并视为已有一次心跳
        console.add_listener(monitor.update)  # 订阅串口原始数据
        ...
        if monitor.check_timeout():           # 周期检查是否超时
            # 推流异常停止
        console.remove_listener(monitor.update)
        monitor.stop()
    """

    # timeout 默认值仅当调用方未显式传入时生效（rtmp.py 会传 yaml 的 heartbeat_timeout）；
    # 权威值见 config/modules/rtmp.yaml（会经常调整）。
    def __init__(self, timeout: float = 40.0):
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
            self._reason = f"RTMP heartbeat timeout（>{self.timeout:.0f}s 无 f_index）"
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
