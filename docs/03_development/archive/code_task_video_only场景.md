# Code Agent 任务单：新增 `video_only` 场景（仅录像、不下载，43 条可用组合）

> 由 Document Agent 出具。**状态：已就绪，可交 Code Agent 实施**。
> 需求来源：用户 2026-11-23「把 Code Agent 测出来可用的命令，写一个单元测试场景，叫 `video_only`，只录像不需要下载，每个命令录 3s」。
> 作用分支：`feat/windows_rebuild_app_arch`。
> 变更级别：**Level 1**（新增场景配置文件，复用既有 `video` 模块的能力，不改接口/协议）。
> 证据：[test_report_20261123](../04_testing/test_report_20261123_video关键字式60组合实测.md)、devlog `20261123_1315`。

## 1. 目标

新增 `ATS/config/scenarios/video_only.yaml`：逐条跑「真机实测可用」的 `cam_set video` 组合，**每条只录像不下载**，单条录 **3s**。

## 2. 组合取值（43 条，来自真机实测）

> 来源：60 组合实测后去重（`OK` 且按固件强制后有效 eis 归一）得 **43 个唯一可用组合**。
> 排除：`3k` 的 fps60（6）、`1080p` 的 fps60（6）——固件拒；`sd1080p fps60 eis2 h265`——固件 stop 挂死。

| res | fps | eis | codec | 条数 |
|---|---|---|---|---|
| 3k | 30 | 2（强制） | h264, h265 | 2 |
| 1080p | 30 | 0 / 1 / 2 | h264, h265 | 6 |
| sd1080p | 30 | 0 / 1 / 2 | h264, h265 | 6 |
| sd1080p | 60 | 0 / 1（×2 codec） + 2（仅 h264） | h264, h265 | 5 |
| 720p | 30 | 0 / 1 / 2 | h264, h265 | 6 |
| 720p | 60 | 0 / 1 / 2 | h264, h265 | 6 |
| 480p | 30 | 0 / 1 / 2 | h264, h265 | 6 |
| 480p | 60 | 0 / 1 / 2 | h264, h265 | 6 |
| **合计** | | | | **43** |

固定参数：`bitrate 18000000`、`gop 30`、`vui 709`。

## 3. 场景骨架

```yaml
# video_only：仅录像不下载，逐条跑真机实测可用的 43 个 cam_set video 组合，每条 3s。
# 组合来源：test_report_20261123_video关键字式60组合实测.md（60 组合实测去重）。
# 已排除：3k/1080p × fps60（固件拒）、sd1080p fps60 eis2 h265（固件 stop 挂死）。
scenario:
  name: video_only
  preview:
    enabled: false
  prepare:
    - serial_init
    - wifi_connect
    - preclean
    - ftp_ready
  loop:
    enable: false          # 单轮跑完即止；轮次由人工改
  tasks:
    - module: video
      duration: 3
      override:
        ftp_download: false
        video_params: {res: "3k",      fps: 30, eis: 2, codec: "h264", bitrate: 18000000, gop: 30, vui: "709"}
    # ...（共 43 条，取值见 §2）
```

### 3.1 字段要点

- **`duration: 3`**：每条录 3s（`video` 模块 `duration_key = "video_duration"`，task.duration 覆盖）。
- **`ftp_download: false`**：走 `video.py` 纯录像分支，完全不碰 FTP。
- **`video_params` 7 键必须全写**（模块 `_merge()` 是浅合并，override 整体替换默认段）。
- **不写 `video_integrity`**：本场景只要录像成功，不做 H265 完整性检测。
- **顺序**按 §2 表（res → fps → eis → codec），便于日志对照。

## 4. 验收标准

### 离线

1. `python3 -m ATS.main --dry-run --scenario video_only` 契约校验通过；
2. `grep -c "module: video" ATS/config/scenarios/video_only.yaml` = **43**；
3. 43 条 `video_params` 与 §2 表逐条一致（可用 `iter_video_params` 或脚本比对）。

### 真机

1. 43 条全 PASS（串口 `Video recording completed successfully.`）；
2. 无 `command not found`、无 `busy`、无 `stopping` 卡死；
3. 单条耗时记录（校准整轮预算）。

## 5. 明确不做

- ❌ 不改 `drivers/video_commands.py`（语法改关键字式是**另一条 P0 任务**，见 [next_step.md](../../05_handoff/next_step.md)；本场景文件先按**现有常量**写，语法修正落地后本场景无须变动即可复跑）；
- ❌ 不测 60 条中不可用的 17 条（12 SET_FAIL + 1 挂死 + 4 个 3k 重复）；
- ❌ 不在 `video.py` 内写循环（红线 2，43 条由 tasks 驱动）。

> ⚠️ **前置依赖**：本场景用 `video_params.res/fps/eis/codec/...` 接口，需 `video_commands.py` 的 **Level 2 语法修正先落地**（位置式→关键字式）才能真机跑通；否则下发被固件拒。请与 [next_step.md](../../05_handoff/next_step.md) 的 P0 一并实施。

## 6. 交付要求

1. 新建 `ATS/config/scenarios/video_only.yaml`（43 条）；
2. 写 devlog `<YYYYMMDD>_<HHMM>_新增video_only场景.md`，含组合来源、task 数、离线/真机证据；
3. 更新 `docs/03_development/devlog/README.md` 索引。
