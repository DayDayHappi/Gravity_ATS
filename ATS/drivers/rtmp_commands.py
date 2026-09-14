"""RTMP 推流固件协议定义：命令、判据、heartbeat 正则与超时的唯一维护位置。

本文件不发送串口、不连接 RTMP/ffprobe、不读取 YAML，也不安排测试次数或时长。
"""
import re
from typing import Pattern

RTMP_START_COMMAND = "rtmp_video_start {url}"
RTMP_STOP_COMMAND = "rtmp_video_stop"
RTMP_START_EXPECT = r"publish ready|Push Start"
RTMP_STOP_EXPECT = r"Push Stop|Stop requested"
RTMP_START_TIMEOUT = 8.0
RTMP_STOP_TIMEOUT = 8.0

# heartbeat 日志正则：板端 RTMP 发送侧的帧索引（代表编码+发送仍在进行）。
#
# 用裸匹配而非锚定前缀：固件日志格式已从 8 月的 "[RTMP] f_index = N" 变为 9 月的
# "I/App Rtmp: f_index = N"（f_len 可缺失，行前可能有 ANSI 残留），且前缀会被串口
# 分块截断（实测 p: f_index / Rtmp: f_index / 裸 f_index），锚定前缀必失配。
#
# 裸匹配安全前提（窗口隔离）：仅用于 rtmp 推流保持窗口内监听，该窗口内串口仅有
# Rtmp 一种 f_index（scenario 串行时序 photo -> video -> rtmp，video 的 Dfs 心跳在
# dfs_video_stop 后已停），故无前缀也不会误匹配其它模块的 f_index。
RTMP_HEARTBEAT_RE: Pattern = re.compile(r"f_index\s*=\s*\d+")
