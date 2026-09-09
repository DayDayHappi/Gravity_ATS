"""录像固件协议定义：完整命令与实测 size 的唯一维护位置。

本文件不发送串口、不连接 FTP、不读取 YAML，也不安排测试次数或时长。
映射来源：用户 2026-09-09 在当前需求中提供的手测结果。
width/height/orientation 是预期值，不是脚本对本次视频的测量结果。
"""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class VideoProfile:
    """一个独立的录像命令组合；相同像素尺寸不代表同一个组合。"""

    key: str
    command: str
    width: int
    height: int
    orientation: str


# 必须存完整命令，不能在业务代码按 key 拼接或依赖板端默认尾参数。
VIDEO_PROFILES: Mapping[str, VideoProfile] = MappingProxyType({
    "sd1080p_0": VideoProfile("sd1080p_0", "cam_set video sd1080p 0", 1920, 1080, "横屏"),
    "sd1080p_1": VideoProfile("sd1080p_1", "cam_set video sd1080p 1", 1920, 1080, "横屏"),
    "sd1080p_2": VideoProfile("sd1080p_2", "cam_set video sd1080p 2", 2016, 1034, "横屏"),
    "hd1080p_1": VideoProfile("hd1080p_1", "cam_set video hd1080p 1", 1920, 1080, "横屏"),
    "hd1080p_2": VideoProfile("hd1080p_2", "cam_set video hd1080p 2", 1296, 2304, "竖屏"),
    "3k_2": VideoProfile("3k_2", "cam_set video 3k 2", 2268, 3024, "竖屏"),
    "720p_0": VideoProfile("720p_0", "cam_set video 720p 0", 1280, 720, "横屏"),
    "720p_1": VideoProfile("720p_1", "cam_set video 720p 1", 1280, 720, "横屏"),
    "720p_2": VideoProfile("720p_2", "cam_set video 720p 2", 1600, 900, "横屏"),
    "480p_0": VideoProfile("480p_0", "cam_set video 480p 0", 640, 480, "横屏"),
    "480p_2": VideoProfile("480p_2", "cam_set video 480p 2", 800, 600, "横屏"),
})

# 默认策略明确采用需求表第一项；不声称它等同旧固件的模糊 "1080p" 默认。
DEFAULT_VIDEO_PROFILE = "sd1080p_0"
BLOCKED_VIDEO_PROFILES: Mapping[str, str] = MappingProxyType({
    "480p_1": "用户手测报错刷屏，本轮明确不测试",
})

VIDEO_START_COMMAND = "dfs_video_start"
VIDEO_STOP_COMMAND = "dfs_video_stop"
VIDEO_START_EXPECT = r"Record Start|f_index\s*="
VIDEO_STOP_EXPECT = r"Video recording completed successfully."
VIDEO_CLEANUP_EXPECT = r"Save Video|Please start|recording completed"
# exec_sync 无 expect 时并不必然识别 Usage；设置失败绝不接着录旧 size。
VIDEO_SET_ERROR = r"(?i)\b(?:usage|error|failed|fail|invalid|unknown|unsupported)\b|command not found"
VIDEO_SET_TIMEOUT = 10.0
VIDEO_START_TIMEOUT = 25.0
VIDEO_STOP_TIMEOUT = 25.0
VIDEO_CLEANUP_TIMEOUT = 8.0


class VideoProfileError(ValueError):
    """未知、不完整或本轮禁止的录像组合。"""


def resolve_video_profile(key: str) -> VideoProfile:
    """只允许显式组合 ID；拒绝裸档位和任意串口命令，不做静默猜测。"""
    if not isinstance(key, str) or not key:
        raise VideoProfileError("video_resolution 必须是非空组合 ID，例如 sd1080p_0")
    if key in BLOCKED_VIDEO_PROFILES:
        raise VideoProfileError(f"录像组合 {key} 已禁用：{BLOCKED_VIDEO_PROFILES[key]}")
    profile = VIDEO_PROFILES.get(key)
    if profile is None:
        choices = ", ".join(VIDEO_PROFILES)
        raise VideoProfileError(f"video_resolution={key!r} 未定义或不完整；请显式选择：{choices}")
    return profile
