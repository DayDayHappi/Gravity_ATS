# Code Agent 任务单：`stress.yaml` 录像命令替换为真机实测可用集（43 条）

> 由 Document Agent 出具。**状态：已定稿，可交 Code Agent 实施**（两项确认已由用户 2026-11-23 拍板，见 §0）。
> 需求来源：用户 2026-11-23「将刚才测试的可用的录像命令，放进 `stress.yaml` 替换掉原来的录像命令」。
> 作用分支：`feat/windows_rebuild_app_arch`。
> 变更级别：**Level 1**（纯场景配置，复用既有 `video` 模块能力）。
> 可用集来源：`video_only.yaml`（43 条，真机 43/43 PASS，devlog `20261123_1340`）。

## 0. 已确认（用户 2026-11-23，无需再问）

| # | 事项 | 结论 |
|---|---|---|
| C1 | 是否加 `4k` | **暂时不加**：只放 43 条实测可用集，`stress.yaml` 现有 `4k` 录像**删除** |
| C2 | `ftp_download` 策略 | **全 `false`**：43 条均 `ftp_download: false`（只录像不下载） |

> ⚠ **C2 连带影响（须 Code Agent 一并处理，见 §3）**：`ftp_download: false` 后 `video_integrity`（靠 FTP 下载产物做 H265 校验）将**无文件可检**。处置**二选一（见 §3）**：删除该 task（建议）／或保留并确认 `empty_input_policy: "skip"`。**勿留下「跑但不检查任何文件」的悬空配置。**

## 1. 目标

把 `ATS/config/scenarios/stress.yaml` 中现有的 **6 条** `video` task，替换为实测可用集（**43 条**，见 §2）。
`photo` 段、`video_integrity` 段、`rtmp` 段、`loop`、`prepare`、`cleanup` **均不动**。

## 2. 替换内容（43 条，取自 `video_only.yaml`）

| res | fps | 唯一可用组合 | 条数 |
|---|---|---|---|
| 3k | 30 | eis2 × h264/h265 | 2 |
| 1080p | 30 | eis0/1/2 × h264/h265 | 6 |
| sd1080p | 30 | eis0/1/2 × h264/h265 | 6 |
| sd1080p | 60 | eis0/1 × h264/h265 + eis2-h264 | 5 |
| 720p | 30 | eis0/1/2 × h264/h265 | 6 |
| 720p | 60 | eis0/1/2 × h264/h265 | 6 |
| 480p | 30 | eis0/1/2 × h264/h265 | 6 |
| 480p | 60 | eis0/1/2 × h264/h265 | 6 |
| **合计** | | | **43** |

- 固定：`bitrate 18000000`、`gop 30`、`vui 709`；
- **排除**：3k/1080p × fps60（固件拒）、`sd1080p fps60 eis2 h265`（固件 stop 挂死）；
- 顺序：沿用 `video_only.yaml` 顺序（res → fps → eis → codec）；
- 每条写法：`module: video` / `repeat: 1` / `duration: 20`（**保持 20s，不改 3s**）+ `override.ftp_download: false`（C2）+ `override.video_params`（7 键全写）。

## 3. 字段要点

- **`video_params` 7 键必须全写**（模块 `_merge()` 浅合并，override 整体替换默认段）；
- **每条加 `override.ftp_download: false`**（C2）；
- **`duration` 保持 20**（stress 语义；3s 是 `video_only` 的设定，不搬到这里）；
- **`video_integrity` task 处置（二选一，必做其一）**：
  - **建议：删除该 task** —— 本场景已全部 `ftp_download: false`，无下载产物，完整性检测无意义；
  - 或保留并确认其 `empty_input_policy: "skip"`（本轮 0 文件时跳过、不判 FAIL）。
  - ⚠ 不可留「跑但不检查任何文件」的悬空 task。
- 替换后计数：`grep -c "module: video"` = **43**，`module: photo` = 12，`module: rtmp` = 1；`video_integrity` 按上面处置（删除=0 / 保留=1）。

## 4. 验收标准

### 离线

1. `python3 -m ATS.main --dry-run --scenario stress` 契约校验通过；
2. `grep -c "module: video" ATS/config/scenarios/stress.yaml` = 43，且 43 条均 `ftp_download: false`；
3. 43 条 `video_params` 与 `video_only.yaml` 逐条一致（组合、bitrate/gop/vui）；
4. 无 `4k`（C1）；无 `sd1080p fps60 eis2 h265`；无 3k/1080p × fps60；
5. `video_integrity` 按 §3 处置（删除或确认 skip 语义），不得悬空。

### 真机（可选，视用户是否要求）

1. stress 单轮录像 43 条全 PASS；
2. 无 `busy` / `stopping` / `command not found`。

## 5. 影响提示（供用户判断，不阻塞）

- 43 条 × 20s ≈ **14.3 min/轮**纯录像（原 6 条 ≈ 2min），`loop.count` 200 时单场景时长显著增长；
- `ftp_download: false` 后 stress **不再做录像下载与 H265 完整性检测**（原设计二者皆有）；若后续要恢复下载/完整性校验，需重新开启 `ftp_download`。

## 6. 交付要求

1. 改 `ATS/config/scenarios/stress.yaml`（video 段替换为 43 条 + `ftp_download: false`；`video_integrity` 按 §3 处置）；
2. 写 devlog `<YYYYMMDD>_<HHMM>_stress录像命令替换为实测可用集.md`，含：改动条数、组合来源、C1/C2 结论、`video_integrity` 处置、离线证据；
3. 更新 `docs/03_development/devlog/README.md` 索引。
