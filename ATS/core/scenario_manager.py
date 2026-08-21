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
        port, detected_baud = detect_port(
            baudrate=baudrate,
            baud_candidates=ser_cfg.get("baudrate_candidates"),
            interactive=True,
            detect_timeout=ser_cfg.get("detect_timeout", 2.0),
        )
        if port is None:
            raise ScenarioError("无法确定 EVB 串口，测试中止")
        baudrate = detected_baud

    console = SerialConsole(
        port=port, baudrate=baudrate,
        timeout=ser_cfg.get("timeout", 2.0),
        ready_timeout=ser_cfg.get("ready_timeout", 60),
        sentinel_timeout=ser_cfg.get("sentinel_timeout", 5.0),
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


@prepare_action("wifi_connect")
def _action_wifi_connect(ctx, system_cfg):
    """交互式 WiFi 连接（默认 SSID 或扫描选 AP），连上存 ctx.evb_ip / ctx.skip_wifi。

    --no-interactive-wifi 时跳过交互，交由 wifi_join 模块用 system.wifi 默认参数连接。
    """
    if getattr(ctx, "no_interactive_wifi", False):
        logger.info("--no-interactive-wifi：跳过交互 WiFi 连接，交由 wifi_join 模块处理")
        return
    console = getattr(ctx, "console", None)
    if console is None:
        logger.warn("wifi_connect: 无 console，跳过")
        return

    from ..modules.wifi import _SCAN_HEADER_RE, _SCAN_ROW_RE, _GOT_IP_RE

    wifi_cfg = system_cfg.get("wifi", {})
    default_ssid = wifi_cfg.get("default_ssid", "")
    default_pwd = wifi_cfg.get("default_password", "")

    print("\n" + "=" * 50)
    print("WiFi 连接")
    print("=" * 50)
    use_default = True
    if wifi_cfg.get("interactive", True):
        ans = input(f"是否连接默认 WiFi [{default_ssid}]? [Y/n]: ").strip().lower()
        use_default = ans != "n"

    if use_default:
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
        f"wifi join {ssid} {pwd}",
        expect=_GOT_IP_RE, send_timeout=5.0, result_timeout=30.0,
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
        console.exec_sync("cd /", timeout=5.0)
        console.exec_async("dfs_video_stop",
                           expect=r"Save Video|Please start|recording completed",
                           result_timeout=8.0)
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
                           result_timeout=8.0)
    except Exception:
        pass


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

    def load(self, name: str) -> Scenario:
        """加载场景名 -> Scenario 对象（含参数合并前的原始 task）。"""
        raw = load_scenario(name, self.config_dir)
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
