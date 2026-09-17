"""pvt_auto_test 业务判据（ADR-011 唯一来源）。

业务关键串来自实测样例 res/utestlog.txt（ANSI 剥离后）：

    PVT0 auto monitor started (irq=69)   # 出现 2 次
    PVT1 auto monitor started (irq=70)

宽松（D7 纯存在类）：PVT0 / PVT1 双通道 monitor 均启动。
"""

TESTCASE = "pvt_auto_test"

# 业务关键串正则（D1 叠加：result 行 PASSED 前提下，全部命中才 PASS）。
BUSINESS_RES = [
    r"PVT0\s+auto\s+monitor\s+started",
    r"PVT1\s+auto\s+monitor\s+started",
]
