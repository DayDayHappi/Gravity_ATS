"""eMMC 模块：目录挂载验证。

实测日志显示板子上电已自动挂载到 /emmc（``sd mount to /emmc/ is successful``），
故默认只执行 ``cd emmc`` 验证可进入目录，不做 mkfs/mount（避免与自动挂载冲突）。
配置 ``emmc.format: true`` 或 CLI ``--format`` 时才格式化+重挂载。
"""
from .base import TestModule, register
from ..core.result import Timer


@register("emmc")
class EmmcModule(TestModule):
    """eMMC 挂载验证。"""

    depends = []

    def run(self, ctx, console):
        timer = Timer().start()
        do_format = bool(self.config.get("format", False))

        if do_format:
            logger.info("格式化 eMMC（mkfs）...")
            r = console.exec_sync("mkfs -t elm sd", timeout=60.0)
            if not r.success:
                return self._fail("格式化失败", detail=r.clean)
            r = console.exec_sync("mount sd /emmc elm", timeout=15.0)
            if not r.success:
                return self._fail("挂载失败", detail=r.clean)

        # 默认路径：cd /emmc 验证可进入（用绝对路径，避免上次运行残留当前目录导致 cd emmc 失败）
        r = console.exec_sync("cd /emmc", timeout=10.0)
        if not r.success:
            return self._fail("无法进入 /emmc 目录", detail=r.clean)
        res = self._pass("已进入 /emmc" + ("（已格式化）" if do_format else "（自动挂载）"))
        res.elapsed_ms = timer.elapsed_ms()
        return res
