"""efuse_test 业务判据（ADR-011 唯一来源）。

业务关键串来自实测样例 res/utestlog.txt（ANSI 剥离后）：

    EFUSE uart_baud[63:32] = 0x000f4240 (expect 0x000f4240)
    EFUSE flash_vendor[15:14] = 0x1 (expect 0x1)

严格（D7 值相等类）：``<val> == expect`` 用同组回引正则表达。
"""

TESTCASE = "efuse_test"

# 业务关键串正则（D1 叠加：result 行 PASSED 前提下，全部命中才 PASS）。
BUSINESS_RES = [
    # uart_baud：= <val> (expect <val>)，回引 \1 保证 val == expect
    r"EFUSE\s+uart_baud\[[^\]]*\]\s*=\s*(0x[0-9a-fA-F]+)\s*\(expect\s*\1\)",
    # flash_vendor：= <val> (expect <val>)，回引 \1 保证 val == expect
    r"EFUSE\s+flash_vendor\[[^\]]*\]\s*=\s*(0x[0-9a-fA-F]+)\s*\(expect\s*\1\)",
]
