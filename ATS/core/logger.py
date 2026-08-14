"""日志系统。

两类输出：
1. **串口原始日志** ``logs/<run_ts>/serial.log`` —— 串口收发的每个字节，带毫秒时间戳，
   保留 ANSI 原始字节（便于问题回溯）。由 ``SerialConsole`` 的常驻读线程调用 ``log_serial`` 写入。
2. **运行日志 + 控制台** ``logs/<run_ts>/run.log`` + stdout —— 框架/模块的运行轨迹和
   测试进度（``[PASS]/[FAIL]``），同时写文件和控制台。

设计为单例风格：``get_logger()`` 返回全局实例，各层共用，避免传参耦合。
"""
import os
import sys
import datetime as _dt

_RUN_TS = None          # 本次运行时间戳（目录名）
_LOG_DIR = None         # 本次运行日志目录
_SERIAL_FP = None       # serial.log 文件句柄
_RUN_FP = None          # run.log 文件句柄
_VERBOSE = False        # 详细模式


def _now() -> str:
    """当前时间字符串，精确到毫秒。"""
    return _dt.datetime.now().strftime("%H:%M:%S.") + "%03d" % (
        _dt.datetime.now().microsecond // 1000
    )


def init_logger(log_root: str, verbose: bool = False) -> str:
    """初始化本次运行的日志目录。

    Args:
        log_root: 日志根目录（如 ``logs``），会在其下创建时间戳子目录。
        verbose: 是否输出详细（DEBUG 级）日志到控制台。

    Returns:
        本次运行的时间戳（用作 reports/logs 子目录名）。
    """
    global _RUN_TS, _LOG_DIR, _VERBOSE
    _RUN_TS = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    _LOG_DIR = os.path.join(log_root, _RUN_TS)
    os.makedirs(_LOG_DIR, exist_ok=True)
    _VERBOSE = verbose
    _open_files()
    return _RUN_TS


def _open_files():
    global _SERIAL_FP, _RUN_FP
    _SERIAL_FP = open(os.path.join(_LOG_DIR, "serial.log"), "w", encoding="utf-8", errors="replace")
    _RUN_FP = open(os.path.join(_LOG_DIR, "run.log"), "w", encoding="utf-8", errors="replace")


def log_serial(direction: str, data: str):
    """写一行串口日志。

    Args:
        direction: ``"TX>"``（发送）或 ``"RX<"``（接收）。
        data: 本次收发的文本（可含多行，已按需拼接）。
    """
    if _SERIAL_FP is None:
        return
    ts = _now()
    # data 可能多行，每行都加前缀，便于对齐阅读
    for line in data.splitlines() or [""]:
        _SERIAL_FP.write(f"[{ts}] {direction} {line}\n")
    _SERIAL_FP.flush()


def log_serial_raw(direction: str, data: bytes):
    """写串口原始字节（解码失败时用 repr 保底，绝不丢字节）。"""
    if _SERIAL_FP is None:
        return
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        text = repr(data)
    log_serial(direction, text)


def _write_run(level: str, msg: str, to_console: bool):
    if _RUN_FP is not None:
        _RUN_FP.write(f"[{_now()}] [{level}] {msg}\n")
        _RUN_FP.flush()
    if to_console:
        print(f"[{level}] {msg}", flush=True)


def info(msg: str, to_console: bool = True):
    _write_run("INFO", msg, to_console)


def debug(msg: str):
    """详细日志，仅在 verbose 模式输出到控制台，但始终写文件。"""
    _write_run("DEBUG", msg, _VERBOSE)


def warn(msg: str, to_console: bool = True):
    _write_run("WARN", msg, to_console)


def error(msg: str, to_console: bool = True):
    _write_run("ERROR", msg, to_console)


def step(msg: str):
    """测试步骤提示（不带级别前缀，控制台醒目）。"""
    if _RUN_FP is not None:
        _RUN_FP.write(f"[{_now()}] {msg}\n")
        _RUN_FP.flush()
    print(msg, flush=True)


def result_line(status: str, name: str, elapsed_ms: int, msg: str = ""):
    """控制台打印一行测试结果，带颜色。"""
    color = {
        "PASS": "\033[32m",   # 绿
        "FAIL": "\033[31m",   # 红
        "SKIP": "\033[33m",   # 黄
        "ERROR": "\033[35m",  # 紫
    }.get(status, "")
    reset = "\033[0m"
    line = f"[{color}{status}{reset}] {name} ({elapsed_ms}ms)"
    if msg:
        line += f" - {msg}"
    if _RUN_FP is not None:
        # 文件里不写颜色码
        _RUN_FP.write(f"[{_now()}] [{status}] {name} ({elapsed_ms}ms) - {msg}\n")
        _RUN_FP.flush()
    print(line, flush=True)


def close():
    global _SERIAL_FP, _RUN_FP
    if _SERIAL_FP:
        _SERIAL_FP.close()
        _SERIAL_FP = None
    if _RUN_FP:
        _RUN_FP.close()
        _RUN_FP = None


def log_dir() -> str:
    return _LOG_DIR or ""


def run_ts() -> str:
    return _RUN_TS or ""
