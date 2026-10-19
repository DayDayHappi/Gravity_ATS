"""串口上下电控制模块（PowerSwitch）协议定义：命令帧、判据帧与超时的唯一维护位置。

ADR-015：PC 通过**独立串口**（115200）连接上下电控制模块，发 4 字节二进制帧执行
下电/上电，板子电源线接该模块。

本文件只存协议字节/判据帧/超时，**不写 IO、不 import console/ctx/ftp/pyserial、
不读取 YAML、不安排触发时机**（ADR-011：协议属固件契约留代码，yaml 只存开关与
硬件参数）。

帧格式（实测 `res/串口控制器log.txt`）：4 字节 hex，末字节 = 前三字节求和 & 0xFF，
换行符**不加**（已实测）。控制器响应约 1.0~1.1s（见 log TX→RX 时间戳）。
"""

# 帧长（字节）。收发均为 4 字节定长。
POWER_FRAME_LEN = 4

# PC → 控制器：上电
POWER_ON_FRAME = bytes([0xA0, 0x01, 0x03, 0xA4])
# PC → 控制器：下电
POWER_OFF_FRAME = bytes([0xA0, 0x01, 0x02, 0xA3])
# 控制器 → PC：状态 ON（探测判据：发上电帧后回此帧 = 控制器）
POWER_STATE_ON = bytes([0xA0, 0x01, 0x01, 0xA2])
# 控制器 → PC：状态 OFF
POWER_STATE_OFF = bytes([0xA0, 0x01, 0x00, 0xA1])

# 控制器串口波特率（与 EVB 的 2000000 不同，用于探测区分防接反）
POWER_BAUDRATE = 115200

# 单次收发超时（秒）。实测控制器响应约 1.0~1.1s，留宽松余量。
POWER_FRAME_TIMEOUT = 3.0
# 探测时：发上电帧后等待响应帧的超时（同上，真机再校准）
POWER_DETECT_TIMEOUT = 3.0
# 探测时串口打开后的读超时（秒）
POWER_DETECT_READ_TIMEOUT = 0.5


def is_valid_state_frame(frame) -> bool:
    """判据：响应帧是否合法（4 字节 + 帧头 A0 01 + 末字节 = 前三字节求和 & 0xFF）。

    TC-PS-001 压测判据之一：每次发帧后须收到合法 4 字节状态帧。
    """
    if not isinstance(frame, (bytes, bytearray)) or len(frame) != POWER_FRAME_LEN:
        return False
    if frame[0] != 0xA0 or frame[1] != 0x01:
        return False
    return ((frame[0] + frame[1] + frame[2]) & 0xFF) == frame[3]


def frame_state(frame) -> int:
    """取合法状态帧的 state 字节：0x01=ON / 0x00=OFF；非法帧返回 -1。"""
    if not is_valid_state_frame(frame):
        return -1
    return frame[2]

