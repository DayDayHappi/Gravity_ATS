"""filesystem 模块：mount/write/read 三行宽松判据（D7 纯存在类）。"""
from ..base import register
from .base import UtestCaseModule
from ...drivers.utest import filesystem_commands as commands


@register("utest_filesystem")
class FilesystemModule(UtestCaseModule):
    testcase = commands.TESTCASE
    business_res = commands.BUSINESS_RES
