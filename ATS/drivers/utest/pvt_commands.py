"""pvt_test 业务判据（ADR-011 唯一来源）。

业务关键串来自实测样例 res/utestlog.txt（ANSI 剥离后）：

    PVT single voltage: 0.783V
    PVT single temperature: 35.115C
    PVT convenience: vol=0.778V, temp=34.878C

宽松（D7 纯存在类）：三行均出现。
"""

TESTCASE = "pvt_test"

# 业务关键串正则（D1 叠加：result 行 PASSED 前提下，全部命中才 PASS）。
BUSINESS_RES = [
    r"PVT\s+single\s+voltage:",
    r"PVT\s+single\s+temperature:",
    r"PVT\s+convenience:",
]
