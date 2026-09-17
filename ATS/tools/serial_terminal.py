"""交互式串口终端（类 Xcom 串口助手）。

用途：人工手动发串口命令、实时查看板子返回，用于调试（如 RTMP 推流命令行为探查）。
脚本不代发、不解析、不判定，全程由用户操作。

启动：``python3 -m ATS.main --terminal``（复用配置的串口参数与自动探测）。

交互：
- 敲命令 + 回车 -> 发送到板子（自动补 ``\\n``），屏幕以 ``TX>``（绿）显示
- 板子返回实时以 ``RX<`` 显示
- Tab 切换 ANSI 颜色码剥离 / 原始显示
- Ctrl+C 或输入 ``exit``/``quit`` 退出

实现：直接用 pyserial（独立于 ``SerialConsole`` 类，因那是命令-响应模型，不适合实时交互），
复用 ``detect_port``（自动探测）和 ``ansi.strip``（剥离转义）两个纯函数。
"""
import sys
import os
import threading
from ..platform.console_input import KeyboardInput

try:
    import serial
except ImportError:  # pragma: no cover
    serial = None

from ..core import logger
from ..core.ansi import strip as ansi_strip
from ..core.serial_console import detect_port, SerialError

# 颜色码
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"

# 退出命令
_EXIT_CMDS = {"exit", "quit", ":q"}


def run_terminal(port, baudrate, strip_ansi=True):
    """跨平台终端入口；非 TTY、初始化异常、中断均不遗留串口资源。"""
    try:
        with KeyboardInput() as keyboard:
            return _run_session(port, baudrate, strip_ansi, keyboard)
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2


def _run_session(port, baudrate, strip_ansi, keyboard):
    """运行交互式串口终端。

    Args:
        port: 串口设备路径。
        baudrate: 波特率。
        strip_ansi: 初始是否剥离 ANSI 转义码。

    Returns:
        int 退出码（0 正常退出）。
    """
    if serial is None:
        print("[错误] 缺少 pyserial 依赖，请先 pip install pyserial", file=sys.stderr)
        return 2

    # 打开和重置任一步失败都要关闭已获取的句柄。
    ser = None
    try:
        ser = serial.Serial(port, baudrate, timeout=0.1, write_timeout=2.0)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
    except BaseException as e:
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        if not isinstance(e, Exception):
            raise
        print(f"[错误] 打开串口 {port} 失败: {e}", file=sys.stderr)
        return 2

    # 共享状态
    state = {
        "strip_ansi": strip_ansi,  # Tab 切换
        "stop": False,
        "error": False,
    }
    print_lock = threading.Lock()

    def _print_rx(text):
        """读线程：把板子返回打到屏幕（带 RX< 前缀，流式不强制换行）。"""
        if not text:
            return
        with print_lock:
            # 按行输出，每行加 RX< 前缀；末尾不完整行保留不补换行
            lines = text.split("\n")
            for i, ln in enumerate(lines):
                if i > 0:
                    sys.stdout.write("\n")
                if ln:
                    sys.stdout.write(f"{_CYAN}RX<{_RESET} {ln}")
            sys.stdout.flush()

    def _print_tx(line):
        """主线程：显示用户发送的命令（TX> 绿色）。"""
        with print_lock:
            sys.stdout.write(f"\r{_GREEN}TX>{_RESET} {line}\n")
            sys.stdout.flush()

    def _print_status(msg):
        with print_lock:
            sys.stdout.write(f"\r{_YELLOW}{msg}{_RESET}\n")
            sys.stdout.flush()

    def _reader_loop():
        """读线程：循环读串口，实时打屏。"""
        while not state["stop"]:
            try:
                data = ser.read(4096)
            except Exception as exc:
                if not state["stop"]:
                    state["error"] = True
                    state["stop"] = True
                    _print_status(f"[串口断开或读取失败] {exc}")
                break
            if not data:
                continue
            text = data.decode("utf-8", "ignore")
            if state["strip_ansi"]:
                text = ansi_strip(text)
            _print_rx(text)

    reader = threading.Thread(target=_reader_loop, name="terminal-reader", daemon=True)

    print(f"\n{_YELLOW}════════ 交互式串口终端 ════════{_RESET}")
    print(f"  端口: {port}  波特率: {baudrate}")
    print(f"  ANSI 剥离: {'开' if state['strip_ansi'] else '关'}（Tab 切换）")
    print(f"  {_DIM}回车=发送  Tab=切换ANSI  Ctrl+C 或 exit=退出{_RESET}")
    print(f"{_YELLOW}══════════════════════════════{_RESET}\n")

    reader.start()

    buf = ""
    try:
        while not state["stop"]:
            ch = keyboard.read(timeout=0.1)
            if ch is None:
                continue
            if not ch:
                break
            # Ctrl+C
            if ch in ("\x03", "\x04"):
                break
            # Tab: 切换 ANSI 剥离
            if ch == "\t":
                state["strip_ansi"] = not state["strip_ansi"]
                _print_status(
                    f"[ANSI 剥离: {'开' if state['strip_ansi'] else '关'}]")
                # 刷新当前输入行（cbreak 下 Tab 不回显，补显当前 buf）
                with print_lock:
                    sys.stdout.write(f"{_DIM}> {_RESET}{buf}")
                    sys.stdout.flush()
                continue
            # 回车: 发送命令
            if ch in ("\r", "\n"):
                line = buf
                buf = ""
                # 换行显示
                with print_lock:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                if line.strip().lower() in _EXIT_CMDS:
                    break
                if line:
                    _print_tx(line)
                    try:
                        ser.write((line + "\n").encode("utf-8"))
                        ser.flush()
                    except Exception as e:
                        _print_status(f"[发送失败] {e}")
                continue
            # 退格: 删一个字符
            if ch in ("\x7f", "\x08"):
                if buf:
                    buf = buf[:-1]
                    with print_lock:
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                continue
            # 普通字符: 累积 + 回显
            buf += ch
            with print_lock:
                sys.stdout.write(ch)
                sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        state["stop"] = True
        try:
            reader.join(timeout=1.0)
        except Exception:
            pass
        try:
            ser.close()
        except Exception:
            pass
        print(f"\n{_YELLOW}已退出串口终端，串口已释放。{_RESET}")
    return 1 if state["error"] else 0


def run_from_args(args, config):
    """从 CLI 参数 + 配置解析串口参数，运行终端。

    复用配置的自动探测逻辑（port=auto 时调 detect_port）。
    """
    ser_cfg = config.get("serial", {}) if config else {}
    port = args.port or ser_cfg.get("port", "auto")
    baudrate = args.baudrate or ser_cfg.get("baudrate", 2000000)

    if port in ("auto", "", None):
        logger.info("自动探测 EVB 串口...")
        try:
            port, detected_baud = detect_port(
                baudrate=baudrate,
                baud_candidates=ser_cfg.get("baudrate_candidates"),
                interactive=True,
                detect_timeout=ser_cfg.get("detect_timeout", 2.0),
            )
        except SerialError as e:
            print(f"[错误] {e}", file=sys.stderr)
            return 2
        if port is None:
            print("[错误] 无法确定 EVB 串口", file=sys.stderr)
            return 2
        baudrate = detected_baud

    return run_terminal(port, baudrate, strip_ansi=not getattr(args, "raw", False))
