"""测试结果数据结构。

定义 ``Response``（单条命令的响应）、``TestResult``（单个测试用例的结果）等，
供通信层、模块层、编排层、报告层共用，避免循环依赖。
"""
from dataclasses import dataclass, field
from time import perf_counter
from typing import Optional


@dataclass
class Response:
    """单条串口命令的执行结果。

    Attributes:
        raw: 原始输出（含 ANSI，用于日志归档）。
        clean: 剥离 ANSI 后的输出（用于解析判定）。
        success: 判定结果（成功/失败）。
        elapsed_ms: 该命令耗时（毫秒）。
        matched: 正则匹配到的内容（如解析出的 IP 地址）。
        error: 异常信息（超时、串口断开等），无异常为 None。
    """
    raw: str = ""
    clean: str = ""
    success: bool = False
    elapsed_ms: int = 0
    matched: Optional[str] = None
    error: Optional[str] = None

    def __bool__(self) -> bool:
        """``if response:`` 直接判断 success，便于模块层写 ``if not cmd(...):``。"""
        return self.success


# 测试用例状态枚举（用字符串常量，避免引入 enum 依赖）
PASSED = "PASS"
FAILED = "FAIL"
SKIPPED = "SKIP"
ERROR = "ERROR"


@dataclass
class TestResult:
    """单个测试用例（或单个子项，如某一拍照模式）的执行结果。

    一个模块可产生多条 TestResult（如 PhotoModule 每个模式一条），
    也可只产生一条。报告层按 result 列表汇总。
    """
    name: str                        # 用例名（如 "wifi_join"、"photo[auto]"）
    module: str                      # 所属模块名
    status: str = FAILED             # PASS / FAIL / SKIP / ERROR
    elapsed_ms: int = 0              # 耗时
    message: str = ""                # 概要信息（通过/失败原因）
    detail: str = ""                 # 详细上下文（失败时的命令输出等）
    timestamp: str = ""              # 时间戳字符串（由 reporter 填）
    scenario: str = ""               # 所属场景名（scenario 层新增，默认空）
    cycle: int = 0                   # 所属 cycle 序号（loop 第几轮，默认 0）

    @property
    def passed(self) -> bool:
        return self.status == PASSED

    @property
    def skipped(self) -> bool:
        return self.status in (SKIPPED,)


class Timer:
    """简易计时器，用于测量命令/用例耗时。"""

    def __init__(self):
        self._start = 0.0

    def start(self) -> "Timer":
        self._start = perf_counter()
        return self

    def elapsed_ms(self) -> int:
        return int((perf_counter() - self._start) * 1000)
