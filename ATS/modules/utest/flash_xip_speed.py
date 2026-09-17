"""flash_xip_speed 模块：速率打印宽松判据 + 可选阈值校验（D4）。

默认只判「有速率打印」；``min_speed_kbs`` 为配置项，>0 时速率 < 阈值判 FAIL。
"""
import re

from ..base import register
from .base import UtestCaseModule
from ...drivers.utest import flash_xip_speed_commands as commands


@register("utest_flash_xip_speed")
class FlashXipSpeedModule(UtestCaseModule):
    testcase = commands.TESTCASE
    business_res = commands.BUSINESS_RES

    def _extra_missing(self, clean, cfg):
        """阈值校验（D4）：min_speed_kbs <= 0 不校验；>0 时速率低于阈值判缺失。"""
        try:
            min_kbs = float(cfg.get(commands.MIN_SPEED_KBPS_KEY, 0) or 0)
        except (TypeError, ValueError):
            return []
        if min_kbs <= 0:
            return []
        m = re.search(commands.SPEED_RE, clean or "")
        if not m:
            return []  # 速率打印缺失已由 business_res 兜底
        speed = int(m.group(1))
        if speed < min_kbs:
            return [f"flash xip 速率 {speed} KB/s < 阈值 {min_kbs:g} KB/s"]
        return []
