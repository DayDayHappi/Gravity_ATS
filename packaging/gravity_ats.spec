# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir build for Gravity ATS.

Entry: ATS/gui/main.py (module ATS.gui.main)
"""
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

project_root = Path(SPECPATH).resolve().parent.parent
entry_script = project_root / "ATS" / "gui" / "main.py"

datas = [
    (str(project_root / "ATS" / "config"), "ATS/config"),
]
runtime_root = project_root / "runtime"
if runtime_root.is_dir():
    datas.append((str(runtime_root), "runtime"))

a = Analysis(
    [str(entry_script)],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=["serial.tools.list_ports"] + collect_submodules("ATS.modules"),
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
    name="GravityATS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GravityATS",
)
