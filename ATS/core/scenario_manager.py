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
    """
    ser_cfg = system_cfg.get("serial", {})
    port = ser_cfg.get("port", "auto")
    baudrate = ser_cfg.get("baudrate", 2000000)
    fingerprint_set = getattr(ctx, "serial_fingerprint", "default")

    if port in ("auto", "", None):
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


@prepare_action("power_switch_init")
def _action_power_switch_init(ctx, system_cfg):
    """探测上下电控制模块（ADR-015）：enabled 时对候选串口发上电帧探测控制器。

    - 幂等：``power_switch.enabled`` 为 false 时直接 return，零副作用。
    - 候选端口 = 全部可访问串口 减去已确定 EVB 的端口（ctx.console.port），
      防止把 EVB 误当控制器（控制器 115200 / EVB 2000000，帧协议也互斥）。
    - 探测成功后控制器保持长连接，存 ctx.power_switch，由 cleanup 关闭。
    """
    ps_cfg = system_cfg.get("power_switch", {}) or {}
    if not ps_cfg.get("enabled", False):
        return

    from ..drivers.power_switch import detect_power_switch, _accessible_ports

    console = getattr(ctx, "console", None)
    evb_port = getattr(console, "port", None)
    candidates = [p for p in _accessible_ports() if p != evb_port]
    if not candidates:
        logger.warn("power_switch_init: 无候选串口（可能未插控制器），跳过")
        return

    baudrate = ps_cfg.get("baudrate", 115200)
    reboot_delay = ps_cfg.get("reboot_delay")
    ps = detect_power_switch(candidate_ports=candidates, baudrate=baudrate,
                             reboot_delay=reboot_delay)
    if ps is None:
        logger.warn("power_switch_init: 未探测到上下电控制模块，跳过（后续 reboot 不可用）")
        return
    ctx.power_switch = ps


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

    def _run_action(self, action: str, ctx: Context, kind: str):
        registry = PREPARE_ACTIONS if kind == "prepare" else CLEANUP_ACTIONS
        fn = registry.get(action)
        if fn is None:
            logger.warn(f"未知 {kind} 动作: {action}（跳过）")
            return
        logger.step(f"  [{kind}] {action}")
        fn(ctx, self.system_cfg)
