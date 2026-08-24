"""WiFi 模块：连接检测、扫描与连接。

成功判据（对齐实测日志字节）：
- check: ``ifconfig`` 输出中 ``ip address:`` 非 0.0.0.0 即已联网
- scan: 表头 ``SSID MAC security rssi chn Mbps`` + 至少 1 行数据
- join: ``Got IP address : <IP>``（注意 address 与冒号间有空格，冒号后有空格）

执行顺序：wifi_check -> wifi_scan -> wifi_join
- wifi_check 先 ifconfig 检测，若已有 IP（板子未下电仍连着），跳过 scan/join
- 否则 wifi_scan 扫描 AP，wifi_join 连接并获取 IP

职责定位（ADR-008）：
- wifi_check：状态检测器，prepare 内部使用（产出 ctx.evb_ip + ctx.wifi_ready），
  只检测不 scan/join，不作 normal task。
- wifi_scan / wifi_join：代码保留但退出 normal 默认流程（可复用于手动调试/未来场景）。
- 连接收敛由 prepare.wifi_connect（状态收敛器）完成。
"""
import re
import time

from .base import TestModule, register
from ..core import logger
from ..core.result import TestResult, Timer

# 扫描结果表头（实测 wifi_scan_connect.txt）
_SCAN_HEADER_RE = re.compile(r"SSID\s+MAC\s+security\s+rssi\s+chn\s+Mbps")
# 扫描数据行：<ssid> <mac:17> <security> <rssi:int> <chn:int> <mbps:int>
_SCAN_ROW_RE = re.compile(
    r"^(\S+)\s+([0-9a-fA-F:]{17})\s+(\S+)\s+(-?\d+)\s+(\d+)\s+(\d+)"
)
# 连接成功 + IP 提取（实测: "Got IP address : 10.1.90.71"）
_GOT_IP_RE = r"Got IP address\s*:\s*([0-9.]+)"
# ifconfig 中 IP 提取：默认接口 w0 的 "ip address: x.x.x.x"（非 0.0.0.0 才算联网）
_IFCONFIG_IP_RE = re.compile(r"ip address\s*:\s*(\d+\.\d+\.\d+\.\d+)")


def check_wifi_connected(console):
    """发 ifconfig 检测是否已联网（有非 0.0.0.0 的 IP）。

    Returns:
        IP 字符串（已联网）；None（未联网或检测失败）。
    """
    r = console.exec_sync("ifconfig", timeout=8.0)
    if not r.success:
        return None
    # 取所有 ip address，只要有任一非 0.0.0.0 即算已联网
    for m in _IFCONFIG_IP_RE.finditer(r.clean):
        ip = m.group(1)
        if ip != "0.0.0.0":
            return ip
    return None


@register("wifi_check")
class WifiCheckModule(TestModule):
    """WiFi 连接状态检测器（ADR-008：prepare 内部检测，不作 normal task）。

    只检测（ifconfig → 有无非 0.0.0.0 IP），产出 ctx.evb_ip + ctx.wifi_ready。
    不 scan / join / 改配置。
    """

    depends = []

    def run(self, ctx, console, params=None):
        timer = Timer().start()
        ip = check_wifi_connected(console)
        ctx.wifi_ready = bool(ip)
        if ip:
            ctx.skip_wifi = True
            ctx.evb_ip = ip
            res = self._pass(f"已联网，IP={ip}")
        else:
            res = self._pass("未联网")
        res.elapsed_ms = timer.elapsed_ms()
        return res


@register("wifi_scan")
class WifiScanModule(TestModule):
    """WiFi 扫描测试。"""

    depends = []

    def run(self, ctx, console, params=None):
        if getattr(ctx, "skip_wifi", False):
            return self._skip(f"WiFi 已连接（IP={ctx.evb_ip}），跳过扫描测试")
        timer = Timer().start()
        r = console.exec_sync("wifi scan", expect=_SCAN_HEADER_RE.pattern, timeout=15.0)
        if not r.success:
            return self._fail("扫描失败或无结果", detail=r.clean)
        # 解析 AP 列表
        aps = []
        for ln in r.clean.splitlines():
            m = _SCAN_ROW_RE.match(ln.strip())
            if m:
                aps.append({
                    "ssid": m.group(1), "mac": m.group(2),
                    "rssi": int(m.group(4)),
                })
        if not aps:
            return self._fail("未解析到任何 AP", detail=r.clean)
        weak = [a for a in aps if a["rssi"] < -70]
        msg = f"扫描到 {len(aps)} 个 AP"
        if weak:
            msg += f"（其中 {len(weak)} 个 RSSI<-70 信号弱）"
        ctx.scan_results = aps
        res = self._pass(msg)
        res.elapsed_ms = timer.elapsed_ms()
        return res


@register("wifi_join")
class WifiJoinModule(TestModule):
    """WiFi 连接测试。

    若 ctx 已有 evb_ip（wifi_check 检测到或交互连上），直接 SKIP。
    否则用 ctx.wifi_ssid / ctx.wifi_password 执行 join。
    """

    depends = []

    def run(self, ctx, console, params=None):
        if getattr(ctx, "skip_wifi", False) and getattr(ctx, "evb_ip", None):
            ssid_info = ctx.wifi_ssid or "未知SSID"
            return self._skip(f"WiFi 已连接 ({ssid_info}/{ctx.evb_ip})，跳过 join 测试")
        # 连接目标 ssid/password 属系统环境（system.yaml 的 wifi 段）
        sys_wifi = (getattr(ctx, "system_config", None) or {}).get("wifi", {}) or {}
        ssid = getattr(ctx, "wifi_ssid", None) or sys_wifi.get("default_ssid")
        pwd = getattr(ctx, "wifi_password", None) or sys_wifi.get("default_password", "")
        if not ssid:
            return self._fail("未配置 SSID")
        timer = Timer().start()
        r = console.exec_async(
            f"wifi join {ssid} {pwd}",
            expect=_GOT_IP_RE, send_timeout=5.0, result_timeout=30.0,
        )
        if not r.success or not r.matched:
            return self._fail(f"连接失败或未获取 IP ({ssid})", detail=r.clean)
        ctx.evb_ip = r.matched
        ctx.wifi_ssid = ssid
        time.sleep(5.0)  # 等 wifi join 后板子状态稳定，再发下一条命令
        res = self._pass(f"已连接 {ssid}，IP={r.matched}")
        res.elapsed_ms = timer.elapsed_ms()
        return res
