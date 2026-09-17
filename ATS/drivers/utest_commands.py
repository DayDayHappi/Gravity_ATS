"""utest 固件自检协议定义：命令、判据、超时映射的唯一维护位置。

本文件不发送串口、不连接网络/FTP、不读取 YAML，也不安排测试项或时长。
协议来源：ADR-012 + 实测样例 ``res/utestlog.txt``。

固件 utest 统一日志框架（剥离 ANSI 后）的关键结构：

    [I/utest] [----------] [ testcase ] (<name>) started
        ... 各 testcase 特有的业务单元输出 ...
    [I/utest] [  PASSED  ] [ result   ] testcase (<name>)   ★ 唯一可靠判据
    [I/utest] [----------] [ testcase ] (<name>) finished
    [I/utest] [==========] [ utest    ] finished

唯一判据 = testcase 级 result 行（固件已汇总单元结果），不扫 unit 级业务输出、
不扫 ``fail``/``error`` 关键字（``qspi_test`` 的 ``1 lane fail!`` 是合法中间态，
最终 testcase 仍 PASSED）。
"""
from types import MappingProxyType
from typing import Mapping

# utest_list（本期不做，仅预留命令常量，见 ADR-012 Decision 6）
UTEST_LIST_COMMAND = "utest_list"

# 跑单个 testcase（同步阻塞命令，跑完才回 msh）
UTEST_RUN_COMMAND = "utest_run {name}"

# testcase 级 result 行正则：捕获 (status, name)。这是唯一业务判据。
# 显式传 exec_sync 的 expect，同时避开 serial_console 默认 _ERROR_RE 兜底，
# 解决 qspi_test 的 "1 lane fail!" 被误判。
# 状态枚举 PASSED|FAILED|ERROR|SKIPPED 为预留接口：当前仅 PASSED 有实测样例，
# FAILED/ERROR/SKIPPED 的 result 行确切格式待真机补充。
UTEST_RESULT_RE = (
    r"\[\s*(?P<status>PASSED|FAILED|ERROR|SKIPPED)\s*\]"
    r"\s*\[ result\s+\]\s*testcase\s*\(\s*(?P<name>\w+)\s*\)"
)

# 兜底：识别任意 status 的 result 行（status 用 \S+ 宽松捕获）。
# 仅用于区分「result 行存在但状态未知 → ERROR」与「无 result 行 → FAIL」。
# 注意：要求 ``testcase (<name>)``，因此不会命中 utest 级汇总行
# ``[  PASSED  ] [ result   ] 1 tests.``。
UTEST_RESULT_ANY_RE = (
    r"\[\s*(?P<status>\S+)\s*\]"
    r"\s*\[ result\s+\]\s*testcase\s*\(\s*(?P<name>\w+)\s*\)"
)

# 每个 testcase 独立脚本超时（秒）= 固件 run timeout + 脚本余量（ADR-012 表）。
# 固件 run timeout 来自实测 ``utest_list`` 的 ``[run timeout]:N``，此处不重复其值，
# 只维护脚本侧最终等待值；scenario 的 override.timeout 可单项覆盖。
UTEST_TESTCASES: Mapping[str, float] = MappingProxyType({
    # 固件 run timeout 1s 组 → 脚本 10s
    "efuse_test": 10.0,
    "filesystem": 10.0,
    "imu_test": 10.0,
    "pvt_test": 10.0,
    # 固件 run timeout 10s 组 → 脚本 20s
    "i2c_test": 20.0,
    "flash_read": 20.0,
    "qspi_test": 20.0,
    # pvt_auto_test 固件 run timeout 标 1s，但真机实测跑约 10.2s（超脚本 10s），
    # 脚本超时提为 20s（与 i2c 组对齐）。
    "pvt_auto_test": 20.0,
    # 固件 run timeout 30s 组 → 脚本 40s
    "flash_xip_speed": 40.0,
})


class UnknownTestcaseError(ValueError):
    """请求的 testcase 不在 UTEST_TESTCASES 映射内，且未提供 timeout 覆盖。"""


def script_timeout_for(testcase: str) -> float:
    """返回某 testcase 的脚本侧默认超时；未知 testcase 抛 UnknownTestcaseError。

    只做查表，不做覆盖合并；override.timeout 由业务侧自行解析。
    """
    timeout = UTEST_TESTCASES.get(testcase)
    if timeout is None:
        known = ", ".join(UTEST_TESTCASES)
        raise UnknownTestcaseError(
            f"未知 utest testcase: {testcase!r}（已知: {known}）"
        )
    return timeout
