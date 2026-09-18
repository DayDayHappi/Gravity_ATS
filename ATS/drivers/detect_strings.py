"""固件关键字符串检测定义：检测串（监听命中串）的唯一维护位置。

本文件只存「监听命中串」的定义（key / pattern / label），不写 IO、不编排、
不 import console/ctx。video / rtmp 等模块按配置选择键（``detect_strings``）
查表实例化 ``StringHitMonitor`` 订阅串口原始数据，命中只收集、不判 FAIL。

注意：跨 chunk 截断前缀的自动推导（见 ``string_hit_monitor.py``）**仅对字面串
成立**。若未来新增含正则元字符的 pattern（如 ``\s*`` / ``\d+``），无法按字面
前缀拼接，需在定义处显式提供截断前缀或降级为「不跨 chunk 拼接」，届时在对应
条目注释标注。
"""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class DetectString:
    """一条待检测的关键字符串定义。

    Attributes:
        key: 配置选择键（modules yaml 的 ``detect_strings`` 列表引用此键）。
        pattern: 匹配正则/字面串（进 ``re`` 编译）。字面串（如 ``TT ERROR``）支持
            跨 chunk 截断前缀自动推导；含正则元字符的 pattern 需另行标注处理方式。
        label: 报告展示名（命中详情标题里显示）。
    """

    key: str
    pattern: str
    label: str


DETECT_STRINGS: Mapping[str, DetectString] = MappingProxyType({
    # 首条即历史 TTErrorMonitor 的内联串，pattern 逐字不动（纯搬移，不改判据语义）。
    "tt_error": DetectString("tt_error", r"TT ERROR", "TT ERROR"),
    # 录像/推流过程中的 IMU FMQ 溢出日志；用户给的字符串逐字（小写、含空格、`=` 结尾），
    # `=` 后实际有数字但不校验（字面串子串匹配即可命中 `... f=1234`）；纯字面串，跨 chunk
    # 截断前缀自动推导生效。
    "imu_fmq_overflow": DetectString("imu_fmq_overflow", r"imu fmq overflow f=", "imu fmq overflow f="),
    # 后续新增串在此追加，如 "xxx": DetectString(...)
})
