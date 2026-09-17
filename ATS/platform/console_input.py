"""逐字符终端输入适配；平台库仅在进入对应后端时导入。"""
import os
import codecs
import sys
import time

IS_WINDOWS = os.name == "nt"


class KeyboardInput:
    """with 管理 POSIX 终端状态；read 返回字符、None(无输入)、空串(EOF)。"""

    def __init__(self, stream=None):
        self.stream = stream if stream is not None else sys.stdin
        self._old = None
        self._fd = None
        self._msvcrt = None
        self._pending = ""
        self._decoder = None

    def __enter__(self):
        if not self.stream.isatty():
            raise OSError("--terminal 需要交互终端(TTY)，请在 PowerShell/CMD/终端中直接运行")
        if IS_WINDOWS:
            import msvcrt
            self._msvcrt = msvcrt
        else:
            import termios
            import tty
            self._fd = self.stream.fileno()
            self._decoder = codecs.getincrementaldecoder(getattr(self.stream, "encoding", None) or "utf-8")("replace")
            self._old = termios.tcgetattr(self._fd)
            try:
                tty.setcbreak(self._fd)
            except BaseException:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
                self._old = None
                raise
        return self

    def read(self, timeout=0.1):
        if self._msvcrt is not None:
            deadline = time.monotonic() + max(0.0, timeout)
            while not self._msvcrt.kbhit():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                time.sleep(min(.02, remaining))
            ch = self._msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                self._msvcrt.getwch()  # 功能键/方向键的第二码，不发送给板端。
                return None
            return ch
        # 不把 select(fd) 与 TextIOWrapper.read(1) 混用：粘贴时后者预读的字符
        # 留在 Python 缓冲里，fd 已不可读，会导致剩余输入停住。直接读取 fd 并增量解码。
        import select
        deadline = time.monotonic() + max(0.0, timeout)
        while not self._pending:
            ready, _, _ = select.select([self._fd], [], [], max(0.0, deadline - time.monotonic()))
            if not ready:
                return None
            data = os.read(self._fd, 4096)
            if not data:
                return ""
            self._pending += self._decoder.decode(data)
        ch, self._pending = self._pending[0], self._pending[1:]
        return ch

    def __exit__(self, exc_type, exc, tb):
        if self._old is not None:
            import termios
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
            self._old = None
        return False
