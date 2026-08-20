"""FTP 模块：启动 EVB 端 FTP 服务 + PC 端连接验证。

流程：
1. 串口发 ``ftp_server``，用 exec_async 等到 ``service launched success``（真正
   listen 21 端口）——``Ftp server init success`` 只是初始化完成，到 listen 还有
   约 3~4s 延迟，只等 init success 就 connect 会 Connection refused。
2. 用 FtpClient 连接 ctx.evb_ip（重试，等服务真正 listen）。
3. 验证：列 /emmc 目录成功。
4. 把已连接的 ftp_client 存入 ctx，供 photo/video 模块复用。

注意：``ftp_server`` 全程只在本模块 run() 发一次（wifi 连接后），此后不再
重发——板子端服务一直 listen，重发只会触发固件 "service go wrong, now wait
restarting" 崩溃循环刷屏日志，干扰问题定位。

板子 FTP 会话有约 3s 空闲超时，闲置后连接会被服务端断开。``ensure_ftp`` 不
再"先测试旧连接再决定要不要重连"，而是每次要下载图片/视频前都直接建一条
全新独立的控制连接（新 socket -> 读欢迎信息 -> 重新 USER/PASS 登录 -> cwd
回根目录），数据连接（主动模式 PORT，每次传输换新端口）由 ftplib 在实际
传输时自动重新协商。

依赖 wifi（需 evb_ip）。必须在 photo/video 之前执行。
"""
from .base import TestModule, register
from ..core import logger
from ..core.result import Timer
from ..drivers.ftp_client import FtpClient, FtpError


def ensure_ftp(ctx, console, force=False):
    """获取可用于下载的 FTP 客户端：每次都重新 connect，不测试/复用旧连接。

    板子 FTP 服务端会一直 listen，但会话空闲超过约 3s 就被服务端断开。因此不再
    尝试探测旧连接是否存活（探测本身也要一次 RTT，且大概率已经死了），而是
    每次要下载图片/视频前都直接建立一条全新独立的控制连接（新 socket ->
    connect 读欢迎信息 -> USER/PASS 重新登录 -> cwd 回根目录，见
    ``FtpClient.connect()``），数据连接（PORT + 新数据端口）由 ftplib 在每次
    实际传输时自动重新协商，无需在此处处理。

    force 参数保留供调用方语义区分（force=True 常用于拍照/录像刚结束、
    force=False 用于开始前的基线检查），但两者行为一致：都会重新连接。

    成功返回 FtpClient，失败返回 None。
    """
    client = getattr(ctx, "ftp_client", None)
    if client is not None:
        try:
            client.close()
        except Exception:
            pass
        ctx.ftp_client = None

    evb_ip = getattr(ctx, "evb_ip", None)
    if not evb_ip:
        return None
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
    logger.debug("FTP 已重新连接")
    return client


@register("ftp")
class FtpModule(TestModule):
    """FTP 服务启动与连接验证。"""

    depends = ["wifi_join"]

    def run(self, ctx, console, params=None):
        self.config = self._merge(params)
        evb_ip = getattr(ctx, "evb_ip", None)
        if not evb_ip:
            return self._skip("无 EVB IP（WiFi 未连接），跳过 FTP")

        timer = Timer().start()
        cfg = self.config
        # 保存配置供 ensure_ftp 复用
        ctx.ftp_cfg = cfg
        # 1. 启动 EVB 端 FTP 服务。发 ftp_server 后必须等到 "service launched success"
        #    （服务真正开始监听 21 端口）——"Ftp server init success" 只是初始化完成，
        #    到真正 listen 还有约 3~4s 延迟；若只等 init success 就 connect，会撞在
        #    服务未 listen 的窗口上，得到 Connection refused（见 devBugLog 记录）。
        #    用 exec_async 持续等 "service launched success"，事件驱动而非固定 sleep。
        r = console.exec_async("ftp_server",
                               expect=r"service launched success",
                               result_timeout=15.0)
        if not r.success:
            return self._fail("FTP 服务启动失败（未等到 service launched）", detail=r.clean)

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
