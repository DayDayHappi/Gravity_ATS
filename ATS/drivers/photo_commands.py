"""拍照固件协议定义：命令、判据、超时与路径的唯一维护位置。

本文件不发送串口、不连接 FTP、不读取 YAML，也不安排测试次数或时长。
"""
from types import MappingProxyType
from typing import Mapping

# 合法拍照模式名（唯一来源文档）。业务从 config/modules/photo.yaml 的 photo_modes
# 读取模式名后，用 PHOTO_SET_COMMAND.format(mode=...) 拼命令（不在此处校验 mode 合法性）。
# TODO-CONFIRM：hdr_0~3 是否为固件合法模式名待真机核实（与场景文件注释同源）。
PHOTO_MODES: Mapping[str, str] = MappingProxyType({
    "auto": "cam_set photo auto",
    "single": "cam_set photo single",
    "mfnr": "cam_set photo mfnr",
    "hdr_0": "cam_set photo hdr_0",
    "hdr_1": "cam_set photo hdr_1",
    "hdr_2": "cam_set photo hdr_2",
    "hdr_3": "cam_set photo hdr_3",
})

# 命令模板（保持对任意 mode 的兼容，由固件自行拒绝非法模式名）。
PHOTO_SET_COMMAND = "cam_set photo {mode}"
PHOTO_CAPTURE_COMMAND = "dfs_capture_start"
PHOTO_CAPTURE_EXPECT = r"Capture completed successfully."
PHOTO_SET_TIMEOUT = 10.0
PHOTO_CAPTURE_TIMEOUT = 30.0

# 实测拍照存盘目录（大写）
_PIC_DIR = "/emmc/PIC"
