"""PowerCycle 恢复后端（ADR-016 第一阶段唯一后端）。

把统一 ``recover()`` 请求映射为 ``ctx.power_switch.reboot()``。PowerSwitch 本身
保持 ADR-015 原职责不变（只上下电，不感知触发原因与测试策略）。

禁止静默 fallback：``available()`` 返回 False（power_switch 未启用/未探测到）时，
Coordinator 应报 ``RecoveryBackendUnavailable``，不得偷偷改 soft reset 或静默关闭。
"""
from ...core import logger
from .base import RecoveryBackend, register_backend


@register_backend("power_cycle")
class PowerCycleBackend(RecoveryBackend):
    """串口控制器上下电恢复。"""

    name = "power_cycle"

    def __init__(self, config: dict = None):
        self.config = config or {}

    def available(self, ctx) -> bool:
        """可用条件：ctx.power_switch 已探测并持有长连接。"""
        ps = getattr(ctx, "power_switch", None)
        return ps is not None

    def recover(self, ctx):
        """执行 power cycle：``ctx.power_switch.reboot_checked()``（NEW-P0-04）。

        用严格接口验证 OFF/ON 控制器回帧，避免「板子根本没断电重启却被判恢复成功」。
        设计文档 §23：Recovery 路径禁止静默退化到非严格 reboot()。
        """
        ps = getattr(ctx, "power_switch", None)
        if ps is None:
            raise RuntimeError("power_switch 未就绪，无法 power cycle")
        if not hasattr(ps, "reboot_checked"):
            raise RuntimeError("PowerSwitch 不支持 reboot_checked，禁止非严格 PowerCycle recovery")
        logger.info("PowerCycleBackend: 执行 power cycle（下电→延时→上电，严格校验回帧）...")
        ps.reboot_checked()
        logger.info("PowerCycleBackend: power cycle 完成")
        return f"power cycle via {ps.port}"
