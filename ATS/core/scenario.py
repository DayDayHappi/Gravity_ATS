"""测试场景（Scenario）数据结构与 prepare/cleanup 动作注册表。

职责边界（架构约定）：
- **Scenario**：怎么组合测试（流程 / 顺序 / 循环次数 / 持续时间 / 前置清理动作）。
- **Runner**：什么时候执行（调度）。
- **Module**：怎么测（能力）。
- **Config**：参数是什么。

本模块只定义数据结构 + prepare/cleanup 动作注册表，不含执行逻辑
（执行在 ``scenario_manager`` 与 ``runner``）。
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LoopConfig:
    """整轮 tasks 循环配置。

    ``count``（次数）与 ``duration``（秒）二选一；都缺省时视为**无限循环**
    （老化测试用途，打印提示 + 外部 Ctrl+C 中断）。``count`` 优先于 ``duration``。
    """
    enable: bool = False
    count: Optional[int] = None
    duration: Optional[float] = None


@dataclass
class Task:
    """一个测试任务：模块名 + 重复次数 + 持续时间 + 参数覆盖。

    - ``repeat``: 该 task 重复执行次数（由 runner 循环，模块内不写 for）。
    - ``duration``: 快捷覆盖模块的「持续类」参数，经模块类属性 ``duration_key``
      映射（video→video_duration、rtmp→stream_duration）。
    - ``override``: 显式参数覆盖 dict（任意模块配置 key）。
    """
    module: str
    repeat: int = 1
    duration: Optional[float] = None
    override: dict = field(default_factory=dict)


@dataclass
class Scenario:
    """一次完整测试任务描述（不含实现）。"""
    name: str = ""
    prepare: list = field(default_factory=list)
    tasks: list = field(default_factory=list)
    cleanup: list = field(default_factory=list)
    loop: LoopConfig = field(default_factory=LoopConfig)


# prepare/cleanup 动作注册表：动作名 -> 可调用对象
PREPARE_ACTIONS = {}
CLEANUP_ACTIONS = {}


def prepare_action(name: str):
    """装饰器：注册一个 prepare 动作（如 serial_init / wifi_connect）。"""
    def deco(fn):
        PREPARE_ACTIONS[name] = fn
        return fn
    return deco


def cleanup_action(name: str):
    """装饰器：注册一个 cleanup 动作（如 stop_stream / close_serial）。"""
    def deco(fn):
        CLEANUP_ACTIONS[name] = fn
        return fn
    return deco
