"""WiFi 固件协议定义：命令、判据正则与超时的唯一维护位置。

本文件不发送串口、不连接网络、不读取 YAML，也不安排测试次数或时长。
"""
import re
from typing import Pattern

WIFI_IFCONFIG_COMMAND = "ifconfig"
WIFI_SCAN_COMMAND = "wifi scan"
WIFI_JOIN_COMMAND = "wifi join {ssid} {pwd}"

# 扫描结果表头（实测 wifi_scan_connect.txt）
WIFI_SCAN_HEADER_RE: Pattern = re.compile(r"SSID\s+MAC\s+security\s+rssi\s+chn\s+Mbps")
# 扫描数据行：<ssid> <mac:17> <security> <rssi:int> <chn:int> <mbps:int>
WIFI_SCAN_ROW_RE: Pattern = re.compile(
    r"^(\S+)\s+([0-9a-fA-F:]{17})\s+(\S+)\s+(-?\d+)\s+(\d+)\s+(\d+)"
)
# 连接成功 + IP 提取（实测: "Got IP address : 10.1.90.71"）
WIFI_GOT_IP_RE = r"Got IP address\s*:\s*([0-9.]+)"
# ifconfig 中 IP 提取：默认接口 w0 的 "ip address: x.x.x.x"（非 0.0.0.0 才算联网）
WIFI_IFCONFIG_IP_RE: Pattern = re.compile(r"ip address\s*:\s*(\d+\.\d+\.\d+\.\d+)")

WIFI_IFCONFIG_TIMEOUT = 8.0
WIFI_SCAN_TIMEOUT = 15.0
WIFI_JOIN_SEND_TIMEOUT = 5.0
WIFI_JOIN_RESULT_TIMEOUT = 30.0
