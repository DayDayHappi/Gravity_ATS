"""场景管理器：加载场景、编排 prepare → tasks(loop) → cleanup。

职责边界：ScenarioManager 只负责「加载 + 编排」，具体模块执行交给 TestRunner，
prepare/cleanup 动作是「框架级环境准备」的薄封装（串口初始化、WiFi 交互连接、
预清理、兜底停止推流、关闭串口），模块级准备（如 ftp_server 启动）仍由模块自身 run 完成。

动作签名统一为 ``fn(ctx, system_cfg)``，通过 ctx 传递 console / 状态，动作幂等；
未注册的动作名仅告警跳过，保证 scenario 写法健壮。
"""
import time

from . import logger
from .config import load_system, load_scenario, CONFIG_DIR
from .context import Context
from .scenario import (
    Scenario, Task, LoopConfig,
    prepare_action, cleanup_action, PREPARE_ACTIONS, CLEANUP_ACTIONS,
)
from .serial_console import SerialConsole, detect_port, SerialError
from ..drivers import rtmp_commands as rtmp_commands
from ..drivers import wifi_commands as wifi_commands
from ..drivers import video_commands as video_commands
from ..drivers import emmc_commands as emmc_commands


class ScenarioError(Exception):
    """场景编排错误（环境不可用等）。"""


# ---------------------------------------------------------------------------
# prepare 动作
# ---------------------------------------------------------------------------

@prepare_action("serial_init")
def _action_serial_init(ctx, system_cfg):
    """串口探测 + 打开 + 就绪 + 自检，console 存入 ctx.console。

    按 ctx.serial_fingerprint（ADR-013）选择指纹集/就绪正则；默认 default（旧固件）。

    NEW-P0-05：若 PowerSwitch 已先行上电（ctx.power_switch 存在，冷启动场景），
    在 ``power_on_detect_timeout`` 内循环等待 EVB UART 枚举出现（bounded polling），
    避免「上电后 UART 尚未枚举完成，单次探测失败」的 race。
    """
    ser_cfg = system_cfg.get("serial", {})
    port = ser_cfg.get("port", "auto")
    baudrate = ser_cfg.get("baudrate", 2000000)
    fingerprint_set = getattr(ctx, "serial_fingerprint", "default")

    # 排除已识别的 PowerSwitch 串口（避免把控制器误当 EVB）
    power_port = None
    ps = getattr(ctx, "power_switch", None)
    if ps is not None:
        power_port = getattr(ps, "port", None)

    if port in ("auto", "", None):
        # 冷启动（PowerSwitch 先行上电）：在超时内循环等待 EVB UART 出现
        if ps is not None:
            port, detected_baud = _detect_evb_with_wait(
                baudrate=baudrate,
                baud_candidates=ser_cfg.get("baudrate_candidates"),
                fingerprint_set=fingerprint_set,
                exclude_port=power_port,
                timeout=ser_cfg.get("power_on_detect_timeout", 30.0),
                interval=ser_cfg.get("power_on_detect_interval", 0.5),
            )
            if port is None:
                raise ScenarioError(
                    "PowerSwitch 已上电，但 EVB UART 在规定时间内未出现"
                )
        else:
            port, detected_baud = detect_port(
                baudrate=baudrate,
                baud_candidates=ser_cfg.get("baudrate_candidates"),
                interactive=True,
                detect_timeout=ser_cfg.get("detect_timeout", 2.0),
                fingerprint_set=fingerprint_set,
            )
            if port is None:
                raise ScenarioError("无法确定 EVB 串口，测试中止")
            baudrate = detected_baud
    else:
        # 显式端口：直接使用
        pass

    console = SerialConsole(
        port=port, baudrate=baudrate,
        timeout=ser_cfg.get("timeout", 2.0),
        ready_timeout=ser_cfg.get("ready_timeout", 60),
        sentinel_timeout=ser_cfg.get("sentinel_timeout", 5.0),
        ready_set=fingerprint_set,
    )
    try:
        console.open()
    except SerialError as e:
        raise ScenarioError(str(e))

    if not console.wait_for_ready():
        console.close()
        raise ScenarioError("EVB 未就绪（等待 msh 超时）")
    if not console.health_check():
        console.close()
        raise ScenarioError("串口自检失败，请检查波特率/接线")

    ctx.console = console


def _detect_evb_with_wait(baudrate, baud_candidates, fingerprint_set,
                          exclude_port, timeout, interval):
    """冷启动：在 timeout 内循环等待 EVB UART 枚举并识别（bounded polling）。

    复用 ``detect_port`` 的指纹探测，但把「单次扫描」改为「循环等待」；每轮排除
    PowerSwitch 端口，避免把控制器误当 EVB。返回 (port, baud) 或 (None, None)。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        from ..core.serial_console import _list_candidate_ports
        ports = [p for p in _list_candidate_ports() if p != exclude_port]
        if ports:
            for p in ports:
                for baud in ([baudrate] + [b for b in (baud_candidates or []) if b != baudrate]):
                    if _probe_evb_fingerprint(p, baud, fingerprint_set):
                        return p, baud
        time.sleep(interval)
    return None, None


def _probe_evb_fingerprint(port, baud, fingerprint_set):
    """用指定端口+波特率探测 EVB 指纹（复用 serial_console._probe_port_baud）。"""
    from ..core.serial_console import _probe_port_baud
    try:
        return _probe_port_baud(port, baud, detect_timeout=2.0,
                                fingerprint_set=fingerprint_set)
    except Exception:
        return False


@prepare_action("power_switch_init")
def _action_power_switch_init(ctx, system_cfg):
    """探测上下电控制模块（ADR-015）+ 冷启动上电（NEW-P0-05）。

    - 幂等：``power_switch.enabled`` 为 false 且非 recovery 必需时直接 return。
    - recovery.enabled=true + backend=power_cycle 时 fail-closed：power_switch 未启用、
      无候选、探测失败、POWER_STATE_ON 未确认均抛 ScenarioError（禁止 WARN+skip）。
    - 显式 ``power_switch.port`` 优先；auto 时按协议帧识别（排除已配置的 serial.port）。
    - 探测成功后发 POWER ON 确认 POWER_STATE_ON，长连接存 ctx.power_switch。
    """
    from ..drivers import power_commands as pcmds
    from ..drivers.power_switch import detect_power_switch, _accessible_ports

    ps_cfg = system_cfg.get("power_switch", {}) or {}
    enabled = bool(ps_cfg.get("enabled", False))

    # 是否 recovery 必需（fail-closed）
    rc_cfg = getattr(ctx, "recovery", None) or {}
    required = bool(rc_cfg.get("enabled", False)) and rc_cfg.get("backend") == "power_cycle"

    if not enabled:
        if required:
            raise ScenarioError(
                "配置错误：recovery.backend=power_cycle 要求 power_switch.enabled=true"
            )
        return

    port = ps_cfg.get("port", "auto")
    baudrate = ps_cfg.get("baudrate", 115200)
    reboot_delay = ps_cfg.get("reboot_delay")

    # 候选端口：排除已配置的 EVB 串口（即使 ctx.console 尚未创建）
    exclude = []
    if port in ("auto", "", None):
        ser_cfg = system_cfg.get("serial", {}) or {}
        evb_port = ser_cfg.get("port", "auto")
        if evb_port not in ("auto", "", None):
            exclude.append(evb_port)
        candidates = [p for p in _accessible_ports() if p not in exclude]
        if not candidates:
            if required:
                raise ScenarioError("无候选串口，无法探测上下电控制模块")
            logger.warn("power_switch_init: 无候选串口（可能未插控制器），跳过")
            return
        ps = detect_power_switch(candidate_ports=candidates, baudrate=baudrate,
                                 reboot_delay=reboot_delay)
    else:
        # 显式端口：直接在该端口验证
        candidates = [port]
        ps = detect_power_switch(candidate_ports=candidates, baudrate=baudrate,
                                 reboot_delay=reboot_delay)

    if ps is None:
        if required:
            raise ScenarioError("未探测到上下电控制模块（POWER_STATE_ON 未确认）")
        logger.warn("power_switch_init: 未探测到上下电控制模块，跳过（后续 reboot 不可用）")
        return

    # NEW-P0-05：确认 POWER ON 已发送且 POWER_STATE_ON 已回（冷启动前置）
    on_resp = ps.power_on()
    if on_resp != pcmds.POWER_STATE_ON:
        if required:
            raise ScenarioError(
                f"上下电控制上电确认失败（回帧 {on_resp.hex(' ').upper() if on_resp else '<空>'}）"
            )
        logger.warn("power_switch_init: 上电确认失败，但非 recovery 必需，继续")
    ctx.power_switch = ps


@prepare_action("serial_reconnect")
def _action_serial_reconnect(ctx, system_cfg):
    """重建 EVB UART transport（ADR-016 NEW-P0-06 + BUG-006），只负责 transport 恢复。

    - 只恢复底层 pyserial transport（保持 SerialConsole 对象身份不变），不负责
      board_ready（msh ready + health_check 由 board_ready 单独做）。
    - 职责边界：不碰 PowerSwitch、WiFi、FTP、health policy、Task retry。

    BUG-006 修复要点（两个句柄抢同一端口 → multiple access on port）：
    1. 先记录 old_port，**先 ``console.close()`` 释放旧 reader + 旧 pyserial 句柄**，
       再谈端口探测（否则探测 open 同一端口与旧 reader 冲突）。
    2. 若 old_port 仍在可访问列表（USB-UART 桥独立供电、端口未消失）→ 直接
       ``console.reconnect(old_port)``，不探测（省掉无谓的 30s 空等）；
       仅 old_port 消失（真重枚举到新设备名）才走 ``_detect_evb_with_wait`` 找新端口。
    """
    console = getattr(ctx, "console", None)
    if console is None:
        raise ScenarioError("serial_reconnect: 无 console，无法重建 transport")

    ps = getattr(ctx, "power_switch", None)
    power_port = getattr(ps, "port", None) if ps is not None else None

    system_cfg = system_cfg or {}
    ser_cfg = system_cfg.get("serial", {}) or {}
    baudrate = ser_cfg.get("baudrate", 2000000)
    fingerprint_set = getattr(ctx, "serial_fingerprint", "default")

    old_port = getattr(console, "port", None)

    # BUG-006：先关旧 transport（释放端口），避免探测时与旧 reader 抢同一端口
    console.close()

    new_port = ser_cfg.get("port", "auto")
    if new_port in ("auto", "", None):
        # 判断原端口是否仍存在（可访问且非 PowerSwitch 端口）
        from ..core.serial_console import _list_candidate_ports
        accessible = [p for p in _list_candidate_ports() if p != power_port]
        if old_port is not None and old_port in accessible:
            # 原端口未消失：直接沿用，不探测（BUG-006 主场景）
            logger.info(f"serial_reconnect: 原端口 {old_port} 仍在，直接重连（不探测）")
            new_port = old_port
        else:
            # 原端口消失（真重枚举）：才走 bounded wait 探测（旧句柄已 close，无冲突）
            logger.info(f"serial_reconnect: 原端口 {old_port} 已消失，探测新 EVB UART ...")
            new_port, detected_baud = _detect_evb_with_wait(
                baudrate=baudrate,
                baud_candidates=ser_cfg.get("baudrate_candidates"),
                fingerprint_set=fingerprint_set,
                exclude_port=power_port,
                timeout=ser_cfg.get("power_on_detect_timeout", 30.0),
                interval=ser_cfg.get("power_on_detect_interval", 0.5),
            )
            if new_port is None:
                raise ScenarioError("serial_reconnect: PowerCycle 后 EVB UART 未重新枚举")
            baudrate = detected_baud

    # 同一对象 reconnect（保持 Runner/Coordinator/listener 引用不分裂）
    console.reconnect(port=new_port, baudrate=baudrate)


@prepare_action("board_ready")
def _action_board_ready(ctx, system_cfg):
    """轻量 EVB 就绪确认（ADR-016）：``console.wait_for_ready() → health_check()``。

    供 RecoveryCoordinator 在 Power Cycle 后复用（第一阶段不重新执行完整
    serial_init，控制串口预计保持打开）。控制串口未打开时优雅降级（返回，不抛）。

    P0-06：若 ctx.recovery_cursor 已由 Coordinator 记录（PowerCycle 前），则用
    ``wait_for_ready_since(cursor)`` 只认 reboot 后的新 RX，避免命中旧 msh 缓冲；
    否则（首次 serial_init 后）用普通 ``wait_for_ready``。
    """
    console = getattr(ctx, "console", None)
    if console is None:
        logger.warn("board_ready: 无 console，跳过")
        return
    cursor = getattr(ctx, "recovery_cursor", None)
    if cursor is not None:
        ready = console.wait_for_ready_since(cursor)
        # fresh-ready 完成后清游标，避免后续误用
        ctx.recovery_cursor = None
    else:
        ready = console.wait_for_ready()
    if not ready:
        raise ScenarioError("EVB 重启后就绪超时（等待 msh 失败）")
    if not console.health_check():
        raise ScenarioError("EVB 重启后串口自检失败")


@prepare_action("wifi_connect")
def _action_wifi_connect(ctx, system_cfg):
    """WiFi 状态收敛器（ADR-008）：先检测已联网则保留，未联网则执行 join。

    - 检测：复用 wifi.check_wifi_connected（ifconfig 有无非 0.0.0.0 IP）。
    - 已联网：设 ctx.evb_ip + ctx.wifi_ready=True + ctx.skip_wifi=True，直接返回。
    - 未联网：自动（--no-interactive-wifi）用默认 SSID join；交互（默认）可选默认/扫描。
    最终保证 WiFi 达到可用状态（ctx.evb_ip 就绪）。
    """
    console = getattr(ctx, "console", None)
    if console is None:
        logger.warn("wifi_connect: 无 console，跳过")
        return

    from ..modules.wifi import check_wifi_connected

    # 1. 状态检测：已联网则收敛，不再 join（掉电记忆 WiFi 场景）
    ip = check_wifi_connected(console)
    if ip:
        ctx.evb_ip = ip
        ctx.wifi_ready = True
        ctx.skip_wifi = True
        logger.info(f"WiFi 已联网（IP={ip}），无需连接")
        return
    ctx.wifi_ready = False

    wifi_cfg = system_cfg.get("wifi", {})
    default_ssid = wifi_cfg.get("default_ssid", "")
    default_pwd = wifi_cfg.get("default_password", "")

    no_interactive = getattr(ctx, "no_interactive_wifi", False)

    print("\n" + "=" * 50)
    print("WiFi 连接")
    print("=" * 50)
    use_default = True
    if not no_interactive and wifi_cfg.get("interactive", True):
        ans = input(f"是否连接默认 WiFi [{default_ssid}]? [Y/n]: ").strip().lower()
        use_default = ans != "n"

    if no_interactive:
        ssid, pwd = default_ssid, default_pwd
        logger.info(f"--no-interactive-wifi：使用默认 WiFi [{ssid}] 自动连接")
    elif use_default:
        ssid, pwd = default_ssid, default_pwd
        logger.info(f"使用默认 WiFi: {ssid}")
    else:
        logger.info("扫描 WiFi 网络...")
        r = console.exec_sync(wifi_commands.WIFI_SCAN_COMMAND,
                              expect=wifi_commands.WIFI_SCAN_HEADER_RE.pattern,
                              timeout=wifi_commands.WIFI_SCAN_TIMEOUT)
        aps = []
        for ln in r.clean.splitlines():
            m = wifi_commands.WIFI_SCAN_ROW_RE.match(ln.strip())
            if m:
                aps.append((m.group(1), m.group(4)))
        if not aps:
            logger.error("扫描无结果，无法选择")
            return
        print("扫描到的 AP:")
        for i, (s, rssi) in enumerate(aps):
            print(f"  [{i}] {s}  (RSSI {rssi})")
        sel = input("选择序号(或直接输入 SSID): ").strip()
        if sel.isdigit() and int(sel) < len(aps):
            ssid = aps[int(sel)][0]
        else:
            ssid = sel
        pwd = input(f"输入 [{ssid}] 的密码: ").strip()

    if not ssid:
        logger.error("SSID 为空")
        return

    ctx.wifi_ssid = ssid
    ctx.wifi_password = pwd
    r = console.exec_async(
        wifi_commands.WIFI_JOIN_COMMAND.format(ssid=ssid, pwd=pwd),
        expect=wifi_commands.WIFI_GOT_IP_RE,
        send_timeout=wifi_commands.WIFI_JOIN_SEND_TIMEOUT,
        result_timeout=wifi_commands.WIFI_JOIN_RESULT_TIMEOUT,
    )
    if r.success and r.matched:
        ctx.evb_ip = r.matched
        ctx.skip_wifi = True
        logger.info(f"WiFi 连接成功: {ssid} / IP={r.matched}")
        time.sleep(5.0)  # 等 wifi join 后板子状态稳定，再发下一条命令
    else:
        logger.error(f"WiFi 连接失败: {r.error}")
        logger.error(f"输出: {r.clean}")


@prepare_action("preclean")
def _action_preclean(ctx, system_cfg):
    """板子状态预清理：回根目录、停录像（未在录则忽略）。"""
    console = getattr(ctx, "console", None)
    if console is None:
        return
    logger.info("预清理板子状态...")
    try:
        console.exec_sync(emmc_commands.EMMC_CD_ROOT_COMMAND,
                          timeout=emmc_commands.EMMC_CD_ROOT_TIMEOUT)
        console.exec_async(video_commands.VIDEO_STOP_COMMAND,
                           expect=video_commands.VIDEO_CLEANUP_EXPECT,
                           result_timeout=video_commands.VIDEO_CLEANUP_TIMEOUT)
    except Exception as e:
        logger.warn(f"预清理异常(可忽略): {e}")


@prepare_action("ftp_ready")
def _action_ftp_ready(ctx, system_cfg):
    """启动 EVB 端 ftp_server（全局只发一次）并建立 PC 端连接。

    幂等：loop 多轮重复调用不会重发 ftp_server（ctx.ftp_server_started 标志）。
    板子 FTP 服务端一直 listen（3s 空闲断开会话），脚本侧仍是无状态 client，
    photo/video 每次下载前由 ensure_ftp 重建连接。ftp_server 只发一次、连接每次重建。
    """
    console = getattr(ctx, "console", None)
    if console is None:
        logger.warn("ftp_ready: 无 console，跳过")
        return
    from ..modules.ftp import start_ftp
    client = start_ftp(ctx, console)
    if client is None:
        logger.warn("ftp_ready: FTP 服务启动/连接失败（可能 WiFi 未连），photo/video 可能跳过")


@prepare_action("preview_start")
def _action_preview_start(ctx, system_cfg):
    """启动画面观察 PreviewManager（ADR-010）：组观看地址 + nginx 就绪后 start。

    - 开关：ctx.preview_enabled（scenario 层 preview.enabled）为 False 则跳过。
    - 观看地址：preview.url 显式覆盖优先；否则由 ctx.pc_ip + rtmp.yaml 的 stream_url
      模板推导（与 rtmp 模块判据同一 URL，避免两处各写一份漂移）。
    - 复用 RtmpServer.check_ready() 确认 nginx-rtmp 就绪，未就绪跳过（不影响判据）。
    - 创建 PreviewManager 写入 ctx.preview_manager，供 preview_stop 与未来扩展复用。
    """
    if not getattr(ctx, "preview_enabled", False):
        logger.info("preview.enabled=false，跳过画面观察")
        return

    from ..drivers.preview_manager import PreviewManager, _detect_pc_ip
    from ..drivers.rtmp_server import RtmpServer, RtmpServerError
    from .config import load_module_config

    preview_cfg = load_module_config("preview")
    rtmp_cfg = load_module_config("rtmp")

    # pc_ip 解析顺序：system.pc.ip -> auto 探测（复用 preview_manager._detect_pc_ip）
    evb_ip = getattr(ctx, "evb_ip", None)
    sys_pc = (getattr(ctx, "system_config", None) or {}).get("pc", {}) or {}
    pc_ip = sys_pc.get("ip", "auto")
    if pc_ip in ("auto", "", None):
        pc_ip = _detect_pc_ip(evb_ip) if evb_ip else ""
    if pc_ip:
        ctx.pc_ip = pc_ip

    explicit_url = (preview_cfg.get("url") or "").strip()
    if explicit_url:
        url = explicit_url
    elif pc_ip:
        url = (rtmp_cfg.get("stream_url", "rtmp://{pc_ip}/live/cam")).format(pc_ip=pc_ip)
    else:
        logger.warn("preview_start: 未确定 PC IP，跳过画面观察")
        return

    # nginx-rtmp 就绪（复用现有 driver），未就绪则跳过（不影响判据）
    try:
        RtmpServer(port=1935).check_ready()
    except RtmpServerError as e:
        logger.warn(f"preview_start: RTMP 服务端未就绪，跳过画面观察: {e}")
        return

    mgr = PreviewManager(preview_cfg)
    mgr.start(url)
    ctx.preview_manager = mgr


@prepare_action("health_monitor_start")
def _action_health_monitor_start(ctx, system_cfg):
    """启动板卡健康监测器（ADR-016，Scenario 生命周期能力，非 Task）。

    - 开关：scenario 的 ``health_monitor.enabled``（ctx 透传）为 false 直接 return，
      零副作用（向后兼容）。
    - P1-03：``recovery.enabled=true`` 但 ``health_monitor.enabled=false`` 时，
      fail-closed 抛 ScenarioError（配置约束，禁止静默无效）。
    - 创建 BoardHealthMonitor 存 ctx.board_health_monitor，订阅串口原始数据。
    - 若 recovery.enabled 同时为真，创建 RecoveryCoordinator 并立即 validate()
      （P1-02：backend/restore 前置校验，失败在 tasks 前报错）。
    """
    hm_cfg = getattr(ctx, "health_monitor", None) or {}
    rc_cfg = getattr(ctx, "recovery", None) or {}

    # P1-03：recovery 要求 monitor 前置（fail-closed）
    if rc_cfg.get("enabled", False) and not hm_cfg.get("enabled", False):
        raise ScenarioError(
            "配置错误：recovery.enabled=true 要求 health_monitor.enabled=true（当前 "
            "health_monitor.enabled=false，机制不会工作）"
        )

    if not hm_cfg.get("enabled", False):
        return

    from ..application.board_health_monitor import BoardHealthMonitor
    from ..application.recovery_coordinator import RecoveryCoordinator
    from ..application.recovery_backends.base import RecoveryBackendUnavailable
    from .config import load_module_config

    console = getattr(ctx, "console", None)
    mon_cfg = load_module_config("board_health") or {}
    monitor = BoardHealthMonitor({**mon_cfg, **hm_cfg})
    monitor.start()
    if console is not None:
        console.add_listener(monitor.on_rx)
    ctx.board_health_monitor = monitor

    # recovery.enabled 时创建 Coordinator 并前置校验（P1-02）
    if rc_cfg.get("enabled", False):
        coord = RecoveryCoordinator(policy=rc_cfg, ctx=ctx, console=console, monitor=monitor)
        try:
            coord.validate()
        except (RecoveryBackendUnavailable, ValueError) as e:
            # fail-closed：tasks 前明确报错，禁止静默降级
            monitor.stop()
            if console is not None:
                try:
                    console.remove_listener(monitor.on_rx)
                except Exception:
                    pass
            ctx.board_health_monitor = None
            raise ScenarioError(f"恢复机制配置校验失败: {e}")
        ctx.recovery_coordinator = coord
        logger.info("板卡健康监测 + 恢复机制已启用（monitor + recovery）")
    else:
        logger.info("板卡健康监测已启用（仅 monitor，不自动恢复）")


# ---------------------------------------------------------------------------
# cleanup 动作
# ---------------------------------------------------------------------------

@cleanup_action("health_monitor_stop")
def _action_health_monitor_stop(ctx, system_cfg):
    """停止板卡健康监测器（ADR-016）。幂等：无实例则直接 return。

    cleanup 首先执行本动作（见场景 cleanup 顺序），防止正常清理被误判为死机。
    """
    monitor = getattr(ctx, "board_health_monitor", None)
    console = getattr(ctx, "console", None)
    if monitor is None:
        return
    if console is not None:
        try:
            console.remove_listener(monitor.on_rx)
        except Exception:
            pass
    monitor.stop()
    ctx.board_health_monitor = None


@cleanup_action("stop_stream")
def _action_stop_stream(ctx, system_cfg):
    """兜底停止 RTMP 推流（幂等，未推流则忽略）。"""
    console = getattr(ctx, "console", None)
    if console is None:
        return
    try:
        console.exec_async(rtmp_commands.RTMP_STOP_COMMAND,
                           expect=rtmp_commands.RTMP_STOP_EXPECT,
                           result_timeout=rtmp_commands.RTMP_STOP_TIMEOUT)
    except Exception:
        pass


@cleanup_action("preview_stop")
def _action_preview_stop(ctx, system_cfg):
    """关闭画面观察 PreviewManager（ADR-010），释放 ffplay 重连 wrapper 及子进程。"""
    mgr = getattr(ctx, "preview_manager", None)
    if mgr is None:
        return
    try:
        mgr.stop()
    except Exception as e:
        logger.warn(f"preview_stop 异常(可忽略): {e}")
    ctx.preview_manager = None


@cleanup_action("power_switch_close")
def _action_power_switch_close(ctx, system_cfg):
    """关闭上下电控制模块串口（ADR-015）。幂等：无实例则直接 return。"""
    ps = getattr(ctx, "power_switch", None)
    if ps is None:
        return
    try:
        ps.close()
    except Exception as e:
        logger.warn(f"power_switch_close 异常(可忽略): {e}")
    ctx.power_switch = None


@cleanup_action("close_serial")
def _action_close_serial(ctx, system_cfg):
    """关闭串口。"""
    console = getattr(ctx, "console", None)
    if console is not None:
        try:
            console.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# ScenarioManager
# ---------------------------------------------------------------------------

class ScenarioManager:
    """加载并编排一个测试场景。"""

    def __init__(self, config_dir: str = None):
        self.config_dir = config_dir or CONFIG_DIR
        self.system_cfg = None
        self.ctx = None
        self.preview_cfg = {}   # scenario 层 preview 开关（ADR-010），load 时解析
        self.recovery_history = []   # ADR-016 P0-05：ctx.cleanup 前保存，供报告读取

    def load(self, name: str) -> Scenario:
        """加载场景名 -> Scenario 对象（含参数合并前的原始 task）。"""
        raw = load_scenario(name, self.config_dir)
        self.preview_cfg = (raw.get("scenario") or {}).get("preview") or {}
        return self._parse_scenario(raw, name)

    def run(self, scenario_name: str, no_interactive_wifi: bool = False,
            module_overrides: dict = None, system_cfg: dict = None) -> list:
        """执行一个场景：prepare → (loop: tasks) → cleanup，返回 TestResult 列表。

        Args:
            scenario_name: 场景名（对应 config/scenarios/<name>.yaml）。
            no_interactive_wifi: 跳过交互 WiFi 连接。
            module_overrides: {module_name: {key: val}}，来自 CLI（如 --format -> emmc.format）。
            system_cfg: 已加载（含 CLI 覆盖）的 system 配置；None 则内部加载。
        """
        self.system_cfg = system_cfg if system_cfg is not None else load_system(self.config_dir)
        scenario = self.load(scenario_name)
        if module_overrides:
            self._apply_module_overrides(scenario, module_overrides)
        # NEW-P1-01：Scenario 生命周期接线前置校验（enabled 必须真实接线，fail-closed）
        self.validate_scenario(scenario, self.system_cfg)

        ctx = Context()
        ctx.system_config = self.system_cfg
        ctx.no_interactive_wifi = no_interactive_wifi
        ctx.preview_enabled = bool(self.preview_cfg.get("enabled", False))
        ctx.serial_fingerprint = scenario.serial_fingerprint   # ADR-013
        ctx.health_monitor = scenario.health_monitor            # ADR-016（策略透传给 action）
        ctx.recovery = scenario.recovery                        # ADR-016
        ctx.scenario_name = scenario.name
        self.ctx = ctx

        results = []
        try:
            # prepare
            for action in scenario.prepare:
                self._run_action(action, ctx, "prepare")

            # tasks（loop 由 runner 控制）
            from .runner import TestRunner
            runner = TestRunner(self.system_cfg, ctx, scenario)
            results = runner.run()
        finally:
            # cleanup 始终执行
            for action in scenario.cleanup:
                try:
                    self._run_action(action, ctx, "cleanup")
                except Exception as e:
                    logger.warn(f"cleanup 动作 {action} 异常: {e}")
            # P0-05：ctx.cleanup() 前保存 recovery_history，避免被清空后报告丢失
            self.recovery_history = list(getattr(ctx, "recovery_history", None) or [])
            # 关闭 ctx 持有的资源（如 FTP 连接）
            try:
                ctx.cleanup()
            except Exception:
                pass

        return results

    # ---------- 内部 ----------

    def _parse_scenario(self, raw: dict, default_name: str) -> Scenario:
        sc = raw.get("scenario") or {}
        loop_raw = sc.get("loop") or {}
        loop = LoopConfig(
            enable=bool(loop_raw.get("enable", False)),
            count=loop_raw.get("count"),
            duration=loop_raw.get("duration"),
        )
        tasks = []
        for t in sc.get("tasks", []):
            if isinstance(t, str):
                t = {"module": t}
            if not t.get("module"):
                raise ScenarioError(f"场景 {default_name} 存在缺 module 的 task")
            tasks.append(Task(
                module=t.get("module"),
                repeat=int(t.get("repeat", 1) or 1),
                duration=t.get("duration"),
                override=dict(t.get("override") or {}),
            ))
        if not tasks:
            raise ScenarioError(f"场景 {default_name} 的 tasks 为空")
        return Scenario(
            name=sc.get("name", default_name),
            prepare=list(sc.get("prepare", [])),
            tasks=tasks,
            cleanup=list(sc.get("cleanup", [])),
            loop=loop,
            serial_fingerprint=sc.get("serial_fingerprint", "default"),
            health_monitor=dict(sc.get("health_monitor") or {}),   # ADR-016
            recovery=dict(sc.get("recovery") or {}),               # ADR-016
        )

    def _apply_module_overrides(self, scenario: Scenario, module_overrides: dict):
        """把 CLI 模块覆盖合并进对应 task 的 override。"""
        for task in scenario.tasks:
            if task.module in module_overrides:
                task.override = {**task.override, **module_overrides[task.module]}

    def validate_scenario(self, scenario: Scenario, system_cfg: dict = None):
        """公开入口（NEW-P1-03）：静态校验 Scenario runtime contract + system capability。

        供 ``run()`` 与 ``--dry-run`` 共用；dry-run 只做静态校验（不做串口/网络探测）。

        NEW-P0-05（设计文档 §22）：recovery.backend=power_cycle 时校验
        system.power_switch.enabled 必须 true（fail-closed，不得等到 serial_init 才暴露）。
        """
        self._validate_scenario_runtime_contract(scenario)
        self._validate_system_capability(scenario, system_cfg)

    def _validate_system_capability(self, scenario: Scenario, system_cfg: dict):
        """NEW-P0-05：system 硬件能力在硬件动作前校验（dry-run/run 共用）。"""
        rc = scenario.recovery or {}
        if rc.get("enabled", False) and rc.get("backend") == "power_cycle":
            if system_cfg is None:
                return   # dry-run 未传 system_cfg 时跳过（run 前会再查）
            ps_cfg = system_cfg.get("power_switch", {}) or {}
            if not ps_cfg.get("enabled", False):
                raise ScenarioError(
                    "配置错误：recovery.backend=power_cycle 要求 system.power_switch.enabled=true"
                )

    def _validate_scenario_runtime_contract(self, scenario: Scenario):
        """NEW-P1-01：校验 Scenario 声明与生命周期 action 接线一致，fail-closed。

        原则：Scenario 显式声明（YAML 保持可审计），框架**不**偷偷自动补 action；
        声明了 enabled 却漏接对应生命周期 action 时直接报 ScenarioError。

        校验规则（仅对已声明的能力做接线检查，未声明零影响）：
        - health_monitor.enabled=true → prepare 含 health_monitor_start、
          cleanup 含 health_monitor_stop。
        - recovery.enabled=true → health_monitor.enabled=true、
          prepare 含 health_monitor_start。
        - recovery.backend=power_cycle → prepare 含 power_switch_init，且
          power_switch_init 在 health_monitor_start 之前。
        - health_monitor_stop 必须早于 power_switch_close / close_serial
          （cleanup 本身不被 Monitor 误判为死机）。
        """
        hm = scenario.health_monitor or {}
        rc = scenario.recovery or {}
        prepare = list(scenario.prepare)
        cleanup = list(scenario.cleanup)

        if hm.get("enabled", False):
            if "health_monitor_start" not in prepare:
                raise ScenarioError(
                    "配置错误：health_monitor.enabled=true 但 prepare 缺 health_monitor_start"
                )
            if "health_monitor_stop" not in cleanup:
                raise ScenarioError(
                    "配置错误：health_monitor.enabled=true 但 cleanup 缺 health_monitor_stop"
                )

        if rc.get("enabled", False):
            if not hm.get("enabled", False):
                raise ScenarioError(
                    "配置错误：recovery.enabled=true 要求 health_monitor.enabled=true"
                )
            if "health_monitor_start" not in prepare:
                raise ScenarioError(
                    "配置错误：recovery.enabled=true 但 prepare 缺 health_monitor_start"
                )
            if rc.get("backend") == "power_cycle":
                if "power_switch_init" not in prepare:
                    raise ScenarioError(
                        "配置错误：recovery.backend=power_cycle 但 prepare 缺 power_switch_init"
                    )
                # NEW-P0-05（设计文档 §21）：power_switch_init < serial_init < health_monitor_start
                for a, b, name in (("power_switch_init", "serial_init", "serial_init"),
                                   ("power_switch_init", "health_monitor_start", "health_monitor_start"),
                                   ("serial_init", "health_monitor_start", "health_monitor_start")):
                    if a in prepare and b in prepare:
                        if prepare.index(a) > prepare.index(b):
                            raise ScenarioError(
                                f"配置错误：{a} 必须在 {b} 之前（冷启动依赖顺序）"
                            )

        # cleanup 顺序：health_monitor_stop 必须早于 power_switch_close / close_serial
        if "health_monitor_stop" in cleanup:
            for later in ("power_switch_close", "close_serial"):
                if later in cleanup and cleanup.index("health_monitor_stop") > cleanup.index(later):
                    raise ScenarioError(
                        f"配置错误：health_monitor_stop 必须在 {later} 之前（避免 cleanup 被误判为死机）"
                    )

    def _run_action(self, action: str, ctx: Context, kind: str):
        registry = PREPARE_ACTIONS if kind == "prepare" else CLEANUP_ACTIONS
        fn = registry.get(action)
        if fn is None:
            logger.warn(f"未知 {kind} 动作: {action}（跳过）")
            return
        logger.step(f"  [{kind}] {action}")
        fn(ctx, self.system_cfg)
