"""flash_read 模块：暂无业务关键串，暂只判 result 行 PASSED（D5）。"""
from ..base import register
from .base import UtestCaseModule
from ...drivers.utest import flash_read_commands as commands


@register("utest_flash_read")
class FlashReadModule(UtestCaseModule):
    testcase = commands.TESTCASE
    business_res = commands.BUSINESS_RES  # 空列表（D5）
