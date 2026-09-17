"""efuse_test 模块：EFUSE uart_baud / flash_vendor 两条严格判据（D7 值相等类）。"""
from ..base import register
from .base import UtestCaseModule
from ...drivers.utest import efuse_commands as commands


@register("utest_efuse")
class EfuseModule(UtestCaseModule):
    testcase = commands.TESTCASE
    business_res = commands.BUSINESS_RES
