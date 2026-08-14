"""FTP 模块：启动 EVB 端 FTP 服务 + PC 端连接验证。

流程：
1. 串口发 ``ftp_server``，等 ``Ftp server init success`` 或 ``service launched success``。
2. 用 FtpClient 连接 ctx.evb_ip（重试，等服务真正 listen）。
3. 验证：列 /emmc 目录成功。
4. 把已连接的 ftp_client 存入 ctx，供 photo/video 模块复用。

注意：该固件 FTP 服务在录像等重负载后会崩溃（``service go wrong``），
``ensure_ftp`` 会在每次使用前检查并恢复（重发 ftp_server + 重连）。

依赖 wifi（需 evb_ip）。必须在 photo/video 之前执行。
"""
import re

from .base import TestModule, register
from ..core import logger
from ..core.result import Timer
from ..drivers.ftp_client import FtpClient, FtpError

_FTP_OK_RE = r"Ftp server init success|service launched success"


def ensure_ftp(ctx, console, force=False):
    """确保 FTP 客户端可用，不可用则重发 ftp_server + 重连。

    供 photo/video 模块在使用 FTP 前调用，应对固件 FTP 服务在重负载后崩溃。
    - force=True：强制重发 ftp_server + 重连（用于拍照/录像后，FTP 服务可能半崩）
    - force=False：先测现有连接，失效才恢复

    成功返回 FtpClient，失败返回 None。
    """
    import time
    client = getattr(ctx, "ftp_client", None)

    if not force and client is not None:
        # 先测现有连接是否活着（list 根目录）
        try:
            client.list_dir("/emmc")
            return client
        except Exception:
            logger.warn("FTP 连接失效，尝试恢复...")
            try:
                client.close()
            except Exception:
                pass
            ctx.ftp_client = None
    elif force:
        # 强制重连：先关旧连接
        logger.debug("强制重连 FTP")
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
            ctx.ftp_client = None

    # 重发 ftp_server 恢复服务
    evb_ip = getattr(ctx, "evb_ip", None)
    if not evb_ip:
        return None
    r = console.exec_sync("ftp_server", expect=_FTP_OK_RE, timeout=10.0)
    if not r.success:
        logger.error("FTP 服务恢复失败")
        return None
    # 等服务真正 listen
    time.sleep(1.5)
    cfg = getattr(ctx, "ftp_cfg", {}) or {}
    client = FtpClient(
        host=evb_ip, port=cfg.get("port", 21),
        user=cfg.get("user", "loogg"), password=cfg.get("password", "loogg"),
        retry=cfg.get("connect_retry", 5), interval=cfg.get("connect_interval", 1.5),
        pasv=cfg.get("pasv", False), timeout=cfg.get("timeout", 10),
    )
    try:
        client.connect()
    except FtpError as e:
        logger.error(f"FTP 重连失败: {e}")
        return None
    ctx.ftp_client = client
    logger.info("FTP 已恢复")
    return client


@register("ftp")
class FtpModule(TestModule):
    """FTP 服务启动与连接验证。"""

    depends = ["wifi_join"]

    def run(self, ctx, console):
        evb_ip = getattr(ctx, "evb_ip", None)
        if not evb_ip:
            return self._skip("无 EVB IP（WiFi 未连接），跳过 FTP")

        timer = Timer().start()
        cfg = self.config
        # 保存配置供 ensure_ftp 复用
        ctx.ftp_cfg = cfg
        # 1. 启动 EVB 端 FTP 服务
        r = console.exec_sync("ftp_server", expect=_FTP_OK_RE, timeout=10.0)
        if not r.success:
            return self._fail("FTP 服务启动失败", detail=r.clean)

        # 2. PC 端连接（带重试，服务 listen 有延迟）
        client = FtpClient(
            host=evb_ip,
            port=cfg.get("port", 21),
            user=cfg.get("user", "loogg"),
            password=cfg.get("password", "loogg"),
            retry=cfg.get("connect_retry", 5),
            interval=cfg.get("connect_interval", 1.5),
            pasv=cfg.get("pasv", False),
            timeout=cfg.get("timeout", 10),
        )
        try:
            client.connect()
        except FtpError as e:
            return self._fail(f"FTP 客户端连接失败: {e}", detail=r.clean)

        # 3. 验证列目录
        try:
            items = client.list_dir("/emmc")
        except Exception as e:
            client.close()
            return self._fail(f"列 /emmc 失败: {e}", detail=r.clean)

        # 4. 存入 ctx 供后续模块复用
        ctx.ftp_client = client
        res = self._pass(f"FTP 已连接 {evb_ip}，/emmc 列出 {len(items)} 项")
        res.elapsed_ms = timer.elapsed_ms()
        return res

    def teardown(self, ctx, console):
        # 不在这里关闭 ftp_client：photo/video 还要用，由 ctx.cleanup() 统一关闭
        pass
