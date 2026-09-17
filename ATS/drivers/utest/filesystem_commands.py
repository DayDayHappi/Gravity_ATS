"""filesystem 业务判据（ADR-011 唯一来源）。

业务关键串来自实测样例 res/utestlog.txt（ANSI 剥离后）：

    [I/utest] emmc card mount to /emmc is success
    [I/utest] Elm filesystem write test data is success!
    [I/utest] Elm filesystem read test data is success!

宽松（D7 纯存在类）：mount + write + read 三行均出现。
注意 ``[I/DFS.fs] the path:/emmc is not a mountpoint!`` 是 mount 前合法中间态，
绝不算失败——本文件只列白名单正判据，不扫关键字。
"""

TESTCASE = "filesystem"

# 业务关键串正则（D1 叠加：result 行 PASSED 前提下，全部命中才 PASS）。
BUSINESS_RES = [
    r"emmc card mount to /emmc is success",
    r"Elm filesystem write test data is success",
    r"Elm filesystem read test data is success",
]
