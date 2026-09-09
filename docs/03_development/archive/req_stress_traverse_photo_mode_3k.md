# 需求文档：新增场景 3k 录像压测（复制 stress_traverse_photo_mode）

> 提出方：Document Agent（按用户口述整理，交由 Code Agent 实施）
> 状态：待实施

## 1. 背景

现有场景 `stress_traverse_photo_mode`（`ATS/config/scenarios/stress_traverse_photo_mode.yaml`）
遍历全部拍照模式（`auto/single/mfnr/hdr_0~3`）+ video + video_integrity + rtmp 压测。

现需新增一个"3k 录像压测"场景：**配置内容与 `stress_traverse_photo_mode` 完全一致，
唯一差异是录像分辨率改为 3k**，其余（preview/prepare/loop/count/tasks 结构/duration/
video_integrity/rtmp/cleanup）全部不变。

## 2. 需求

复制 `stress_traverse_photo_mode.yaml` 为新文件，仅给 video task 增加 3k 分辨率 override：

- **除 video task 的 `override.video_resolution` 外，其余内容与源文件逐字一致**。
- 不改任何源码、不改 `config/modules/*.yaml` 全局默认值。

## 3. 关键事实（已核实，避免 Code Agent 重复调研）

- **当前 `stress_traverse_photo_mode.yaml` 的 video task 没有任何 `override`**
  （见该文件 L26-27：`- module: video` + `duration: 66`），分辨率完全继承
  `config/modules/video.yaml` 的 `video_resolution`。
- **模块默认分辨率当前是 `"1080p"`**：`video.yaml` L2 为 `video_resolution: "1080p"`。
  注意 commit `519e805`（"111"）刚把 `"3k"` 改回了 `"1080p"`（git 有记录：
  `-video_resolution: "3k"` → `+video_resolution: "1080p"`）。故"改为 3k"不能靠改模块默认，
  必须走场景级 override，否则会影响 normal/stress 等其他场景。
- **3k 档位合法**：`video.py` 只发 `cam_set video {resolution}`；固件回显
  `w(2520) * h(1890)`，实际落盘 **2268 × 3024**（竖屏，sensor 旋转后），
  见 `docs/05_handoff/current_status.md`「固件行为快照」。
- **override 机制已支持，无需改代码**：Runner 参数合并为「模块默认 + task.override」
  （`runner.py` L97-102 → `base.py` `_merge` → `video.py` L52 `config.get("video_resolution")`）。
  photo/rtmp/video_integrity 均无需覆盖。

## 4. 实现方式（纯配置，复制 + 一行 override）

建议文件：`ATS/config/scenarios/stress_traverse_photo_mode_3k.yaml`

```yaml
# 压测场景：遍历全部拍照模式 + 3k 录像（video/rtmp 时长与整轮循环次数自行按需配置）
# 与 stress_traverse_photo_mode.yaml 唯一差异：video task 用 override.video_resolution=3k
# 强制 3k 录像（不碰 config/modules/video.yaml 的全局默认 1080p）。
# 其余（preview/prepare/loop/video_integrity/rtmp/cleanup）与源文件完全一致。
scenario:
  name: stress_traverse_photo_mode_3k
  preview:
    enabled: true
  prepare:
    - serial_init
    - wifi_connect
    - preclean
    - ftp_ready
    - preview_start
  loop:
    enable: true
    count: 200
  tasks:
    - module: photo
      repeat: 1
      override:
        photo_modes: [auto, single, mfnr, hdr_0, hdr_1, hdr_2, hdr_3]
    - module: video
      duration: 66
      override:
        video_resolution: "3k"     # 唯一新增：3k 录像（覆写模块默认 1080p）
    - module: video_integrity
      override:
        input:
          source: "current_run"
          selection: "latest_unchecked"
          empty_input_policy: "skip"
    - module: rtmp
      duration: 66
  cleanup:
    - stop_stream
    - preview_stop
    - close_serial
```

> 上面的 `photo_modes` / `duration` / `count` / `video_integrity.override` 数值均从
> 源文件**原样复制**；若源文件后续改动，请以当时源文件内容为准，只额外加一行
> `video.override.video_resolution: "3k"`。

## 5. 场景内 name 字段与文件名

按惯例 `scenario.name` 需与文件名一致（去 `.yaml`），便于日志区分：

- 文件名：`stress_traverse_photo_mode_3k.yaml`（ASCII 安全，可被 `--scenario` 直接引用）
- `name: stress_traverse_photo_mode_3k`
- 用户口述的中文名「3k 录像压测」建议作为文件头部注释的第一行（便于识别），
  不写入 `scenario.name`（name 会进日志/report 字段，保持 ASCII 稳妥）。

CLI 调用（场景名 = 文件名去掉 `.yaml`，`list_scenarios` 自动发现，无需注册）：

```bash
python3 -m ATS.main --scenario stress_traverse_photo_mode_3k --no-interactive-wifi
```

## 6. 验收标准

- `python3 -m ATS.main --list-scenarios` 能看到 `stress_traverse_photo_mode_3k`。
- 跑一轮后，`video` 模块日志 `录像测试: 3k / 66s`（非 1080p），且视频路径/大小校验、
  video_integrity、rtmp 与源场景行为一致。
- `config/modules/video.yaml` 保持 `"1080p"` 不变（3k 只在场景 override 生效）。

## 7. 边界确认

- 本需求**不改源码**：现有 override 机制已够用，`video.py` 无需改动。
- 若 Code Agent 实施时发现 `cam_set video 3k` 后 video_integrity 的
  `expected_fps`/`expected_gop_size`（`video_integrity.yaml` 现为 30/30）或
  `video_min_size_kb` 阈值与 3k 落盘不符（如 3k 文件更大或 GOP 结构不同），
  **停下产出 `Document Agent Request`，不要自行调参**。
- 按工程红线 1，新增配置文件后需在 `docs/03_development/devlog/` 新建记录并更新 README 索引。
