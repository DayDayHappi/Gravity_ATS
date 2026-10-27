# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec for AtsCli（feature/windows-cli 打包发布）。

用途：把 VX100 EVB 上位机自动化测试脚本打包成 Windows 自包含控制台 exe。
对应文档：docs/02_design/windows_cli_exe打包发布方案.md（T4 / T6）。

关键点：
- onedir（非 onefile）、控制台模式（非 --noconsole）：脚本有 input() 交互。
- --collect-submodules ATS：ATS/modules/__init__.py 用 importlib.import_module("ATS.modules")
  动态导入子模块（含 modules/utest 包），静态分析会漏，导致 exe 模块注册表为空。
- --add-data：把内置配置打进 _MEIPASS/ATS/config，作为 T1 的只读回退备份。
  ★ 打进的是「已收敛」配置（upload 关闭 + 去敏感项），由 build 脚本先收敛到 staging，
    再经 ATSCLI_CONFIG_SRC 指定；不直接打包源码 ATS/config 原始值（防内置备份含敏感项）。
- 隐藏导入：jinja2（reporter HTML 渲染）、serial.tools.list_ports（串口枚举）。
"""
import os

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = [
    "jinja2",
    "serial.tools.list_ports",
]
hiddenimports += collect_submodules("ATS")

# 内置 fallback 配置源：优先取 build 脚本预收敛的 staging（ATSCLI_CONFIG_SRC），
# 否则回退源码 ATS/config（手动跑 spec 时用，发布务必走 build 脚本做收敛）。
_config_src = os.environ.get("ATSCLI_CONFIG_SRC") or os.path.join("ATS", "config")
_config_src = os.path.abspath(_config_src)
if not os.path.isdir(_config_src):
    raise SystemExit(f"打包配置源目录不存在: {_config_src}")

a = Analysis(
    ["ATS/main.py"],
    pathex=["."],
    binaries=[],
    datas=[(_config_src, "ATS/config")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AtsCli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AtsCli",
)
