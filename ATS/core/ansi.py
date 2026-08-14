"""ANSI 转义序列剥离工具。

EVB 的 msh 输出带大量颜色码（如 ``\x1b[32m...\x1b[0m``），在正则匹配前必须先剥离，
否则关键字（如 ``Got IP address``）会被颜色码打断导致失配。

实测日志 ``res/*.txt`` 中的颜色码均为 CSI 序列（``ESC [ 参数 字母``），
本模块用一个正则一次性剥离所有 CSI 序列。
"""
import re

# CSI 序列: ESC [ 之后的 0~多个参数字节(数字/分号) + 一个终止字母
# 覆盖 SGR(颜色) \x1b[31m、\x1b[1;32m、光标移动 \x1b[K 等
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip(text: str) -> str:
    """剥离 ANSI CSI 转义序列。

    Args:
        text: 可能含 ANSI 转义的字符串。

    Returns:
        剥离后的纯文本。非 str 输入原样返回。
    """
    if not isinstance(text, str):
        return text
    return _ANSI_RE.sub("", text)


def clean_lines(text: str) -> list:
    """剥离 ANSI 后按行分割，兼容 CRLF/CR/LF 三种行结束符，去掉空行。

    用于命令响应的逐行解析。
    """
    if not text:
        return []
    plain = strip(text)
    # 统一 CR/CRLF -> LF 再分割
    plain = plain.replace("\r\n", "\n").replace("\r", "\n")
    return [ln for ln in plain.split("\n") if ln.strip()]
