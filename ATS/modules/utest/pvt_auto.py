"""pvt_auto_test 模块：PVT0/PVT1 双通道 monitor 启动宽松判据（D7 纯存在类）。"""
from ..base import register
from .base import UtestCaseModule
from ...drivers.utest import pvt_auto_commands as commands


@register("utest_pvt_auto")
class PvtAutoModule(UtestCaseModule):
    testcase = commands.TESTCASE
    business_res = commands.BUSINESS_RES
