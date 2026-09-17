"""pvt_test 模块：single voltage/temperature/convenience 三行宽松判据（D7 纯存在类）。"""
from ..base import register
from .base import UtestCaseModule
from ...drivers.utest import pvt_commands as commands


@register("utest_pvt")
class PvtModule(UtestCaseModule):
    testcase = commands.TESTCASE
    business_res = commands.BUSINESS_RES
