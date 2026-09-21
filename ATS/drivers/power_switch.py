"""串口上下电控制模块能力封装（PowerSwitch）。

ADR-015：给 VX100 EVB 提供「断电重启」能力。PC 通过**独立串口**（115200）连接
上下电控制模块，板子电源线接该模块；脚本需要重启板子时，发 4 字节二进制帧给
控制模块执行下电/上电。

职责边界：
- 本模块是**能力接口**，非测试模块（不注册 @register，不进 Scenario tasks）。
- 暴露被动接口 ``power_on()`` / ``power_off()`` / ``reboot()``，**不感知触发时机**
  ——何时重启由另一独立模块决策，通过直接 ``import`` 调用本接口。本模块禁止反向
  import 触发模块（单向依赖，禁止耦合）。
- 用 pyserial 直接操作独立串口（二进制帧），**不走 SerialConsole**（SerialConsole
  是 EVB msh 文本交互 + 哨兵模型，不适用二进制协议）。
- 探测独立于 EVB 的 ``detect_port``：对候选串口按 115200 打开并发上电帧，
  回 ``POWER_STATE_ON`` 者 = 控制器。候选 = 全部可访问串口 减去已确定 EVB 的端口。
- 长连接：探测成功后串口句柄保持打开，由 cleanup 关闭，不每次临时 open/close。
"""
import glob
import os
import time

try:
    import serial
except ImportError:  # pragma: no cover
    serial = None

from ..core import logger
from . import power_commands as commands


class PowerSwitchError(Exception):
    """上下电控制模块通信异常。"""


# 读空响应重试前的延时（秒）。控制器对极短间隔的重复帧（如紧跟探测帧的 cycle1
# 上电帧，间隔约 3ms）会去抖忽略、不回响应；延时错开后重发一次可覆盖。模块内常量，
# 不新增配置项（红线）。
_RETRY_DELAY = 0.5


def _accessible_ports():
    """枚举当前用户可访问的 /dev/ttyUSB* 和 /dev/ttyACM*（全部候选）。"""
    ports = sorted(set(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")))
    return [p for p in ports if os.access(p, os.R_OK | os.W_OK)]


def _read_frame(ser, timeout):
    """从串口读一个定长响应帧（读到足够字节或超时）。

    返回 bytes；超时/读不到返回 b""。控制器响应约 1s，按帧长累计读。
    读到非空 buf 后写 power_switch.log 留痕（空读不记，避免超时刷屏）。
    """
    deadline = time.monotonic() + timeout
    buf = b""
    while len(buf) < commands.POWER_FRAME_LEN:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        ser.timeout = max(0.1, remaining)
        chunk = ser.read(commands.POWER_FRAME_LEN - len(buf))
        if chunk:
            buf += chunk
        else:
            # 单次读超时：立即结束（不等满帧）
            break
    if buf:
        logger.log_power_switch("RX<", buf.hex(" ").upper())
    return buf


def _send_frame(ser, frame):
    """发送一个二进制帧（不追加换行，实测不加换行），并写 power_switch.log 留痕。"""
    ser.reset_input_buffer()
    ser.write(frame)
    ser.flush()
    logger.log_power_switch("TX>", frame.hex(" ").upper())


class PowerSwitch:
    """上下电控制模块长连接封装。

    探测成功后持有打开的控制串口，通过 power_on/power_off/reboot 发二进制帧；
    close() 释放串口。
    """

    def __init__(self, port, baudrate=None, reboot_delay=None):
        if serial is None:
            raise PowerSwitchError("缺少 pyserial 依赖，请先 pip install pyserial")
        self.port = port
        self.baudrate = baudrate or commands.POWER_BAUDRATE
        # TODO-CONFIRM：板子电容放电时间待真机确定；默认值见 system.yaml 的
        # power_switch.reboot_delay，此处仅兜底。
        self.reboot_delay = reboot_delay if reboot_delay is not None else 3.0
        self._ser = None

    def _ensure_open(self):
        if self._ser is None or not self._ser.is_open:
            self._ser = serial.Serial(self.port, self.baudrate, timeout=1.0,
                                      write_timeout=1.0)

    def _send_and_read(self, frame):
        """发一帧并读响应；读到空响应（控制器对极短间隔重复帧去抖忽略）时延时重发一次。

        覆盖所有「紧跟探测/重复帧被忽略」场景（不只压测首轮）：发帧 → 读帧，
        空 b"" 时延时 ``_RETRY_DELAY`` 重发一帧再读一次，返回第二次结果。
        正常回帧场景行为不变（帧仍只发一次，不引入副作用）。

        Returns:
            响应帧 bytes；两次都空则返回 b""。
        """
        self._ensure_open()
        _send_frame(self._ser, frame)
        resp = _read_frame(self._ser, commands.POWER_FRAME_TIMEOUT)
        if resp:
            return resp
        # 空响应：延时错开后重发一次（保底，覆盖紧跟探测帧被去抖忽略的场景）
        logger.info(f"上下电控制: 空响应，延时 {_RETRY_DELAY:g}s 重发一帧 (port={self.port})")
        time.sleep(_RETRY_DELAY)
        _send_frame(self._ser, frame)
        return _read_frame(self._ser, commands.POWER_FRAME_TIMEOUT)

    def power_on(self):
        """发上电帧并读响应帧（fire-and-forget 增强版，TC-PS-001）。

        Returns:
            响应帧 bytes；读不到/超时返回 b""。上电后期望回 ``POWER_STATE_ON``
            （压测硬判据），但本方法只回读不判状态（判据由调用方/命令层判定）。
        """
        logger.info(f"上下电控制: 上电 (port={self.port})")
        return self._send_and_read(commands.POWER_ON_FRAME)

    def power_off(self):
        """发下电帧并读响应帧（fire-and-forget 增强版，TC-PS-001）。

        Returns:
            响应帧 bytes；读不到/超时返回 b""。下电后回帧不严格要求 OFF
            （ADR-015：先 ON 后 OFF，发一次不轮询），只需是合法状态帧。
        """
        logger.info(f"上下电控制: 下电 (port={self.port})")
        return self._send_and_read(commands.POWER_OFF_FRAME)

    def query_state(self):
        """读当前控制器状态（被动查询，不触发上下电）。

        实现：不主动发帧，仅读一帧（控制器的状态帧在每次上下电后返回）。
        注意：控制器不会主动推送，实际状态应以最近一次发帧的回帧为准。
        无待读帧时返回 b""。
        """
        self._ensure_open()
        return _read_frame(self._ser, commands.POWER_FRAME_TIMEOUT)

    def reboot(self, delay=None):
        """下电 → 延时 → 上电，达到板子重启。

        Args:
            delay: 断电→上电间隔（秒）；None 时用实例的 reboot_delay。
        """
        if delay is None:
            delay = self.reboot_delay
        self.power_off()
        logger.info(f"上下电控制: 断电等待 {delay:g}s（电容放电）...")
        time.sleep(delay)
        self.power_on()

    def close(self):
        """关闭控制串口。"""
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None


def detect_power_switch(candidate_ports=None, baudrate=None, detect_timeout=None,
                        reboot_delay=None):
    """独立探测上下电控制模块：对每个候选串口按 115200 打开并发上电帧，
    回 ``POWER_STATE_ON`` 者 = 控制器。

    Args:
        candidate_ports: 候选端口列表；None 则取全部可访问串口。
        baudrate: 控制器波特率；None 用 power_commands.POWER_BAUDRATE（115200）。
        detect_timeout: 单端口探测超时；None 用 power_commands.POWER_DETECT_TIMEOUT。
        reboot_delay: 断电→上电间隔，透传给返回的 PowerSwitch 实例。

    Returns:
        探测成功返回已打开（保持长连接）的 PowerSwitch 实例；未找到返回 None。
    """
    if serial is None:
        raise PowerSwitchError("缺少 pyserial 依赖，请先 pip install pyserial")
    baudrate = baudrate or commands.POWER_BAUDRATE
    detect_timeout = detect_timeout or commands.POWER_DETECT_TIMEOUT
    ports = list(candidate_ports) if candidate_ports is not None else _accessible_ports()

    for port in ports:
        logger.debug(f"探测上下电控制器 {port} @ {baudrate} ...")
        try:
            ser = serial.Serial(port, baudrate, timeout=0.5, write_timeout=1.0)
        except Exception:
            continue
        try:
            _send_frame(ser, commands.POWER_ON_FRAME)
            resp = _read_frame(ser, detect_timeout)
        except Exception:
            try:
                ser.close()
            except Exception:
                pass
            continue
        if resp == commands.POWER_STATE_ON:
            logger.info(f"  命中上下电控制器: {port} @ {baudrate}")
            # 长连接：复用已打开的句柄（不关闭），由 cleanup 释放。
            ps = PowerSwitch(port, baudrate, reboot_delay=reboot_delay)
            ps._ser = ser
            return ps
        # 非控制器：关闭后试下一候选
        try:
            ser.close()
        except Exception:
            pass

    logger.warn("未探测到上下电控制模块（无端口回 POWER_STATE_ON）")
    return None
