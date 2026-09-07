"""Cross-platform interactive serial terminal for manual EVB diagnostics.

The command-response engine remains in :mod:`ATS.core.serial_console`; this
presentation tool uses a raw terminal session because users need continuous
RX display and manual TX control.
"""
from __future__ import annotations

import sys
import threading

from ATS.core import logger
from ATS.core.ansi import strip as ansi_strip
from ATS.core.serial_console import SerialError, detect_port
from ATS.drivers.serial_terminal_session import SerialTerminalSession
from ATS.platform.console_input import create_console_key_reader

_GREEN = "\033[32m"
_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"
_EXIT_CMDS = {"exit", "quit", ":q"}


def run_terminal(port, baudrate, strip_ansi=True, *, session_factory=SerialTerminalSession):
    """Run an Xcom-like terminal on Linux or Windows and release the port on exit."""
    state = {"strip_ansi": bool(strip_ansi), "stop": False}
    print_lock = threading.Lock()
    session = session_factory()

    def print_rx(text):
        if not text:
            return
        display = ansi_strip(text) if state["strip_ansi"] else text
        with print_lock:
            for index, line in enumerate(display.split("\n")):
                if index:
                    sys.stdout.write("\n")
                if line:
                    sys.stdout.write(f"{_CYAN}RX<{_RESET} {line}")
            sys.stdout.flush()

    def print_status(message):
        with print_lock:
            sys.stdout.write(f"\r{_YELLOW}{message}{_RESET}\n")
            sys.stdout.flush()

    session.add_listener(print_rx)
    try:
        session.open(str(port), int(baudrate))
    except Exception as exc:
        print(f"[错误] 打开串口 {port} 失败: {exc}", file=sys.stderr)
        return 2

    print(f"\n{_YELLOW}════════ 交互式串口终端 ════════{_RESET}")
    print(f"  端口: {port}  波特率: {baudrate}")
    print(f"  ANSI 剥离: {'开' if state['strip_ansi'] else '关'}（Tab 切换）")
    print(f"  {_DIM}回车=发送  Tab=切换ANSI  Ctrl+C 或 exit=退出{_RESET}")
    print(f"{_YELLOW}══════════════════════════════{_RESET}\n")

    buffer = ""
    try:
        with create_console_key_reader() as reader:
            while not state["stop"]:
                char = reader.read_key()
                if not char:
                    if char == "":
                        continue
                    break
                if char == "\x03":
                    break
                if char == "\t":
                    state["strip_ansi"] = not state["strip_ansi"]
                    print_status(f"[ANSI 剥离: {'开' if state['strip_ansi'] else '关'}]")
                    with print_lock:
                        sys.stdout.write(f"{_DIM}> {_RESET}{buffer}")
                        sys.stdout.flush()
                    continue
                if char in ("\r", "\n"):
                    line = buffer
                    buffer = ""
                    with print_lock:
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                    if line.strip().lower() in _EXIT_CMDS:
                        break
                    if line:
                        with print_lock:
                            sys.stdout.write(f"\r{_GREEN}TX>{_RESET} {line}\n")
                            sys.stdout.flush()
                        try:
                            session.send(line)
                        except Exception as exc:
                            print_status(f"[发送失败] {exc}")
                    continue
                if char in ("\x7f", "\x08"):
                    if buffer:
                        buffer = buffer[:-1]
                        with print_lock:
                            sys.stdout.write("\b \b")
                            sys.stdout.flush()
                    continue
                buffer += char
                with print_lock:
                    sys.stdout.write(char)
                    sys.stdout.flush()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        state["stop"] = True
        session.close()
        print(f"\n{_YELLOW}已退出串口终端，串口已释放。{_RESET}")
    return 0


def run_from_args(args, config, interaction_provider=None):
    """Resolve configured/auto-detected port and launch the raw terminal."""
    serial_cfg = config.get("serial", {}) if config else {}
    port = args.port or serial_cfg.get("port", "auto")
    baudrate = args.baudrate or serial_cfg.get("baudrate", 2_000_000)
    if port in ("auto", "", None):
        logger.info("自动探测 EVB 串口...")
        try:
            port, detected_baud = detect_port(
                baudrate=baudrate,
                baud_candidates=serial_cfg.get("baudrate_candidates"),
                interactive=True,
                detect_timeout=serial_cfg.get("detect_timeout", 2.0),
                interaction_provider=interaction_provider,
            )
        except SerialError as exc:
            print(f"[错误] {exc}", file=sys.stderr)
            return 2
        if port is None:
            print("[错误] 无法确定 EVB 串口", file=sys.stderr)
            return 2
        baudrate = detected_baud
    return run_terminal(port, baudrate, strip_ansi=not getattr(args, "raw", False))
