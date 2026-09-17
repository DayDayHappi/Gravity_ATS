"""i2c_test 模块：5 个 sub-mode 严格判据（D7 值相等类，want==readback / expect==got）。"""
from ..base import register
from .base import UtestCaseModule
from ...drivers.utest import i2c_commands as commands


@register("utest_i2c")
class I2cModule(UtestCaseModule):
    testcase = commands.TESTCASE
    business_res = commands.BUSINESS_RES
