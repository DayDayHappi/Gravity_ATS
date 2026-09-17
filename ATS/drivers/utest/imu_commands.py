"""imu_test 业务判据（ADR-011 唯一来源）。

业务关键串来自实测样例 res/utestlog.txt（ANSI 剥离后）：

    imu[N]: irq=M G(...)mDPS A(...)ug T=...   ×50 行
    IMU: collected 50/50 frames, irq 73->122

严格（D7 值相等类）：``collected <n>/<n> frames`` 帧数完整（分子分母相等），
用同组回引表达；不硬编码 50，帧数变化仍适用。
"""

TESTCASE = "imu_test"

# 业务关键串正则（D1 叠加：result 行 PASSED 前提下，全部命中才 PASS）。
BUSINESS_RES = [
    # collected n/n frames：回引 \1 保证收集帧数 == 总帧数（帧数完整）
    r"IMU:\s*collected\s+(\d+)/(\1)\s+frames",
]
