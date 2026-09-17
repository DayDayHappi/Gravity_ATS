"""flash_xip_speed 业务判据（ADR-011 唯一来源）。

业务关键串来自实测样例 res/utestlog.txt（ANSI 剥离后）：

    flash xip read speed: 6826 KB/s (size=1024 KB, time=150 ms)

宽松（D7 纯存在类）：命中速率打印即通过；阈值 ``min_speed_kbs`` 为配置项，
默认 0（不校验），>0 时才比对速率下限（D4）。
"""

TESTCASE = "flash_xip_speed"

# 速率打印正则（捕获 KB/s 数值）。
SPEED_RE = r"flash\s+xip\s+read\s+speed:\s*(\d+)\s*KB/s"

# 业务关键串正则（D1 叠加：result 行 PASSED 前提下，全部命中才 PASS）。
BUSINESS_RES = [SPEED_RE]

# 阈值配置项 key（config/modules/utest.yaml），默认 0 = 不校验（D4）。
MIN_SPEED_KBPS_KEY = "min_speed_kbs"
