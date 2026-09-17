"""imu_test 模块：collected n/n frames 严格判据（D7 值相等类，帧数完整）。"""
from ..base import register
from .base import UtestCaseModule
from ...drivers.utest import imu_commands as commands


@register("utest_imu")
class ImuModule(UtestCaseModule):
    testcase = commands.TESTCASE
    business_res = commands.BUSINESS_RES
