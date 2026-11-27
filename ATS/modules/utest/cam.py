"""cam_test 模块：sif0 寄存器 IRQ 状态业务判据（ADR-011/ADR-012）。"""
from ..base import register
from .base import UtestCaseModule
from ...drivers.utest import cam_commands as commands


@register("utest_cam")
class CamModule(UtestCaseModule):
    testcase = commands.TESTCASE
    business_res = commands.BUSINESS_RES
