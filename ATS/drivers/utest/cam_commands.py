"""cam_test 业务判据（ADR-011 唯一来源）。

业务关键串来自用户实测日志（ANSI 剥离后）：

    sif0  [0xf9000254]=0x0000030c (expect 0x0000030c) ok

同段另有 csi0 / ph yo0 / fe0 等寄存器 dump 行，但只有 sif0 行带
``(expect ...) ok``，故判据锚定 ``sif0 [...]=(...) (expect ...) ok`` 结构。

严格（D7 值相等类）：``<val> == expect`` 用同组回引 ``\\1`` 表达，
保证实测值与期望值相等才命中（用户拍板执行强校验）。
地址 ``0xf9000254`` 与期望值 ``0x0000030c`` 为该 case 固定值。
"""

TESTCASE = "cam_test"

# 业务关键串正则（D1 叠加：result 行 PASSED 前提下命中才 PASS）。
# 严格（D7 值相等类）：= <val> (expect <val>)，回引 \1 保证 val == expect。
BUSINESS_RES = [
    r"sif0\s+\[0xf9000254\]=(0x[0-9a-fA-F]+)\s+\(expect\s+\1\)\s+ok",
]
