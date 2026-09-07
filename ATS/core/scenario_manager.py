
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
from .cancellation import CancellationToken, OperationCancelled


class ScenarioError(Exception):
    """场景编排错误（环境不可用等）。"""


# ---------------------------------------------------------------------------
# prepare 动作
# ---------------------------------------------------------------------------

@prepare_action("serial_init")
def _action_serial_init(ctx, system_cfg):
    """串口探测 + 打开 + 就绪 + 自检，console 存入 ctx.console。"""
    ser_cfg = system_cfg.get("serial", {})
    port = ser_cfg.get("port", "auto")
    baudrate = ser_cfg.get("baudrate", 2000000)

    if port in ("auto", "", None):
        services = getattr(ctx, "platform_services", None)
        port_provider = getattr(services, "serial_ports", None) if services else None
        port, detected_baud = detect_port(
            baudrate=baudrate,
            baud_candidates=ser_cfg.get("baudrate_candidates"),
            interactive=True,
            detect_timeout=ser_cfg.get("detect_timeout", 2.0),
            cancellation_token=getattr(ctx, "cancellation_token", None),
            port_provider=port_provider,
            interaction_provider=getattr(ctx, "interaction_provider", None),
        )
        if port is None:
            raise ScenarioError("无法确定 EVB 串口，测试中止")
        baudrate = detected_baud

    services = getattr(ctx, "platform_services", None)
    registry = getattr(services, "serial_registry", None) if services else None
    owner = getattr(ctx, "run_id", "ats-test") or "ats-test"
    if registry is not None and not registry.acquire(port, owner):
        raise ScenarioError(f"串口 {port} 已被 {registry.owner(port)} 占用")
    ctx.serial_port = port
    ctx.serial_owner = owner

    console = SerialConsole(
        port=port, baudrate=baudrate,
        timeout=ser_cfg.get("timeout", 2.0),
        ready_timeout=ser_cfg.get("ready_timeout", 60),
        sentinel_timeout=ser_cfg.get("sentinel_timeout", 5.0),
        cancellation_token=getattr(ctx, "cancellation_token", None),
    )
    def release_local_console():
        try:
            console.close()
        except Exception:
            pass
        if registry is not None:
            registry.release(port, owner)

    try:
        console.open()
    except SerialError as e:
        release_local_console()
        raise ScenarioError(str(e))

    try:
        if not console.wait_for_ready():
            raise ScenarioError("EVB 未就绪（等待 msh 超时）")
        if not console.health_check():
            raise ScenarioError("串口自检失败，请检查波特率/接线")
    except BaseException:
        # ``ctx.console`` is not published until the port is healthy, so the
        # scenario cleanup action cannot see this local object. Close/release
        # here for cancellation, timeout, and unexpected failures alike.
        release_local_console()
        raise

    ctx.console = console


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

    from ..modules.wifi import (
        _SCAN_HEADER_RE, _SCAN_ROW_RE, _GOT_IP_RE, check_wifi_connected,
    )

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

    provider = getattr(ctx, "interaction_provider", None)
    use_default = True
    if not no_interactive and wifi_cfg.get("interactive", True):
        if provider is None:
            logger.warn("未提供 InteractionProvider，使用默认 WiFi 配置")
        else:
            use_default = provider.confirm(
                f"是否连接默认 WiFi [{default_ssid}]?", default=True
            )

    if no_interactive:
        ssid, pwd = default_ssid, default_pwd
        logger.info(f"--no-interactive-wifi：使用默认 WiFi [{ssid}] 自动连接")
    elif use_default:
        ssid, pwd = default_ssid, default_pwd
        logger.info(f"使用默认 WiFi: {ssid}")
    else:
        logger.info("扫描 WiFi 网络...")
        r = console.exec_sync("wifi scan", expect=_SCAN_HEADER_RE.pattern, timeout=15.0)
        aps = []
        for ln in r.clean.splitlines():
            m = _SCAN_ROW_RE.match(ln.strip())
            if m:
                aps.append((m.group(1), m.group(4)))
        if not aps:
            logger.error("扫描无结果，无法选择")
            return
        labels = [f"{s} (RSSI {rssi})" for s, rssi in aps]
        chosen = provider.choose("扫描到的 AP", labels, default_index=0)
        index = labels.index(chosen)
        ssid = aps[index][0]
        pwd = provider.ask_text(f"输入 [{ssid}] 的密码", secret=True)

    if not ssid:
        logger.error("SSID 为空")
        return

    ctx.wifi_ssid = ssid
    ctx.wifi_password = pwd
    r = console.exec_async(
        f"wifi join {ssid} {pwd}",
        expect=_GOT_IP_RE, send_timeout=5.0, result_timeout=30.0,
    )
    if r.success and r.matched:
        ctx.evb_ip = r.matched
        ctx.skip_wifi = True
        logger.info(f"WiFi 连接成功: {ssid} / IP={r.matched}")
        token = getattr(ctx, "cancellation_token", None)
        if token is None:
            time.sleep(5.0)
        elif token.wait(5.0):
            token.raise_if_cancelled()
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
        console.exec_sync("cd /", timeout=5.0)
        console.exec_async("dfs_video_stop",
                           expect=r"Save Video|Please start|recording completed",
                           result_timeout=8.0, honor_cancellation=False)
    except OperationCancelled:
        try:
            console.exec_async(
                "dfs_video_stop",
                expect=r"Save Video|Please start|recording completed",
                result_timeout=3.0,
                honor_cancellation=False,
            )
        except Exception as cleanup_exc:
            logger.warn(f"取消时预清理录像停止失败: {cleanup_exc}")
        raise
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
        services = getattr(ctx, "platform_services", None)
        RtmpServer(
            port=1935,
            backend=getattr(services, "rtmp_backend", None) if services else None,
        ).check_ready(cancellation_token=getattr(ctx, "cancellation_token", None))
    except RtmpServerError as e:
        logger.warn(f"preview_start: RTMP 服务端未就绪，跳过画面观察: {e}")
        return

    services = getattr(ctx, "platform_services", None)
    mgr = PreviewManager(
        preview_cfg,
        process_controller=getattr(services, "processes", None) if services else None,
        resource_locator=getattr(services, "resources", None) if services else None,
        desktop_environment=getattr(services, "desktop", None) if services else None,
    )
    mgr.start(url)
    ctx.preview_manager = mgr


# ---------------------------------------------------------------------------
# cleanup 动作
# ---------------------------------------------------------------------------

@cleanup_action("stop_stream")
def _action_stop_stream(ctx, system_cfg):
    """兜底停止 RTMP 推流（幂等，未推流则忽略）。"""
    console = getattr(ctx, "console", None)
    if console is None:
        return
    try:
        console.exec_async("rtmp_video_stop",
                           expect=r"Push Stop|Stop requested",
                           result_timeout=8.0, honor_cancellation=False)
    except Exception:
        pass


@cleanup_action("preview_stop")
def _action_preview_stop(ctx, system_cfg):
    """关闭画面观察 PreviewManager（ADR-010），释放 ffplay 重连 wrapper 及子进程。"""
    mgr = getattr(ctx, "preview_manager", None)
    if mgr is None:
        return
    try:
        stopped = mgr.stop()
        if stopped is False:
            logger.error("preview_stop 超时：保留 manager 引用以便再次清理")
            return
    except Exception as e:
        logger.warn(f"preview_stop 异常(可忽略): {e}")
        return
    ctx.preview_manager = None


@cleanup_action("close_serial")
def _action_close_serial(ctx, system_cfg):
    """关闭串口。"""
    console = getattr(ctx, "console", None)
    if console is not None:
        try:
            console.close()
        except Exception:
            pass
    services = getattr(ctx, "platform_services", None)
    registry = getattr(services, "serial_registry", None) if services else None
    port = getattr(ctx, "serial_port", None)
    owner = getattr(ctx, "serial_owner", None)
    if registry is not None and port and owner:
        registry.release(port, owner)


# ---------------------------------------------------------------------------
# ScenarioManager
# ---------------------------------------------------------------------------

class ScenarioManager:
    """加载并编排一个测试场景。"""

    def __init__(self, config_dir: str = None, interaction_provider=None, event_sink=None, run_id: str = "", **_kwargs):
        self.config_dir = config_dir or CONFIG_DIR
        self.interaction_provider = interaction_provider
        self.event_sink = event_sink
        self.run_id = run_id
        self.system_cfg = None
        self.ctx = None
        self.preview_cfg = {}   # scenario 层 preview 开关（ADR-010），load 时解析
        self.last_results = []
        self.cancellation_token = None

    def load(self, name: str) -> Scenario:
        """加载场景名 -> Scenario 对象（含参数合并前的原始 task）。"""
        raw = load_scenario(name, self.config_dir)
        self.preview_cfg = (raw.get("scenario") or {}).get("preview") or {}
        return self._parse_scenario(raw, name)

    def run(self, scenario_name: str, no_interactive_wifi: bool = False,
            module_overrides: dict = None, system_cfg: dict = None,
            cancellation_token: CancellationToken = None, platform_services=None) -> list:
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
        ctx.interaction_provider = self.interaction_provider
        ctx.run_id = self.run_id
        ctx.cancellation_token = cancellation_token or CancellationToken()
        ctx.platform_services = platform_services
        self.cancellation_token = ctx.cancellation_token
        self.ctx = ctx

        results = []
        try:
            # prepare
            for action in scenario.prepare:
                ctx.cancellation_token.raise_if_cancelled()
                self._run_action(action, ctx, "prepare")

            # tasks（loop 由 runner 控制）
            from .runner import TestRunner
            runner = TestRunner(
                self.system_cfg, ctx, scenario, event_sink=self.event_sink,
                cancellation_token=ctx.cancellation_token, config_dir=self.config_dir,
            )
            try:
                results = runner.run()
            finally:
                self.last_results = list(runner.results)
        finally:
            # cleanup 始终执行
            for action in scenario.cleanup:
                try:
                    self._run_action(action, ctx, "cleanup")
                except Exception as e:
                    logger.warn(f"cleanup 动作 {action} 异常: {e}")
            # 关闭 ctx 持有的资源（如 FTP 连接）
            try:
                ctx.cleanup()
            except Exception:
                pass

        self.last_results = list(results)
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
