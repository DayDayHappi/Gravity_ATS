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
  6. 返回退出码: 0 全过 / 1 有失败 / 2 环境配置错 / 130 用户中断
"""
import os
import sys
import argparse
import datetime as _dt

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
    p.add_argument("--list-ports", action="store_true", help="只枚举主机串口，不打开或探测")
    p.add_argument("--no-preview", action="store_true", help="本次关闭 ffplay 观察，不关闭 RTMP 自动判据")
    p.add_argument("--no-problem-prompt", action="store_true", help="结束时不询问问题记录（用于批处理）")
    p.add_argument("--input-dir", help="覆盖 video_integrity 的本地输入目录，选择全部匹配视频")
    p.add_argument("--raw", action="store_true",
                   help="串口终端模式下显示原始字节(不剥离ANSI颜色码)")
    return p.parse_args(argv)


def check_dependencies(system_cfg, scenario, config_dir) -> bool:
    """按本次实际任务检查依赖；本地 H265 场景不要求 pyserial/板端/网络。"""
    from ATS.platform.tools import resolve_tool, ToolError
    import importlib
    importlib.import_module("ATS.modules")
    from ATS.modules.base import get_module_cls

    missing = []
    needs_serial = "serial_init" in scenario.prepare or any(
        t.module != "video_integrity" for t in scenario.tasks)
    if needs_serial:
        try:
            import serial  # noqa: F401
        except ImportError:
            missing.append("pyserial (python -m pip install -r ATS/requirements-cli.txt)")

    checked = set()
    for task in scenario.tasks:
        cls = get_module_cls(task.module)
        if cls is None:
            missing.append(f"未注册模块: {task.module}")
            continue
        try:
            cfg = cls(load_module_config(task.module, config_dir))._merge(task.override)
        except (ConfigError, TypeError, ValueError) as exc:
            missing.append(str(exc))
            continue
        tool_name = {"rtmp": "ffprobe", "video_integrity": "ffmpeg"}.get(task.module)
        if tool_name:
            preferred = cfg.get(tool_name + "_path")
            key = (tool_name, str(preferred))
            if key not in checked:
                checked.add(key)
                try:
                    path = resolve_tool(tool_name, preferred)
                    logger.info(f"工具校验通过: {tool_name} = {path}")
                except ToolError as exc:
                    missing.append(str(exc))
    if missing:
        logger.error("配置/依赖检查失败:")
        for item in missing:
            logger.error(f"  - {item}")
        return False
    return True


def list_ports_cmd():
    from ATS.platform.ports import list_ports
    try:
        ports = list_ports()
    except (RuntimeError, OSError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 2
    print("主机串口（仅枚举，未打开设备）:")
    for item in ports:
        vid, pid = getattr(item, "vid", None), getattr(item, "pid", None)
        usb = f" VID:PID={vid:04X}:{pid:04X}" if vid is not None and pid is not None else ""
        print(f"  {item.device}: {getattr(item, 'description', '')}{usb}")
    if not ports:
        print("  未发现串口；请检查设备驱动与连接。")
    return 0


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
    """按「场景 / 日期」解析日志、报告、问题记录根目录，实现场景隔离 + 按天聚合。

    返回 ``(log_root, report_root, problem_root)``，三者均已按场景隔离；
    ``log_root``/``report_root`` 含当天日期（logger/reporter 在其下再建 ``<run_ts>/`` 子目录），
    ``problem_root`` 不含日期（问题记录稀疏，run_ts 已含日期，不按天打散）。

    结构（date=``%Y%m%d``，run_ts=``%Y%m%d_%H%M%S``）：

    - 日志（所有场景）: ``logs/<scenario>/<date>/<run_ts>/``
    - 报告 normal:      ``reports/<date>/<run_ts>/``
    - 报告 非 normal:   ``logs/<scenario>/report/<date>/<run_ts>/``
    - 问题记录（所有）: ``logs/<scenario>/problem/<run_ts>.log``

    用户显式 ``--output-dir`` 时，报告走 ``<output-dir>/<date>/<run_ts>/``，
    日志与问题记录路径不受影响（维持场景隔离）。
    """
    report_cfg = system_cfg.get("report", {}) or {}
    log_base = report_cfg.get("log_dir", "logs")
    report_base = report_cfg.get("output_dir", "reports")
    date = _dt.datetime.now().strftime("%Y%m%d")   # 每次运行取启动当天日期

    # 日志：所有场景（含 normal）统一 logs/<scenario>/<date>/，去掉中间冗余 logs 层
    log_root = os.path.join(log_base, scenario_name, date)
    # 问题记录：按场景聚合，不按天打散
    problem_root = os.path.join(log_base, scenario_name, "problem")

    # 报告：normal 走顶层 reports；非 normal 归入场景目录；--output-dir 时均走 override
    if scenario_name != "normal" and output_dir_override is None:
        report_root = os.path.join(log_base, scenario_name, "report", date)
    else:
        report_root = os.path.join(output_dir_override or report_base, date)
    return log_root, report_root, problem_root


def _record_test_problem(run_ts: str, problem_root: str) -> None:
    """测试结束时询问用户本次测试遇到的问题，有输入则记录到 ``problem_root/<run_ts>.log``。

    ``problem_root`` 不含日期层（如 ``logs/<scenario>/problem``）：问题记录稀疏、
    ``run_ts`` 已含日期，不按天打散，同场景的问题归入同一 problem 目录。
    """
    try:
        problem = input("\n本次测试有什么问题？(直接回车表示无问题): ").strip()
    except (EOFError, KeyboardInterrupt):
        problem = ""
    if not problem:
        return

    try:
        os.makedirs(problem_root, exist_ok=True)
    except OSError as e:
        logger.error(f"创建 problem 目录失败: {e}")
        return

    fname = os.path.join(problem_root, f"{run_ts}.log")
    try:
        with open(fname, "w", encoding="utf-8") as f:
            f.write(f"{problem}\n")
            f.write(f"\n时间戳: {run_ts}\n")
        logger.info(f"已记录本次测试问题到: {fname}")
    except OSError as e:
        logger.error(f"写入 problem 记录失败: {e}")


def _main(argv=None) -> int:
    args = parse_args(argv)
    config_dir = os.path.abspath(args.config_dir or CONFIG_DIR)
    # 保留系统控制台编码；重定向到旧代码页时用转义保底，不让报告流程因打印崩溃。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="backslashreplace")
            except (OSError, ValueError):
                pass

    if args.list_ports:
        return list_ports_cmd()
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
    if args.input_dir:
        module_overrides["video_integrity"] = {
            "input": {"source": "directory", "directory": os.path.abspath(os.path.expanduser(args.input_dir)),
                      "selection": "all"}}

    # 3. 初始化日志（按场景隔离目录）
    log_root, report_root, problem_root = _resolve_output_dirs(
        system_cfg, args.scenario, output_dir_override=args.output_dir)
    run_ts = logger.init_logger(log_root, verbose=args.verbose)
    logger.info(f"VX100 EVB 自动化测试启动，运行时间戳: {run_ts}")
    logger.info(f"日志目录: {log_root}  报告目录: {report_root}")

    # 4. 加载场景
    manager = ScenarioManager(config_dir)
    try:
        scenario = manager.load(args.scenario)
        if args.input_dir and not any(t.module == "video_integrity" for t in scenario.tasks):
            raise ConfigError("--input-dir 只适用于包含 video_integrity 任务的场景")
        manager._apply_module_overrides(scenario, module_overrides)
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
    interrupted = False
    try:
        results = manager.run(
            args.scenario,
            no_interactive_wifi=args.no_interactive_wifi,
            module_overrides=module_overrides,
            system_cfg=system_cfg,
            no_preview=args.no_preview,
        )
        interrupted = manager.interrupted
    except KeyboardInterrupt:
        interrupted = True
        results = manager.results
        if not results:
            from ATS.core.result import TestResult
            results.append(TestResult(name="interrupted", module="prepare", status="ERROR",
                                      scenario=args.scenario, message="用户在准备阶段中断"))
        logger.warn("测试中断，尝试生成已完成部分的报告")
    except ScenarioError as e:
        logger.error(f"测试中止: {e}")
        results = manager.results
        env_error = True
    except Exception as e:
        logger.error(f"测试执行异常: {e}")
        results = manager.results
        env_error = True

    # 7. 即使中断也生成已完成结果；报告失败不阻止日志句柄关闭。
    out_dir = os.path.join(report_root, run_ts)
    rpt_cfg = system_cfg.get("report", {})
    from ATS.core.reporter import generate as gen_report
    try:
        gen_report(results, out_dir,
                   junit=rpt_cfg.get("junit", True), html=rpt_cfg.get("html", True))
        if not args.no_problem_prompt and not interrupted:
            _record_test_problem(run_ts, problem_root)
    except KeyboardInterrupt:
        interrupted = True
        logger.warn("报告/交互阶段被中断")
    except Exception as exc:
        env_error = True
        logger.error(f"报告生成失败: {exc}")
    finally:
        logger.close()

    if interrupted:
        return 130
    if env_error:
        return 2
    has_fail = any(r.status in ("FAIL", "ERROR") for r in results)
    return 1 if has_fail else 0


def main(argv=None) -> int:
    """最外层资源边界；包括配置/依赖检查阶段的 Ctrl+C。"""
    try:
        return _main(argv)
    except KeyboardInterrupt:
        logger.warn("用户中断启动/检查阶段")
        return 130
    except Exception as exc:
        logger.error(f"启动/环境异常: {exc}")
        return 2
    finally:
        logger.close()


if __name__ == "__main__":
    sys.exit(main())
