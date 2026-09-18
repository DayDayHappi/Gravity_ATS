"""固件关键字符串命中检测器（listener 模式，复用 rtmp_monitor 同款机制）。

职责：订阅串口原始数据，按传入的 ``DetectString``（唯一来源 ``drivers/detect_strings.py``）
检测关键字符串命中。命中**不判 FAIL**，只在模块最终 ``TestResult.detail`` 里标注命中
次数与命中文本；cycle / rep 由 runner 统一填写，本检测器不关心。

与 RTMPMonitor 的区别：RTMPMonitor 做「超时判定」输出 ALIVE/TIMEOUT 状态；本检测器
只做「命中收集」，是否影响结果由调用模块自行决定（当前需求：不影响 status）。

跨 chunk 拼接：串口读线程可能把一行日志分块送达（f_index 被截断的同款问题），关键
字符串（如 ``TT ERROR`` 仅 8 字节）易被分块切断。仅当本次 chunk 以某字面 pattern 的
截断前缀结尾时，才把该前缀保留到下次拼接，避免把已命中的整行尾巴混入下一行造成命中
文本污染。

截断前缀由字面 pattern **自动推导**（全部非空真前缀按长度降序，单字符前缀除外，与
历史 ``_SPLICE_TAILS`` 从 ``"TT"`` 起一致）。该推导仅对纯字面串成立；含正则元字符的
pattern 降级为「不跨 chunk 拼接」，届时由 ``detect_strings.py`` 定义处标注处理方式。
"""
import re

from ..drivers.detect_strings import DetectString, DETECT_STRINGS

# ANSI 转义序列（命中行展示前剥离，避免报告乱码）。
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# 正则元字符：用于判断 pattern 是否纯字面串（纯字面串才可安全做跨 chunk 前缀拼接）。
_RE_META = re.compile(r"[\\\[\](){}.^*+?$|]")


def build_monitor(detect_strings_keys):
    """按配置选择键列表构造 ``StringHitMonitor``（业务接线的公共入口）。

    Args:
        detect_strings_keys: ``DetectString.key`` 列表（来自 modules yaml 的
            ``detect_strings`` 字段）。未配置/空列表 → 返回 ``None``（不检测，
            代码层不兜底默认）。

    Returns:
        ``StringHitMonitor`` 实例；无有效选择时返回 ``None``。

    Raises:
        KeyError: 选择键在 ``DETECT_STRINGS`` 中不存在（配置错误，显式报出，不做
            静默忽略，否则检测会静默失效）。
    """
    if not detect_strings_keys:
        return None
    items = [DETECT_STRINGS[key] for key in detect_strings_keys]
    return StringHitMonitor(items)


def _derive_splice_tails(pattern: str) -> tuple:
    """按字面 pattern 推导跨 chunk 截断前缀（长度降序）。

    - 仅对纯字面串成立：pattern 不含任何正则元字符。含元字符（如 ``\\s*``、``\\d+``）
      无法按字面前缀拼接，返回空元组，降级为「不跨 chunk 拼接」（接受低概率漏检），
      由 ``detect_strings.py`` 定义处显式标注。
    - 单字符真前缀不参与拼接：与历史 ``_SPLICE_TAILS``（最短 ``"TT"``）一致，避免把
      无关的单个字母误当截断前缀。
    """
    if _RE_META.search(pattern):
        return ()
    # range(len-1, 1, -1) 生成 len-1 .. 2，对应 pattern[:len-1] .. pattern[:2]，
    # 恰好排除单字符前缀 pattern[:1]。
    return tuple(pattern[:i] for i in range(len(pattern) - 1, 1, -1))


class StringHitMonitor:
    """关键字符串命中收集器（一个或多个 ``DetectString``）。

    用法::

        mon = StringHitMonitor([ds_tt_error, ds_other])
        console.add_listener(mon.update)     # 订阅串口原始数据
        ...
        console.remove_listener(mon.update)
        detail = mon.attach_to(detail)       # 把命中追加到 TestResult.detail
    """

    def __init__(self, detect_strings):
        # 兼容单条与多条：单个 DetectString 或 DetectString 的可迭代。
        if isinstance(detect_strings, DetectString):
            detect_strings = [detect_strings]
        self._items = []
        for ds in detect_strings:
            self._items.append({
                "label": ds.label,
                "re": re.compile(ds.pattern),
                "tails": _derive_splice_tails(ds.pattern),
                "tail": "",      # 上次 chunk 末尾的截断前缀（仅当结尾是某 pattern 前缀时非空）
                "hits": [],      # 命中文本（去 ANSI 后 strip；跨 chunk 时为拼接还原后的那一行）
            })

    def update(self, text):
        """``console.add_listener`` 回调（读线程调用）。仅正则匹配 + 追加，极轻量。"""
        if not text:
            return
        for it in self._items:
            buf = it["tail"] + text
            it["hits"].extend(self._extract_hits(it["re"], buf))
            it["tail"] = self._splice_tail(text, it["tails"])

    @staticmethod
    def _extract_hits(re_obj, buf):
        """对 buf 中每个匹配，取所在行（\\n 分割）作为命中文本。"""
        out = []
        for m in re_obj.finditer(buf):
            line_start = buf.rfind("\n", 0, m.start()) + 1
            line_end = buf.find("\n", m.end())
            if line_end == -1:
                line_end = len(buf)
            line = buf[line_start:line_end]
            out.append(_ANSI_RE.sub("", line).strip())
        return out

    @staticmethod
    def _splice_tail(text, tails):
        """若 text 结尾是某截断前缀，返回该前缀，否则返回空串。"""
        if not tails:
            return ""
        stripped = text.rstrip("\r\n")
        for tail in tails:
            if stripped.endswith(tail):
                return tail
        return ""

    def get_hits(self):
        """返回命中文本（``{label: [命中行...]}``，按定义顺序）。"""
        return {it["label"]: list(it["hits"]) for it in self._items}

    def attach_to(self, detail: str) -> str:
        """把各 ``DetectString`` 的命中信息追加到 detail（命中不改变 status）。

        展示文案统一为 ``{label} 命中 N 次：第 i 次…``，收敛在本类内，调用模块不再
        各自拼文案（消除 video/rtmp 两份 ``_attach_tt_hits`` 重复）。
        """
        blocks = []
        for it in self._items:
            hits = it["hits"]
            if not hits:
                continue
            blocks.append("\n".join(
                [f"{it['label']} 命中 {len(hits)} 次："]
                + [f"第{i}次: {h}" for i, h in enumerate(hits, 1)]
            ))
        if not blocks:
            return detail
        block = "\n".join(blocks)
        return (detail + "\n" + block) if detail else block

    def clear(self):
        """清空命中（跨 rep 复用实例时调用）。"""
        for it in self._items:
            it["hits"] = []
            it["tail"] = ""
