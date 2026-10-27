#!/usr/bin/env python3
"""Windows onedir 打包发布组装脚本（feature/windows-cli，T4/T5/T6）。

功能：
1. 用 PyInstaller（spec: AtsCli.spec）打 onedir 控制台 exe（dist/AtsCli/）。
2. 组装发布目录：
   - AtsCli.exe + _internal/（PyInstaller 自动生成）
   - config/（★ 用户可编辑配置，T5：upload 收敛 + 去敏感项）
   - tools/ffmpeg/（ffprobe.exe / ffmpeg.exe / ffplay.exe 三件套）
   - run_normal.bat / run_stress.bat / run_aging.bat / run_no_network.bat
   - 使用说明.txt
3. 打 zip 交付物 dist/AtsCli_release.zip。

用法（在仓库根目录执行）：
    python scripts/build_windows_exe.py
    python scripts/build_windows_exe.py --python .venv-cli/Scripts/python.exe
    python scripts/build_windows_exe.py --skip-zip

说明：
- 打包机需装 pyinstaller（脚本会在指定解释器内检测，缺失时提示安装命令）。
- ffmpeg 三件套不随 PyInstaller 打进；优先取仓库 tools/ffmpeg/*.exe，其次 PATH，
  缺失时打 WARN 但不中断（发布前请补齐，目标机无 Python/PATH 时不可用）。
- 本脚本不改动 ATS/ 源码，纯打包侧工具，无需 devlog。
"""
import argparse
import os
import shutil
import subprocess
import sys
import zipfile

try:
    import yaml  # 打包机已有（.venv-cli）
except ImportError:  # pragma: no cover
    yaml = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "AtsCli.spec")
SRC_CONFIG = os.path.join(ROOT, "ATS", "config")
TOOLS_FFMPEG = os.path.join(ROOT, "tools", "ffmpeg")
DIST = os.path.join(ROOT, "dist")
ONEDIR = os.path.join(DIST, "AtsCli")
STAGING_CONFIG = os.path.join(DIST, "_atscli_config_src")   # 打包前收敛的内置配置临时 staging

FFMPEG_TOOLS = ("ffprobe.exe", "ffmpeg.exe", "ffplay.exe")

BAT_TEMPLATE = '@echo off\r\n".\\AtsCli.exe" --scenario {scenario} --no-interactive-wifi\r\n'

USAGE_TXT = """VX100 EVB 上位机自动化测试脚本 —— 发布版使用说明
======================================================

【运行环境】
- 目标机无需安装 Python / pip / venv。
- ffprobe.exe / ffmpeg.exe / ffplay.exe 已随包放在 tools\\ffmpeg\\ 目录；
  若运行含 rtmp 的场景，还需要 nginx-rtmp 服务监听 1935（另装/自带）。
- EVB 板需要 USB-UART 串口驱动（另装）。

【启动方式】
- 直接双击 run_*.bat，已默认携带 --no-interactive-wifi（自动用默认 WiFi，免交互）。
- 或命令行：
      .\\AtsCli.exe --scenario stress --no-interactive-wifi
      .\\AtsCli.exe --dry-run
      .\\AtsCli.exe --list-modules
      .\\AtsCli.exe --list-scenarios
      .\\AtsCli.exe --scenario normal --config-dir .\\config

【改配置（重点）】
- 改流程：编辑 config\\scenarios\\<场景名>.yaml（tasks 顺序 / repeat / duration / override / loop）。
- 新增场景：在 config\\scenarios\\ 新建 <name>.yaml（文件名即 --scenario 取值，需含 scenario: 段）。
- 改模块参数：编辑 config\\modules\\<module>.yaml（video/photo/rtmp/ftp/wifi 等）。
- 改环境参数：编辑 config\\system.yaml（串口 / WiFi / pc.ip）。

  注意：只改 exe 同级的 config\\ 目录；_internal\\ 里的同名文件是只读内置备份，勿动。

【场景说明】
- normal：WiFi/FTP 由 prepare 准备，tasks 4 项（emmc/photo/video/rtmp）。
- stress：photo×10 + video 长录 + rtmp 长推流，整轮循环（压测）。
- aging：photo×10 + rtmp 600s，限时 2h 循环（老化）。
- no_network：无网络纯拍摄/录像场景（不用 FTP / 推流）。
- stress_NoFtp_NoRtmp：无网络压测（不连 WiFi / 不启动 FTP / 不推流），photo×11 模式 +
  video×12 分辨率纯拍摄/录像，整轮循环 200 次；prepare 不挂 wifi_connect/ftp_ready/preview。

【防火墙（含 FTP 下载的 photo/video 场景）】
- 需放行 FTP 主动模式数据端口 1024-65535（及 RTMP 1935）。
- EVB IP 由路由器 DHCP 分配会漂移，规则 RemoteAddress 请用网段（如 192.168.1.0/24），勿写死单 IP。
"""


def _log(msg):
    print(f"[build] {msg}")


def _find_python(explicit):
    if explicit:
        return explicit
    cand = os.path.join(ROOT, ".venv-cli", "Scripts", "python.exe")
    if os.path.isfile(cand):
        return cand
    return sys.executable


def _run(cmd, **kw):
    _log("  $ " + " ".join(cmd))
    subprocess.check_call(cmd, **kw)


def build_onedir(python, config_src):
    if not os.path.isfile(SPEC):
        sys.exit(f"spec 不存在: {SPEC}")
    if not os.path.isdir(config_src):
        sys.exit(f"内置配置源目录不存在: {config_src}")
    if os.path.isdir(ONEDIR):
        _log(f"清理旧 onedir: {ONEDIR}")
        shutil.rmtree(ONEDIR, ignore_errors=True)

    # 检测 pyinstaller，缺失提示安装（不改源码，只做打包机准备）
    probe = subprocess.run(
        [python, "-c", "import PyInstaller"],
        cwd=ROOT, capture_output=True,
    )
    if probe.returncode != 0:
        sys.exit(
            "打包机缺少 PyInstaller。请先在开发/打包 venv 安装：\n"
            f"    {python} -m pip install pyinstaller\n"
            "（这是开发/打包机环境，与目标机无关。）"
        )

    _log("运行 PyInstaller（spec: AtsCli.spec）...")
    _log(f"  内置 fallback 配置源: {config_src}")
    env = dict(os.environ)
    env["ATSCLI_CONFIG_SRC"] = config_src
    _run([python, "-m", "PyInstaller", "--noconfirm", "--clean", SPEC],
         cwd=ROOT, env=env)
    if not os.path.isfile(os.path.join(ONEDIR, "AtsCli.exe")):
        sys.exit("PyInstaller 完成但未找到 dist/AtsCli/AtsCli.exe，打包失败")


def _release_system_yaml(dst_dir):
    """T5：复制 config 并收敛 system.yaml 的 upload（关闭 + 去敏感项）。

    fail-closed：无 pyyaml 时直接 SystemExit，禁止静默降级产出含敏感项的泄漏产物。
    """
    if yaml is None:
        raise SystemExit(
            "发布收敛失败：当前解释器缺少 pyyaml，无法安全收敛 system.yaml（upload 敏感项）。\n"
            "请用含 pyyaml 的解释器运行，例如：\n"
            "    .venv-cli\\Scripts\\python.exe scripts\\build_windows_exe.py\n"
            "或先安装：python -m pip install pyyaml"
        )

    os.makedirs(dst_dir, exist_ok=True)
    # 整目录复制后回写 system.yaml，保证 modules/scenarios 完整
    shutil.rmtree(dst_dir, ignore_errors=True)
    shutil.copytree(SRC_CONFIG, dst_dir)

    sys_path = os.path.join(dst_dir, "system.yaml")
    with open(sys_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    upload = dict(cfg.get("upload") or {})
    upload["enabled"] = False
    # 去敏感项：server / token_file / ca_cert 不随包分发
    upload.pop("server", None)
    upload.pop("token_file", None)
    upload.pop("ca_cert", None)
    cfg["upload"] = upload

    with open(sys_path, "w", encoding="utf-8") as f:
        f.write("# 发布版 system.yaml：upload 已关闭，上传服务地址/令牌文件/证书路径等敏感项已移除。\n")
        f.write("# 改环境参数（串口/WiFi/pc.ip）改本文件；模块参数改 modules/；流程改 scenarios/。\n")
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    _log(f"  system.yaml 已收敛：upload.enabled=false，已去除 server/token_file/ca_cert")


def _copy_ffmpeg(dst_dir):
    """随包放 tools/ffmpeg/ 三件套；优先仓库 tools/ffmpeg，其次 PATH。"""
    os.makedirs(dst_dir, exist_ok=True)
    for tool in FFMPEG_TOOLS:
        src = os.path.join(TOOLS_FFMPEG, tool)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dst_dir, tool))
            _log(f"  ffmpeg 套件命中仓库: tools/ffmpeg/{tool}")
            continue
        found = shutil.which(tool)
        if found:
            shutil.copy2(found, os.path.join(dst_dir, tool))
            _log(f"  ffmpeg 套件命中 PATH: {found}")
        else:
            _log(f"  WARN: 未找到 {tool}（仓库 tools/ffmpeg 与 PATH 均无）。"
                 f"发布前请补齐，否则目标机 rtmp 场景不可用。")


def _write_launchers(dst_dir):
    for name, scenario in (
        ("run_normal", "normal"),
        ("run_stress", "stress"),
        ("run_aging", "aging"),
        ("run_no_network", "no_network"),
        ("run_stress_NoFtp_NoRtmp", "stress_NoFtp_NoRtmp"),
    ):
        with open(os.path.join(dst_dir, f"{name}.bat"), "w", encoding="ascii",
                  newline="\r\n") as f:
            f.write(BAT_TEMPLATE.format(scenario=scenario))
    _log("  启动器 bat 已生成（normal/stress/aging/no_network/stress_NoFtp_NoRtmp）")


def assemble_release():
    if not os.path.isfile(os.path.join(ONEDIR, "AtsCli.exe")):
        sys.exit("请先打包：dist/AtsCli/AtsCli.exe 不存在")

    _log("组装发布目录 dist/AtsCli/ ...")
    _release_system_yaml(os.path.join(ONEDIR, "config"))
    _copy_ffmpeg(os.path.join(ONEDIR, "tools", "ffmpeg"))
    _write_launchers(ONEDIR)

    with open(os.path.join(ONEDIR, "使用说明.txt"), "w", encoding="utf-8",
              newline="\r\n") as f:
        f.write(USAGE_TXT)
    _log("  使用说明.txt 已生成")


def make_zip():
    zip_path = os.path.join(DIST, "AtsCli_release")
    if os.path.exists(zip_path + ".zip"):
        os.remove(zip_path + ".zip")
    _log("打 zip ...")
    shutil.make_archive(zip_path, "zip", root_dir=DIST, base_dir="AtsCli")
    _log(f"交付物: {zip_path}.zip")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Windows onedir exe 打包发布组装")
    ap.add_argument("--python", help="打包机 Python 解释器（默认 .venv-cli\\Scripts\\python.exe）")
    ap.add_argument("--skip-zip", action="store_true", help="不打 zip，只留 dist/AtsCli/ 目录")
    args = ap.parse_args(argv)

    python = _find_python(args.python)
    _log(f"打包机 Python: {python}")
    # 打包前先收敛一份内置配置 staging（T5 修正）：spec 的 --add-data 打进的是
    # 这份收敛后的配置，避免 exe 内部 _MEIPASS 备份含 upload server/token/ca_cert。
    os.makedirs(DIST, exist_ok=True)
    shutil.rmtree(STAGING_CONFIG, ignore_errors=True)
    _release_system_yaml(STAGING_CONFIG)
    build_onedir(python, STAGING_CONFIG)
    assemble_release()
    # 清理 staging（发布目录已含正式收敛后的 exe 同级 config/）
    shutil.rmtree(STAGING_CONFIG, ignore_errors=True)
    if not args.skip_zip:
        make_zip()
    _log("完成。发布目录: dist/AtsCli/  （可整个文件夹或 AtsCli_release.zip 给用户）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
