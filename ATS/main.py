#!/usr/bin/env python3
"""VX100 EVB 上位机自动化测试脚本 - 入口。

用法:
    python -m ATS.main --config ATS/config/test_config.yaml
    python -m ATS.main --port /dev/ttyUSB0 --modules wifi_scan,wifi_join,emmc

流程:
  1. 解析 CLI / 加载配置 / schema 校验
  2. 检查 PC 端依赖 (pyserial, ffmpeg)
  3. 确定串口: --port 指定则用; 否则自动探测(指纹匹配+波特率回退)
  4. 打开串口 -> wait_for_ready -> health_check
  5. WiFi 交互连接 (默认 G-Demo 或扫描选 AP)
  6. 拓扑排序 enabled_modules, 依次执行
  7. 生成 JSON/JUnit/HTML 报告
  8. 返回退出码: 0 全过 / 1 有失败 / 2 环境配置错
"""
import os
import sys
import time
import argparse
import datetime as _dt

# 支持作为模块运行 (python -m ATS.main) 和直接运行 (python ATS/main.py)
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ATS.core import logger, config as cfg
from ATS.core.config import ConfigError, load_config, apply_overrides
from ATS.core.context import Context
from ATS.core.serial_console import SerialConsole, detect_port, SerialError
from ATS.core.runner import TestRunner
from ATS.core.reporter import generate as gen_report
from ATS.drivers.rtmp_receiver import RtmpReceiver


DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "config", "test_config.yaml")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="VX100 EVB 自动化测试脚本")
    p.add_argument("--config", default=DEFAULT_CONFIG, help="配置文件路径")
    p.add_argument("--port", help="串口设备路径(覆盖配置)，不填则自动探测")
    p.add_argument("--baudrate", type=int, help="波特率(覆盖配置)")
    p.add_argument("--modules", help="本次执行的模块(逗号分隔)，覆盖配置")
    p.add_argument("--skip", help="跳过的模块(逗号分隔)")
    p.add_argument("--format", action="store_true", help="强制格式化 eMMC")
    p.add_argument("--wifi-ssid", help="WiFi SSID(覆盖配置)")
    p.add_argument("--wifi-password", help="WiFi 密码(覆盖配置)")
    p.add_argument("--no-interactive-wifi", action="store_true",
                   help="跳过 WiFi 交互，直接用配置的 SSID/密码")
    p.add_argument("--output-dir", help="报告输出目录")
    p.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    p.add_argument("--list-modules", action="store_true", help="列出所有可用模块")
    p.add_argument("--dry-run", action="store_true", help="仅校验配置和依赖，不执行")
    p.add_argument("--terminal", action="store_true",
                   help="交互式串口终端(类Xcom)：手动发命令、实时看板子返回，用于调试")
    p.add_argument("--raw", action="store_true",
                   help="串口终端模式下显示原始字节(不剥离ANSI颜色码)")
    return p.parse_args(argv)


def check_dependencies(config):
    """检查 PC 端依赖，返回是否有缺失。"""
    missing = []
    try:
        import serial  # noqa: F401
    except ImportError:
        missing.append("pyserial (pip install pyserial)")

    # ffprobe 在启用 rtmp 时必需（实时探测 RTMP 流，无存盘降级可用）
    enabled = config.get("test", {}).get("enabled_modules", [])
    if any("rtmp" in m for m in enabled):
        rtmp_cfg = config.get("rtmp", {})
        tool_missing = RtmpReceiver.check_tools(
            rtmp_cfg.get("ffprobe_path", "ffprobe"),
        )
        for t in tool_missing:
            missing.append(t)

    if missing:
        logger.error("缺少依赖:")
        for m in missing:
            logger.error(f"  - {m}")
        return False
    return True


def list_modules_cmd():
    """列出所有已注册模块。"""
    import importlib
    importlib.import_module("ATS.modules")
    from ATS.modules.base import list_modules
    print("可用模块:")
    for name, cls in list_modules():
        deps = getattr(cls, "depends", []) or []
        print(f"  {name:16s} 依赖: {deps if deps else '无'}")


def interactive_wifi(console, config, ctx):
    """启动时交互式连接 WiFi。

    返回是否连接成功。成功则 ctx.skip_wifi=True, ctx.evb_ip=<ip>。
    """
    wifi_cfg = config.get("wifi", {})
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
        # 扫描并列出 AP
        logger.info("扫描 WiFi 网络...")
        from ATS.modules.wifi import _SCAN_HEADER_RE, _SCAN_ROW_RE, _GOT_IP_RE
        r = console.exec_sync("wifi scan", expect=_SCAN_HEADER_RE.pattern, timeout=15.0)
        aps = []
        for ln in r.clean.splitlines():
            m = _SCAN_ROW_RE.match(ln.strip())
            if m:
                aps.append((m.group(1), m.group(4)))
        if not aps:
            logger.error("扫描无结果，无法选择")
            return False
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
        return False

    ctx.wifi_ssid = ssid
    ctx.wifi_password = pwd
    # 执行连接
    from ATS.modules.wifi import _GOT_IP_RE
    r = console.exec_async(
        f"wifi join {ssid} {pwd}",
        expect=_GOT_IP_RE, send_timeout=5.0, result_timeout=30.0,
    )
    if r.success and r.matched:
        ctx.evb_ip = r.matched
        ctx.skip_wifi = True
        logger.info(f"WiFi 连接成功: {ssid} / IP={r.matched}")
        time.sleep(5.0)  # 等 wifi join 后板子状态稳定，再发下一条命令
        return True
    logger.error(f"WiFi 连接失败: {r.error}")
    logger.error(f"输出: {r.clean}")
    return False


def main(argv=None) -> int:
    args = parse_args(argv)

    # --list-modules
    if args.list_modules:
        list_modules_cmd()
        return 0

    # 1. 加载配置
    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"[配置错误] {e}", file=sys.stderr)
        return 2

    # --terminal: 交互式串口终端（调试工具，独立分支，不走测试流程）
    if args.terminal:
        from ATS.tools.serial_terminal import run_from_args
        return run_from_args(args, config)

    # CLI 覆盖
    overrides = {}
    if args.port:
        overrides["serial.port"] = args.port
    if args.baudrate:
        overrides["serial.baudrate"] = args.baudrate
    if args.format:
        overrides["emmc.format"] = True
    if args.wifi_ssid:
        overrides["wifi.default_ssid"] = args.wifi_ssid
    if args.wifi_password:
        overrides["wifi.default_password"] = args.wifi_password
    if args.output_dir:
        overrides["report.output_dir"] = args.output_dir
    if args.modules:
        overrides["test.enabled_modules"] = [m.strip() for m in args.modules.split(",") if m.strip()]
    if args.skip:
        skipset = {m.strip() for m in args.skip.split(",") if m.strip()}
        overrides["test.enabled_modules"] = [
            m for m in config["test"]["enabled_modules"] if m not in skipset
        ]
    config = apply_overrides(config, overrides)

    # 2. 初始化日志
    log_root = config.get("report", {}).get("log_dir", "logs")
    run_ts = logger.init_logger(log_root, verbose=args.verbose)
    logger.info(f"VX100 EVB 自动化测试启动，运行时间戳: {run_ts}")
    logger.info(f"启用模块: {config['test']['enabled_modules']}")

    # 3. 检查依赖
    if not check_dependencies(config):
        logger.close()
        return 2

    # --dry-run
    if args.dry_run:
        logger.info("dry-run: 配置与依赖校验通过，不执行测试")
        # 校验模块依赖
        import importlib
        importlib.import_module("ATS.modules")
        from ATS.modules.base import get_module_cls
        for name in config["test"]["enabled_modules"]:
            cls = get_module_cls(name)
            if cls is None:
                logger.error(f"未注册模块: {name}")
                logger.close()
                return 2
            logger.info(f"  模块 {name} 依赖: {getattr(cls, 'depends', [])}")
        logger.close()
        return 0

    # 4. 确定串口
    ser_cfg = config["serial"]
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
            logger.error("无法确定 EVB 串口，测试中止")
            logger.close()
            return 2
        baudrate = detected_baud

    # 5. 打开串口
    console = SerialConsole(
        port=port, baudrate=baudrate,
        timeout=ser_cfg.get("timeout", 2.0),
        ready_timeout=ser_cfg.get("ready_timeout", 60),
        sentinel_timeout=ser_cfg.get("sentinel_timeout", 5.0),
    )
    try:
        console.open()
    except SerialError as e:
        logger.error(str(e))
        logger.close()
        return 2

    if not console.wait_for_ready():
        logger.close()
        console.close()
        return 1
    if not console.health_check():
        logger.error("串口自检失败，请检查波特率/接线")
        console.close()
        logger.close()
        return 2

    # 6. 板子状态预清理（确保干净起点：回根目录、停录像）
    #    不主动 wifi disc：若板子还连着 WiFi，由 wifi_check 模块检测后跳过 scan/join
    #    不在此处碰 FTP：ftp_server 全程只在 wifi 连接后由 ftp 模块发一次
    #    上次运行可能残留：当前目录在 /emmc、录像进行中
    logger.info("预清理板子状态...")
    try:
        console.exec_sync("cd /", timeout=5.0)             # 回根目录，避免 cd emmc 残留
        console.exec_async("dfs_video_stop",               # 停录像（未在录则忽略）
                           expect=r"Save Video|Please start|recording completed",
                           result_timeout=8.0)
        # 不在此处发 ftp_server：全程只在 wifi 连接后由 ftp 模块启动一次，
        # 避免重复触发固件 "service go wrong, now wait restarting" 崩溃循环刷屏日志。
    except Exception as e:
        logger.warn(f"预清理异常(可忽略): {e}")

    # 7. WiFi 交互连接
    ctx = Context()
    if not args.no_interactive_wifi:
        if not interactive_wifi(console, config, ctx):
            logger.warn("WiFi 交互连接失败，将依赖 wifi_join 用例连接")

    # 8. 执行测试
    runner = TestRunner(config, console, ctx)
    try:
        results = runner.run()
    except Exception as e:
        logger.error(f"测试执行异常: {e}")
        results = runner.results

    # 8. 生成报告
    out_dir = os.path.join(config.get("report", {}).get("output_dir", "reports"), run_ts)
    rpt_cfg = config.get("report", {})
    gen_report(results, out_dir,
               junit=rpt_cfg.get("junit", True),
               html=rpt_cfg.get("html", True))

    # 9. 清理
    ctx.cleanup()
    console.close()
    logger.close()

    # 退出码
    has_fail = any(r.status in ("FAIL", "ERROR") for r in results)
    return 1 if has_fail else 0


if __name__ == "__main__":
    sys.exit(main())
