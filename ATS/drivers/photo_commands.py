"""拍照固件协议定义：命令、判据、超时与路径的唯一维护位置。

本文件不发送串口、不连接 FTP、不读取 YAML，也不安排测试次数或时长。
"""
from types import MappingProxyType
from typing import Mapping

# 合法拍照模式名（唯一来源文档）。业务从 config/modules/photo.yaml 的 photo_modes
# 读取模式名后，用 PHOTO_SET_COMMAND.format(mode=...) 拼命令（不在此处校验 mode 合法性）。
# hdr 0~3 已真机核实为「带参数形式」（cam_set photo hdr <0-3>），非下划线独立名 hdr_0~3；
# single 1080p/720p/480p 三个含空格模式名同样需真机核实（见 archive/新增需求_photo单拍分辨率变体.md）；
# heif 是否为固件合法模式名待真机核实——可能是独立模式名 cam_set photo heif，
# 也可能带参数（如 cam_set photo hdr <0-3> 同源疑问，见 archive 软件需求文档 L483）。
PHOTO_MODES: Mapping[str, str] = MappingProxyType({
    "auto": "cam_set photo auto",
    "single": "cam_set photo single",
    "single 1080p": "cam_set photo single 1080p",
    "single 720p": "cam_set photo single 720p",
    "single 480p": "cam_set photo single 480p",
    "mfnr": "cam_set photo mfnr",
    "hdr 0": "cam_set photo hdr 0",
    "hdr 1": "cam_set photo hdr 1",
    "hdr 2": "cam_set photo hdr 2",
    "hdr 3": "cam_set photo hdr 3",
    "heif": "cam_set photo heif",
})

# 命令模板（保持对任意 mode 的兼容，由固件自行拒绝非法模式名）。
PHOTO_SET_COMMAND = "cam_set photo {mode}"
PHOTO_CAPTURE_COMMAND = "dfs_capture_start"
PHOTO_CAPTURE_EXPECT = r"Capture completed successfully."
PHOTO_SET_TIMEOUT = 10.0
PHOTO_CAPTURE_TIMEOUT = 30.0

# 实测拍照存盘目录（大写）
_PIC_DIR = "/emmc/PIC"
