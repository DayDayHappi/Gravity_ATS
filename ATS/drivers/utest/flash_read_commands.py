"""flash_read 业务判据（ADR-011 唯一来源）。

实测样例 res/utestlog.txt 中 flash_read 无任何业务输出（unit 名
``jx_flash_test_read_unit`` 之后直接 result 行）。

D5：暂无业务关键串，暂只判 result 行 PASSED（BUSINESS_RES 为空）。
本文件保留，未来固件补充日志后再在此加业务正则。
"""

TESTCASE = "flash_read"

# 业务关键串正则（D1 叠加：result 行 PASSED 前提下，全部命中才 PASS）。
# 暂空（D5）：只判 result 行。
BUSINESS_RES = []
