"""RTMP 推流模块：EVB 推流 + PC 端 ffmpeg 拉流 + ffprobe 验证。

流程：
- setup: 确定 pc_ip（自动检测或配置），启动 RtmpReceiver
- run: 前置压制 FTP 崩溃刷屏 -> 启 ffmpeg 拉流 -> ``rtmp_video_start <url>``
       (exec_async，不依赖哨兵) -> 等推流时长 -> ``rtmp_video_stop`` ->
       ffprobe 验证拉到的流（★ 主判据，侧信道）
- teardown: 停止 ffmpeg

只依赖 WiFi（推流需网络），不依赖 FTP。

推流命令用 exec_async 而非 exec_sync：photo/video 后固件 FTP 常陷入
"service go wrong" 崩溃循环刷屏，会打乱 exec_sync 的哨兵定界导致必败。
exec_async 不依赖哨兵，真正成败判据交给 PC 端 ffprobe 是否验到流。
"""
import time
import socket

from .base import TestModule, register
from ..core import logger
from ..core.result import Timer
from ..drivers.rtmp_receiver import RtmpReceiver, RtmpReceiverError
from ..drivers.rtmp_server import RtmpServer, RtmpServerError


def _detect_pc_ip(target_ip: str) -> str:
    """通过"连接 target_ip"获取本机与 target_ip 通信的接口 IP。

    不会真正发数据，仅让 OS 选路并返回本端地址。
    """
    if not target_ip:
        return ""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target_ip, 1935))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return ""


@register("rtmp")
class RtmpModule(TestModule):
    """RTMP 推流测试。"""

    depends = ["wifi_join"]

    def __init__(self, config):
        super().__init__(config)
        self._receiver = None
        self._server = None

    def setup(self, ctx, console):
        evb_ip = getattr(ctx, "evb_ip", None)
        pc_ip = self.config.get("pc_ip", "auto")
        if pc_ip in ("auto", "", None):
            pc_ip = _detect_pc_ip(evb_ip) if evb_ip else ""
            if pc_ip:
                logger.info(f"自动检测到 PC IP: {pc_ip}")
        if not pc_ip:
            logger.warn("未能确定 PC IP，RTMP 推流可能失败")
        ctx.pc_ip = pc_ip

        self._receiver = RtmpReceiver(
            ffmpeg_path=self.config.get("ffmpeg_path", "ffmpeg"),
            ffprobe_path=self.config.get("ffprobe_path", "ffprobe"),
        )
        # RTMP 服务端（MediaMTX）：接收 EVB 推流并中转给 ffmpeg 拉流。
        # 路径默认取项目内置 tools/mediamtx/，可用 mediamtx_path/mediamtx_config 覆盖。
        self._server = RtmpServer(
            mediamtx_path=self.config.get("mediamtx_path"),
            config_path=self.config.get("mediamtx_config"),
        )

    def run(self, ctx, console):
        pc_ip = getattr(ctx, "pc_ip", "")
        if not pc_ip:
            return self._fail("无法确定 PC IP，RTMP 推流目标未知")

        # 启动 PC 端 RTMP 服务端（MediaMTX）：接收 EVB 推流并中转给 ffmpeg 拉流。
        # 这是推流测试的必要前提--无服务端时 EVB 推流连接被拒，流进不到 PC。
        if not self._server or not self._server.available:
            return self._fail("MediaMTX 服务端不可用（缺少 tools/mediamtx/mediamtx 或配置）")
        try:
            self._server.start()
        except RtmpServerError as e:
            return self._fail(f"启动 RTMP 服务端失败: {e}")

        # 前置：压制可能正在刷屏的 FTP 崩溃循环，给 rtmp 干净串口环境。
        # rtmp 不依赖 FTP，但 photo/video 后固件 FTP 常陷入 "service go wrong"
        # 崩溃循环（每 1.5s 刷一次），会打乱后续命令定界。ensure_ftp 重发
        # ftp_server 触发恢复；压不住也无妨，下面的 exec_async 不依赖哨兵。
        try:
            from .ftp import ensure_ftp
            ensure_ftp(ctx, console, force=True)
        except Exception as e:
            logger.warn(f"RTMP 前 FTP 压制异常(可忽略): {e}")
        time.sleep(1.0)  # 等残留刷屏沉淀

        timer = Timer().start()
        url = self.config.get("stream_url", "rtmp://{pc_ip}/live/cam1").format(pc_ip=pc_ip)
        duration = int(self.config.get("stream_duration", 10))

        logger.step(f"  RTMP 推流测试: {url} / {duration}s")

        # 1. EVB 开始推流（先于拉流启动）。
        # 用 exec_async：发命令后直接等推流相关输出，不依赖被 FTP 刷屏打乱的
        # 哨兵定界（exec_sync 在此环境必败）。expect 用宽松正则仅用于尽快返回，
        # 不作为成败判据--真正判据是 PC 端 ffprobe 验到流（侧信道，符合设计
        # 文档原意）。即便 exec_async 没匹配到也不立即 FAIL，留给 ffprobe 兜底。
        # 注：必须先推流后拉流--当前 ffmpeg 拉 RTMP 时若对端暂无流，会立即报
        # I/O error 退出(约 150ms)，故拉流端要在推流上线后再起。
        console.exec_async(
            f"rtmp_video_start {url}",
            expect=r"rtmp_video_start|RTMP|push|start",
            result_timeout=8.0,
        )

        # 2. 等推流上线（给 EVB 建连 + 首帧时间），再起拉流端
        time.sleep(3.0)

        # 3. 启动 PC 端拉流（推流已在线，连接即有流）；带重试防上线时间不准
        try:
            self._receiver.start(url, duration)
        except RtmpReceiverError as e:
            return self._fail(f"启动 ffmpeg 拉流失败: {e}")
        if not self._receiver.is_running:
            # 拉流连接失败重试：推流可能上线稍晚，重试几次
            ok = False
            for i in range(4):
                logger.warn(f"拉流未连上(推流可能未上线)，{1}s 后重试({i+1}/4)")
                time.sleep(1.0)
                try:
                    self._receiver.start(url, duration)
                    if self._receiver.is_running:
                        ok = True
                        break
                except RtmpReceiverError:
                    pass
            if not ok:
                return self._fail("拉流多次重试均未连上推流")

        # 4. 等拉流时长 + 余量（让 ffmpeg 拉到足够数据供 ffprobe 验证）
        time.sleep(duration + 2)

        # 5. 停止推流（同样 exec_async 容忍刷屏）
        console.exec_async(
            "rtmp_video_stop",
            expect=r"rtmp_video_stop|stop|RTMP",
            result_timeout=8.0,
        )

        # 6. ffprobe 验证拉到的流（★ 主判据）
        info = self._receiver.verify(min_duration=max(1.0, duration * 0.5))
        if info.get("ok"):
            res = self._pass(f"推流验证通过: {info['reason']}")
        else:
            res = self._fail(f"推流验证失败: {info.get('reason', '未知')}",
                             detail=str(info))
        res.elapsed_ms = timer.elapsed_ms()
        return res

    def teardown(self, ctx, console):
        if self._receiver:
            self._receiver.stop()
            self._receiver = None
        if self._server:
            self._server.stop()
            self._server = None
