"""i2c_test 业务判据（ADR-011 唯一来源）。

业务关键串来自实测样例 res/utestlog.txt（ANSI 剥离后）：

    i2c cpu wr: want 0x15 readback 0x15 PASS
    i2c irq wr: want 0x15 readback 0x15 PASS
    i2c dma wr: want 0x15 readback 0x15 PASS
    i2c dma transmit: want 0x15 readback 0x15 PASS
    i2c dma receive: expect 0x14 got 0x14 PASS

严格（D7 值相等类）：5 个 sub-mode 各一行且尾 PASS；
``want == readback``（receive 为 ``expect == got``）用同组回引表达。
"""

TESTCASE = "i2c_test"

# 业务关键串正则（D1 叠加：result 行 PASSED 前提下，全部命中才 PASS）。
BUSINESS_RES = [
    r"i2c\s+cpu\s+wr:\s*want\s+(0x[0-9a-fA-F]+)\s+readback\s+\1\s+PASS",
    r"i2c\s+irq\s+wr:\s*want\s+(0x[0-9a-fA-F]+)\s+readback\s+\1\s+PASS",
    r"i2c\s+dma\s+wr:\s*want\s+(0x[0-9a-fA-F]+)\s+readback\s+\1\s+PASS",
    r"i2c\s+dma\s+transmit:\s*want\s+(0x[0-9a-fA-F]+)\s+readback\s+\1\s+PASS",
    r"i2c\s+dma\s+receive:\s*expect\s+(0x[0-9a-fA-F]+)\s+got\s+\1\s+PASS",
]
