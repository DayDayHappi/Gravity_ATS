#!/usr/bin/env python3
"""Gravity ATS command-line presentation."""
from __future__ import annotations

import argparse
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ATS.application.interaction import CliInteractionProvider
from ATS.application.models import RunRequest
from ATS.application.service import TestService
from ATS.core import logger
from ATS.core.config import CONFIG_DIR, ConfigError, apply_overrides, list_scenarios, load_system


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="VX100 EVB 自动化测试脚本")
    p.add_argument("--scenario", default="normal")
    p.add_argument("--config-dir")
    p.add_argument("--port")
    p.add_argument("--baudrate", type=int)
    p.add_argument("--format", action="store_true")
    p.add_argument("--wifi-ssid")
    p.add_argument("--wifi-password")
    p.add_argument("--no-interactive-wifi", action="store_true")
    p.add_argument("--output-dir")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--list-modules", action="store_true")
    p.add_argument("--list-scenarios", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--terminal", action="store_true")
    p.add_argument("--raw", action="store_true")
    return p.parse_args(argv)


def list_modules_cmd():
    import importlib

    importlib.import_module("ATS.modules")
    from ATS.modules.base import list_modules

    print("可用模块:")
    for name, cls in list_modules():
        deps = getattr(cls, "depends", []) or []
        print(f"  {name:16s} 依赖: {deps if deps else '无'}")


def list_scenarios_cmd(config_dir):
    print("可用场景:")
    for name in list_scenarios(config_dir):
        print(f"  {name}")


def _record_test_problem(run_ts: str, problem_root: str) -> None:
    try:
        problem = input("\n本次测试有什么问题？(直接回车表示无问题): ").strip()
    except (EOFError, KeyboardInterrupt):
        problem = ""
    if not problem:
        return
    os.makedirs(problem_root, exist_ok=True)
    path = os.path.join(problem_root, f"{run_ts}.log")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(f"{problem}\n\n时间戳: {run_ts}\n")
    print(f"[INFO] 已记录本次测试问题到: {path}")


def main(argv=None) -> int:
    args = parse_args(argv)
    config_dir = args.config_dir or CONFIG_DIR

    if args.list_modules:
        list_modules_cmd()
        return 0
    if args.list_scenarios:
        list_scenarios_cmd(config_dir)
        return 0

    if args.terminal:
        try:
            system_cfg = load_system(config_dir)
            overrides = {}
            if args.port:
                overrides["serial.port"] = args.port
            if args.baudrate:
                overrides["serial.baudrate"] = args.baudrate
            system_cfg = apply_overrides(system_cfg, overrides)
        except ConfigError as exc:
            print(f"[配置错误] {exc}", file=sys.stderr)
            return 2
        from ATS.tools.serial_terminal import run_from_args

        return run_from_args(args, system_cfg, CliInteractionProvider())

    system_overrides = {}
    if args.port:
        system_overrides["serial.port"] = args.port
    if args.baudrate:
        system_overrides["serial.baudrate"] = args.baudrate
    if args.wifi_ssid:
        system_overrides["wifi.default_ssid"] = args.wifi_ssid
    if args.wifi_password:
        system_overrides["wifi.default_password"] = args.wifi_password

    module_overrides = {"emmc": {"format": True}} if args.format else {}
    request = RunRequest(
        scenario=args.scenario,
        config_dir=config_dir,
        system_overrides=system_overrides,
        module_overrides=module_overrides,
        output_dir=args.output_dir,
        verbose=args.verbose,
        no_interactive_wifi=args.no_interactive_wifi,
        dry_run=args.dry_run,
    )
    service = TestService(interaction_provider=CliInteractionProvider())
    result = service.run(request)
    if result.error:
        print(f"[ERROR] {result.error}", file=sys.stderr)
    if not args.dry_run and result.run_id and result.problem_root and result.report_dir:
        _record_test_problem(result.run_id, result.problem_root)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
