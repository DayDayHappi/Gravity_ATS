"""拍照固件协议定义：命令、判据、超时与参数取值域的唯一维护位置。

本文件不发送串口、不连接 FTP、不读取 YAML，也不安排测试次数或时长。
固件 ``cam_set photo`` 为三段式语法：

    cam_set photo <mode> [size <SIZE>] [num]

2026-11-19 固件串口日志核实：``single`` 之后紧跟的**裸 token 被固件当作 ``num``（帧率）**，
要设尺寸**必须**带 ``size`` 关键字（``cam_set photo single size 8m`` 才生效）。
本文件是 mode/size 取值域、命令拼装与合法性校验的唯一来源；
场景只选择参数（``photo_modes`` 的映射元素），业务代码经 ``resolve_photo_params`` +
``PhotoParams.command`` 下发，不内联协议字符串（ADR-011 / ADR-018）。
"""
from dataclasses import dataclass
from typing import Mapping, Optional

# 合法 mode（6 种，ADR-018）与 size（7 种）。业务侧不再自行拼字符串。
PHOTO_MODE_NAMES = ("auto", "single", "mfnr", "hdr", "fcov", "heif")
PHOTO_SIZES = ("12m", "8m", "w8m", "3m", "1080p", "720p", "480p")

PHOTO_CAPTURE_COMMAND = "cam_run photo"
PHOTO_CAPTURE_EXPECT = r"Capture completed successfully."
PHOTO_SET_TIMEOUT = 10.0
PHOTO_CAPTURE_TIMEOUT = 30.0

# 实测拍照存盘目录（大写）
_PIC_DIR = "/emmc/PIC"


class PhotoParamsError(ValueError):
    """非法的拍照参数（枚举外 / 缺 mode / num 非整数 / 旧字符串形式）。"""


@dataclass(frozen=True)
class PhotoParams:
    """一条完整拍照参数组合（对应一条 ``cam_set photo`` 命令）。

    ``num`` 语义随 mode：``hdr`` 为连拍张数 0-3、``single`` 为帧率 30/60、
    其它 mode 固件忽略。本类只校验 num 为非负整数（越界交固件拒绝）。
    """

    mode: str
    size: Optional[str] = None
    num: Optional[int] = None

    @property
    def key(self) -> str:
        """报告/文件名用短键，**无空格**，如 ``single-12m`` / ``hdr-n0`` / ``auto``。"""
        key = self.mode
        if self.size is not None:
            key += f"-{self.size}"
        if self.num is not None:
            key += f"-n{self.num}"
        return key

    @property
    def command(self) -> str:
        """按固件语法拼完整命令：``cam_set photo <mode> [size <SIZE>] [num]``。"""
        cmd = f"cam_set photo {self.mode}"
        if self.size is not None:
            cmd += f" size {self.size}"
        if self.num is not None:
            cmd += f" {self.num}"
        return cmd


def resolve_photo_params(entry) -> PhotoParams:
    """校验并构造 ``PhotoParams``；不合法直接抛错（拒绝执行，不静默猜测）。

    ``entry`` 必须是含 ``mode``（必需）与可选 ``size`` / ``num`` 的**映射**。
    **硬切**：旧字符串形式（如 ``"single 12m"``）一律拒绝，不做双读兼容（ADR-018）。
    """
    if not isinstance(entry, Mapping):
        raise PhotoParamsError(
            "photo_modes 元素必须是映射（如 {mode: single, size: 12m}），"
            f"实际 {entry!r}；旧字符串形式已废弃（ADR-018）"
        )
    mode = entry.get("mode")
    if not isinstance(mode, str) or mode not in PHOTO_MODE_NAMES:
        raise PhotoParamsError(f"mode={mode!r} 不在取值域 {PHOTO_MODE_NAMES}")

    size = entry.get("size")
    if size is not None:
        if not isinstance(size, str) or size not in PHOTO_SIZES:
            raise PhotoParamsError(f"size={size!r} 不在取值域 {PHOTO_SIZES}")

    num = entry.get("num")
    if num is not None:
        # bool 是 int 子类，必须显式拒绝（True 不能当 num）。
        if isinstance(num, bool) or not isinstance(num, int):
            raise PhotoParamsError(f"num 必须是整数，实际 {num!r}")
        if num < 0:
            raise PhotoParamsError(f"num={num} 不能为负数")

    return PhotoParams(mode=mode, size=size, num=num)
