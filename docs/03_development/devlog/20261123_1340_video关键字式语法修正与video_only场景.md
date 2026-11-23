# 2026-11-23 video 关键字式语法修正 + 新增 video_only 场景（43 条）

## Task

按 Document Agent 任务单实施两项（同批）：

1. **Level 2**：`cam_set video` 命令模板位置式 → 关键字式（真机 2026-11-23 确认固件唯一接受），并 `VIDEO_FPS_FORCED` 补 `1080p`；
2. **Level 1**：新增 `video_only.yaml` 场景（仅录像不下载、43 条真机实测可用组合、每条 3s）。

需求来源：`docs/03_development/archive/code_task_video_only场景.md` + `docs/05_handoff/next_step.md` P0（含语法修正）。
证据：`docs/04_testing/test_report_20261123_video关键字式60组合实测.md`、devlog `20261123_1315`。

## Changed

### 1. 语法修正（Level 2，ADR-011 唯一来源，纯常量）

- `ATS/drivers/video_commands.py`：
  - `VIDEO_SET_COMMAND` 位置式 → **关键字式**：
    `cam_set video {res} fps {fps} eis {eis} format {codec} bitrate {bitrate} gop {gop} vui {vui}`
    （旧写法 `{res} {fps} eis {eis} {codec}` 被固件拒：`bare number 30 not allowed, use "fps 30" or a keyword`）。
  - `VIDEO_FPS_FORCED` 补 `"1080p": (30,)`（真机确认 1080p 不支持 60fps）。
  - 模块 docstring 与 `iter_video_params` docstring 同步（枚举数 168→150）。
- `scripts/gen_video_matrix.py`：header 的「仅 30」档位改为按 `VIDEO_FPS_FORCED` 动态渲染；docstring 168→150。
- `ATS/config/scenarios/video_matrix.yaml`：重新生成（168→150 条，命令走新模板）。
- `stress.yaml` / `stress_NoFtp_NoRtmp.yaml` / `recovery_validation.yaml`：注释 `（168 条）`→`（150 条）`（纯注释）。
- `tests/test_video_params.py`：总数 168→150、1080p 计数 36→18、新增 `test_1080p_with_60fps` 拒绝例、命令断言改关键字式（长度 61→72）、最长命令上界 70→80。

### 2. 新增场景 `video_only`（Level 1，纯配置）

- 新建 `ATS/config/scenarios/video_only.yaml`：43 个 `video` task，每个 `duration: 3` + `override.ftp_download: false` + 7 键 `video_params`（固定 `bitrate 18000000 gop 30 vui 709`）。
- 组合取值（真机实测去重后 43 条）：
  - 3k fps30 eis2（×2 codec，强制 eis2 故仅 1 组）；
  - 1080p fps30 eis0/1/2（×2）；
  - sd1080p fps30 eis0/1/2（×2）；
  - sd1080p fps60 eis0/1/2-h264 + eis0/1-h265（**排除 eis2-h265 挂死组合**）；
  - 720p fps30/60 eis0/1/2（×2）；
  - 480p fps30/60 eis0/1/2（×2）。
- 排除：3k/1080p × fps60（固件拒，12 条）、sd1080p fps60 eis2 h265（固件 stop 挂死）。

## Reason

- 旧位置式模板与新固件不一致，任何 `video` task 下发均被拒 → 必须修（否则全场景 video 失效）。
- 用户 2026-11-23 要求把真机实测可用组合做成只录像的单元测试场景。

## Verification

### 离线

- `python -m unittest discover -s tests` → **130 tests OK**（含改后的 `test_video_params`，25 例本文件全过）。
- 15 个场景 `--dry-run` 全通过（exit 0）。
- 脚本校验 `video_only.yaml`：43 个 video task、`resolve_video_params` 全通过、组合唯一、固定参数正确、无挂死组合、3k/1080p 全 fps30。
- `grep -c "module: video" video_only.yaml` = 43；`video_matrix.yaml` = 150。

### 真机（COM21 @ 2000000，板卡冷启动 idle）

- `python -m ATS.main --scenario video_only --no-interactive-wifi --port COM21`
- **结果：43 条全 PASS（43/43，通过率 100%，总耗时 305.0s ≈ 7.1s/条）**；`result.json` status 全 `PASS`。
- 关键字式命令被固件正常接受（回显 `video: size=... fps=... eis=... format=...`），单条录像+收尾约 7.1s。
- **零 `busy` / 零 `stopping` / 零 `cannot record` / 零 `command not found`**（grep 计数 0），无卡死。
- 结果文件：`logs/video_only/report/20261123/20261123_133429/result.json`。
- 注：运行结束上传 Portal 失败（本地服务未启动），按 ADR-017 不改写测试结论，仅 warn。

## Known limitation

- `video_only` 未接 `video_integrity`（任务单明确：本场景只要录像成功，不做 H265 完整性检测）。
- 固件 bug `sd1080p fps60 eis2 h265` 挂死未修（转固件工程师），本场景已排除该组合。
- `video_matrix.yaml` 仍含 4k 组合（真机未测 4k，用户此前说暂不支持）；本次仅语法修正，未改动其取值域。
- 长录像/连续压测下各组合是否稳定，本次未验证（每条 3s 短录）。

## 备注（Document Agent 复核点）

- 语法修正落地（Level 2，已按 next_step P0 授权「无需新 ADR，ADR-011 范式，纯常量」实施）；`video_commands.py` docstring 已体现关键字式。
- `VIDEO_FPS_FORCED` 补 1080p 后，`iter_video_params` 总数 168→150；`video_matrix.yaml` 随之重生成（1080p 的 fps60 组合被裁剪 36→18）。
