"""FTP 固件协议定义：命令、判据、错误串、验证路径与超时的唯一维护位置。

本文件不发送串口、不连接 FTP、不读取 YAML，也不安排测试次数或时长。
"""
import re
from typing import Pattern

FTP_START_COMMAND = "ftp_server"
FTP_START_EXPECT = r"service launched success"
# 固件 FTP 崩溃循环刷屏标志（重发 ftp_server 会触发 "service go wrong, now wait
# restarting"）。当前业务仅文档化、未用于判定，此处作为协议唯一来源锚点。
FTP_GO_WRONG_RE: Pattern = re.compile(r"service go wrong")
FTP_START_TIMEOUT = 15.0

# FTP 连接验证目录（板端 eMMC 根目录）
_EMMC_DIR = "/emmc"
