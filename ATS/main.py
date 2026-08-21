#!/usr/bin/env python3
"""VX100 EVB 上位机自动化测试脚本 - 入口（场景驱动）。

用法:
    python -m ATS.main --scenario normal
    python -m ATS.main --scenario stress --no-interactive-wifi
    python -m ATS.main --list-scenarios

流程:
  1. 解析 CLI（--scenario 指定场景，默认 normal）
  2. 加载 system.yaml + 目标 scenario
  3. 检查 PC 端依赖 (pyserial, ffprobe)
  4. 交给 ScenarioManager 编排：prepare -> tasks(loop) -> cleanup
  5. 生成 JSON/JUnit/HTML 报告
  6. 返回退出码: 0 全过 / 1 有失败 / 2 环境配置错
"""
import os
import sys
import argparse

# 支持作为模块运行 (python -m ATS.main) 和直接运行 (python ATS/main.py)
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ATS.core import logger
from ATS.core.config import (
    ConfigError, load_system, apply_overrides, list_scenarios,
    load_module_config, CONFIG_DIR,
)
from ATS.core.scenario_manager import ScenarioManager, ScenarioError
from ATS.drivers.rtmp_receiver import RtmpReceiver


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="VX100 EVB 自动化测试脚本")
    p.add_argument("--scenario", default="normal",
                   help="测试场景名（config/scenarios/<name>.yaml，默认 normal）")
    p.add_argument("--config-dir", help="配置目录(覆盖默认 ATS/config)")
    p.add_argument("--port", help="串口设备路径(覆盖配置)，不填则自动探测")
    p.add_argument("--baudrate", type=int, help="波特率(覆盖配置)")
    p.add_argument("--format", action="store_true", help="强制格式化 eMMC")
    p.add_argument("--wifi-ssid", help="WiFi SSID(覆盖配置)")
    p.add_argument("--wifi-password", help="WiFi 密码(覆盖配置)")
    p.add_argument("--no-interactive-wifi", action="store_true",
                   help="跳过 WiFi 交互，直接用配置的 SSID/密码")
    p.add_argument("--output-dir", help="报告输出目录")
    p.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    p.add_argument("--list-modules", action="store_true", help="列出所有可用模块")
    p.add_argument("--list-scenarios", action="store_true", help="列出所有可用场景")
    p.add_argument("--dry-run", action="store_true", help="仅校验配置和依赖，不执行")
    p.add_argument("--terminal", action="store_true",
                   help="交互式串口终端(类Xcom)：手动发命令、实时看板子返回，用于调试")
    p.add_argument("--raw", action="store_true",
                   help="串口终端模式下显示原始字节(不剥离ANSI颜色码)")
    return p.parse_args(argv)


def check_dependencies(system_cfg, scenario, config_dir) -> bool:
    """检查 PC 端依赖，返回是否有缺失。"""
    missing = []
    try:
        import serial  # noqa: F401
    except ImportError:
        missing.append("pyserial (pip install pyserial)")

    # ffprobe 在场景含 rtmp 时必需（实时探测 RTMP 流）
    if any(t.module == "rtmp" for t in scenario.tasks):
        rtmp_cfg = load_module_config("rtmp", config_dir)
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


def list_scenarios_cmd(config_dir):
    """列出所有可用场景。"""
    print("可用场景:")
    for name in list_scenarios(config_dir):
        print(f"  {name}")


def _resolve_output_dirs(system_cfg: dict, scenario_name: str,
                         output_dir_override: str = None) -> tuple:
    """按场景解析日志/报告根目录，实现场景间隔离。

    普通场景（normal）保持现状：日志 ``logs/``，报告 ``reports/``。
    其余场景（stress/aging 等）与普通隔离，统一归入日志根目录下：
    日志 ``<log_dir>/<scenario>/logs/``，报告 ``<log_dir>/<scenario>/report/``。

    返回 ``(log_root, report_root)``。
    """
    report_cfg = system_cfg.get("report", {}) or {}
    log_root = report_cfg.get("log_dir", "logs")
    report_root = output_dir_override or report_cfg.get("output_dir", "reports")
    # 非 normal 场景：日志与报告都按场景名隔离（用户显式 --output-dir 时不改日志根）
    if scenario_name != "normal" and output_dir_override is None:
        base = os.path.join(log_root, scenario_name)
        log_root = os.path.join(base, "logs")
        report_root = os.path.join(base, "report")
    return log_root, report_root


def _record_test_problem(run_ts: str, log_root: str) -> None:
    """测试结束时询问用户本次测试遇到的问题，有输入则记录到 ``logs/problem/``。"""
    try:
        problem = input("\n本次测试有什么问题？(直接回车表示无问题): ").strip()
    except (EOFError, KeyboardInterrupt):
        problem = ""
    if not problem:
        return

    problem_dir = os.path.join(log_root, "problem")
    try:
        os.makedirs(problem_dir, exist_ok=True)
    except OSError as e:
        logger.error(f"创建 problem 目录失败: {e}")
        return

    fname = os.path.join(problem_dir, f"{run_ts}.log")
    try:
        with open(fname, "w", encoding="utf-8") as f:
            f.write(f"{problem}\n")
            f.write(f"\n时间戳: {run_ts}\n")
        logger.info(f"已记录本次测试问题到: {fname}")
    except OSError as e:
        logger.error(f"写入 problem 记录失败: {e}")


def main(argv=None) -> int:
    args = parse_args(argv)
    config_dir = args.config_dir or CONFIG_DIR

    if args.list_modules:
        list_modules_cmd()
        return 0
    if args.list_scenarios:
        list_scenarios_cmd(config_dir)
        return 0

    # 1. 加载 system 配置
    try:
        system_cfg = load_system(config_dir)
    except ConfigError as e:
        print(f"[配置错误] {e}", file=sys.stderr)
        return 2

    # 2. CLI 覆盖 system（串口/WiFi/报告）
    system_overrides = {}
    if args.port:
        system_overrides["serial.port"] = args.port
    if args.baudrate:
        system_overrides["serial.baudrate"] = args.baudrate
    if args.wifi_ssid:
        system_overrides["wifi.default_ssid"] = args.wifi_ssid
    if args.wifi_password:
        system_overrides["wifi.default_password"] = args.wifi_password
    system_cfg = apply_overrides(system_cfg, system_overrides)

    # --terminal: 交互式串口终端（调试工具，独立分支，不走测试流程）
    if args.terminal:
        from ATS.tools.serial_terminal import run_from_args
        return run_from_args(args, system_cfg)

    # --format -> emmc 模块参数覆盖
    module_overrides = {}
    if args.format:
        module_overrides["emmc"] = {"format": True}

    # 3. 初始化日志（按场景隔离目录）
    log_root, report_root = _resolve_output_dirs(
        system_cfg, args.scenario, output_dir_override=args.output_dir)
    run_ts = logger.init_logger(log_root, verbose=args.verbose)
    logger.info(f"VX100 EVB 自动化测试启动，运行时间戳: {run_ts}")
    logger.info(f"日志目录: {log_root}  报告目录: {report_root}")

    # 4. 加载场景
    manager = ScenarioManager(config_dir)
    try:
        scenario = manager.load(args.scenario)
    except (ConfigError, ScenarioError) as e:
        logger.error(f"加载场景失败: {e}")
        logger.close()
        return 2
    logger.info(f"场景 [{scenario.name}] 任务: {[t.module for t in scenario.tasks]}")

    # 5. 检查依赖
    if not check_dependencies(system_cfg, scenario, config_dir):
        logger.close()
        return 2

    # --dry-run
    if args.dry_run:
        logger.info("dry-run: 配置与依赖校验通过，不执行测试")
        import importlib
        importlib.import_module("ATS.modules")
        from ATS.modules.base import get_module_cls
        for t in scenario.tasks:
            cls = get_module_cls(t.module)
            if cls is None:
                logger.error(f"未注册模块: {t.module}")
                logger.close()
                return 2
            logger.info(f"  模块 {t.module} 依赖: {getattr(cls, 'depends', [])}")
        logger.close()
        return 0

    # 6. 执行场景
    results = []
    env_error = False
    try:
        results = manager.run(
            args.scenario,
            no_interactive_wifi=args.no_interactive_wifi,
            module_overrides=module_overrides,
            system_cfg=system_cfg,
        )
    except ScenarioError as e:
        logger.error(f"测试中止: {e}")
        env_error = True
    except Exception as e:
        logger.error(f"测试执行异常: {e}")
        env_error = True

    # 7. 生成报告
    out_dir = os.path.join(report_root, run_ts)
    rpt_cfg = system_cfg.get("report", {})
    from ATS.core.reporter import generate as gen_report
    gen_report(results, out_dir,
               junit=rpt_cfg.get("junit", True),
               html=rpt_cfg.get("html", True))

    # 7.5 询问本次测试问题
    _record_test_problem(run_ts, log_root)

    logger.close()

    # 退出码：2 环境错 / 1 有失败 / 0 全过
    if env_error:
        return 2
    has_fail = any(r.status in ("FAIL", "ERROR") for r in results)
    return 1 if has_fail else 0


if __name__ == "__main__":
    sys.exit(main())
