#!/usr/bin/env python3
"""生成 ``ATS/config/scenarios/video_matrix.yaml``（cam_set video 全参数矩阵）。

用法（工程根目录）：

    python scripts/gen_video_matrix.py            # 覆盖写入场景文件
    python scripts/gen_video_matrix.py --dry-run  # 只打印条数，不写文件

取值域与合法性校验的唯一来源是 ``ATS/drivers/video_commands.py``，本脚本不重复定义
枚举/上下限，只负责按固定顺序展开并渲染 YAML。

固定顺序：res → fps → eis → codec → bitrate → gop → vui，便于日志对照与失败二分。

4k / 3k / 1080p 仅支持 30fps、3k 仅支持 eis 2（1080p 限制于真机 2026-11-23 确认），当前共 150 条。
"""
import argparse
import datetime
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from ATS.drivers import video_commands as vc  # noqa: E402

SCENARIO_PATH = os.path.join(
    _PROJECT_ROOT, "ATS", "config", "scenarios", "video_matrix.yaml")
DEFAULT_DURATION = 10

_HEADER = """\
# 由 scripts/gen_video_matrix.py 生成，请勿手改；改取值域请改 drivers/video_commands.py 后重新生成。
# 生成时间: {timestamp}
# 取值域: res={res} × fps={fps}（{fps_forced} 仅 30）× eis={eis}（3k 仅 2）× codec={codec}
#         × bitrate={bitrate} × gop={gop} × vui={vui}
# 组合数: {count} 条（末尾 video_integrity 不计入）
# 重新生成: python scripts/gen_video_matrix.py
scenario:
  name: video_matrix
  preview:
    enabled: false
  prepare:
    - serial_init
    - wifi_connect
    - preclean
    - ftp_ready
  loop:
    enable: false          # 单轮跑完矩阵即止；轮次由人工改
  tasks:
"""

_FOOTER = """\
    # ── 末尾：对本次下载的 H265 产物统一做完整性检测 ──
    # 矩阵内 ftp_download=false，本 task 仅在改用下载分支时才有输入；无文件时 skip。
    - module: video_integrity
      override:
        input:
          source: "current_run"
          selection: "all_unchecked"
          empty_input_policy: "skip"
  cleanup:
    - close_serial
"""


def _render_task(p: vc.VideoParams) -> str:
    duration = DEFAULT_DURATION
    return (
        "    - module: video\n"
        f"      duration: {duration}\n"
        "      override:\n"
        "        ftp_download: false\n"
        "        video_params:\n"
        f'          res: "{p.res}"\n'
        f"          fps: {p.fps}\n"
        f"          eis: {p.eis}\n"
        f'          codec: "{p.codec}"\n'
        f"          bitrate: {p.bitrate}\n"
        f"          gop: {p.gop}\n"
        f'          vui: "{p.vui}"\n'
    )


def build_text(timestamp: str) -> tuple:
    """返回 (yaml 文本, 组合数)。"""
    params = list(vc.iter_video_params())
    groups = []
    current = None
    for p in params:
        header = f"    # ── {p.res} / fps {p.fps} / eis {p.eis} ──\n"
        if current != (p.res, p.fps, p.eis):
            current = (p.res, p.fps, p.eis)
            groups.append(header)
        groups.append(_render_task(p))

    header = _HEADER.format(
        timestamp=timestamp,
        res="/".join(vc.VIDEO_RESOLUTIONS),
        fps="/".join(str(x) for x in vc.VIDEO_FPS),
        fps_forced="/".join(sorted(vc.VIDEO_FPS_FORCED)),
        eis="/".join(str(x) for x in vc.VIDEO_EIS_MODES),
        codec="/".join(vc.VIDEO_CODECS),
        bitrate="/".join(str(x) for x in (8000000,)),
        gop="/".join(str(x) for x in (30,)),
        vui="/".join(vc.VIDEO_VUI),
        count=len(params),
    )
    return header + "".join(groups) + _FOOTER, len(params)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成 video 全参数矩阵场景")
    parser.add_argument("--dry-run", action="store_true", help="只统计条数，不写文件")
    parser.add_argument("--output", default=SCENARIO_PATH, help="输出路径（默认场景目录）")
    args = parser.parse_args(argv)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text, count = build_text(timestamp)

    if args.dry_run:
        print(f"组合数: {count}")
        return 0

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"已写入 {args.output}（{count} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
