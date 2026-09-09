"""固件关键错误串 ``TT ERROR`` 检测器（listener 模式，复用 rtmp_monitor 同款机制）。

职责：订阅串口原始数据，检测固件关键错误串 ``TT ERROR``。命中**不判 FAIL**，
只在模块最终 ``TestResult.detail`` 里标注命中次数与命中文本；cycle / rep 由 runner
统一填写，本检测器不关心。

与 RTMPMonitor 的区别：RTMPMonitor 做「超时判定」输出 ALIVE/TIMEOUT 状态；本检测器
只做「命中收集」，是否影响结果由调用模块自行决定（当前需求：不影响 status）。

跨 chunk 拼接：串口读线程可能把一行日志分块送达（f_index 被截断的同款问题），
``TT ERROR`` 仅 8 字节、易被分块切断。仅当本次 chunk 以 ``TT ERROR`` 的截断前缀
（``TT`` / ``TT ` / ``TT E`` / ``TT ER`` / ``TT ERR`` / ``TT ERRO``）结尾时，才把该
前缀保留到下次拼接，避免把已命中的整行尾巴混入下一行造成命中文本污染。
"""
import re

# 严格匹配：含空格、大写、无引号。命中 TT ERROR（固件关键错误日志行）。
_TT_ERROR_RE = re.compile(r"TT ERROR")

# ANSI 转义序列（命中行展示前剥离，避免报告乱码）。
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# "TT ERROR" 的跨 chunk 截断前缀（按长度降序，命中最长匹配）。
_SPLICE_TAILS = ("TT ERRO", "TT ERR", "TT ER", "TT E", "TT ", "TT")


class TTErrorMonitor:
    """``TT ERROR`` 命中收集器。"""

    def __init__(self):
        self._hits = []    # 命中文本（去 ANSI 后 strip；跨 chunk 时为拼接还原后的那一行）
        self._tail = ""    # 上次 chunk 末尾的截断前缀（仅当结尾是 "TT ERROR" 前缀时非空）

    def update(self, text):
        """``console.add_listener`` 回调（读线程调用）。仅正则匹配 + 追加，极轻量。"""
        if not text:
            return
        buf = self._tail + text
        self._hits.extend(self._extract_hits(buf))
        self._tail = self._splice_tail(text)

    @staticmethod
    def _extract_hits(buf):
        """对 buf 中每个 ``TT ERROR`` 命中，取所在行（\\n 分割）作为命中文本。"""
        out = []
        for m in _TT_ERROR_RE.finditer(buf):
            line_start = buf.rfind("\n", 0, m.start()) + 1
            line_end = buf.find("\n", m.end())
            if line_end == -1:
                line_end = len(buf)
            line = buf[line_start:line_end]
            out.append(_ANSI_RE.sub("", line).strip())
        return out

    @staticmethod
    def _splice_tail(text):
        """若 text 结尾是 ``TT ERROR`` 的截断前缀，返回该前缀，否则返回空串。"""
        stripped = text.rstrip("\r\n")
        for tail in _SPLICE_TAILS:
            if stripped.endswith(tail):
                return tail
        return ""

    def get_hits(self):
        """返回命中文本列表（第 i 次命中 = get_hits()[i-1]）。"""
        return self._hits

    def clear(self):
        """清空命中（跨 rep 复用实例时调用）。"""
        self._hits = []
        self._tail = ""
