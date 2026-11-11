# Code Agent 任务单：photo/video/rtmp 启动停止命令迁移到 `cam_run` 命令族

> 由 Document Agent 出具，交 Code Agent 执行。
> **状态：已就绪，待 Code Agent 实施**（需求来源：用户 2026-11-10；三项待确认已全部拍板，见 §5）。
> 作用分支：`feat/windows_rebuild_app_arch`（基于 `feature/windows-cli`）。
> 变更级别：**Level 1**（仅 `drivers/*_commands.py` 协议常量的值）。
> **无需新 ADR**：命令/判据集中在 `drivers/<module>_commands.py` 是 [ADR-011](../../02_design/decision_record/ADR-011-串口协议集中化.md) 既定范式，本次只改常量值，不改架构。
> 文档预授权：本任务属 Level 1，**Document Agent 已复核**，Code Agent 不需要再发 `Document Agent Request`；实施后按 §8 写 devlog 即可。

## 1. 目标

把三组「开始 / 停止」串口命令由旧命令族（`dfs_*`、`rtmp_video_*`）迁移到固件新命令族 `cam_run *`。
除命令字面量外**不得改变任何判定语义、时序、超时结构或模块编排**。

## 2. 命令对照表（唯一权威）

| 动作 | 旧命令 | 新命令 | 常量 |
|---|---|---|---|
| 开始拍照 | `dfs_capture_start` | `cam_run photo` | `PHOTO_CAPTURE_COMMAND` |
| 开始录像 | `dfs_video_start` | `cam_run video start` | `VIDEO_START_COMMAND` |
| 停止录像 | `dfs_video_stop` | `cam_run video stop` | `VIDEO_STOP_COMMAND` |
| 开始推流 | `rtmp_video_start <url>` | `cam_run live start <url>` | `RTMP_START_COMMAND`（保留 `{url}` 占位 + `.format`） |
| 停止推流 | `rtmp_video_stop` | `cam_run live stop` | `RTMP_STOP_COMMAND` |

**本任务不涉及**（用户 2026-11-10 确认保持原样，见 §5.3）：

- `cam_set photo {mode}`（`PHOTO_SET_COMMAND`）
- `cam_set video <组合>`（`VIDEO_PROFILES[*].command`）
- `cam_set live bitrate {bitrate}`（`RTMP_BITRATE_COMMAND`）
- `ftp_server`、eMMC / WiFi 命令

## 3. 精确改动锚点

### 3.1 协议定义（**必须改**）

| 文件 | 行 | 改动 |
|---|---|---|
| `ATS/drivers/photo_commands.py` | L31 | `PHOTO_CAPTURE_COMMAND = "cam_run photo"` |
| `ATS/drivers/video_commands.py` | L48 | `VIDEO_START_COMMAND = "cam_run video start"` |
| `ATS/drivers/video_commands.py` | L49 | `VIDEO_STOP_COMMAND = "cam_run video stop"` |
| `ATS/drivers/rtmp_commands.py` | L8 | `RTMP_START_COMMAND = "cam_run live start {url}"` |
| `ATS/drivers/rtmp_commands.py` | L9 | `RTMP_STOP_COMMAND = "cam_run live stop"` |

### 3.2 注释 / docstring 中的旧命令字样（**同步改，属纯文字**）

同一提交内清理，避免后续 Agent 按注释找命令：

| 文件 | 位置 |
|---|---|
| `ATS/core/serial_console.py` | L10、L81、L305、L437（`dfs_capture_start` / `rtmp_video_start` 举例） |
| `ATS/drivers/preview_manager.py` | L12-13（`rtmp_video_stop` / `rtmp_video_start`） |
| `ATS/modules/photo.py` | L10（`dfs_capture_start`） |
| `ATS/modules/rtmp.py` | L6、L8、L24、L99、L120、L135（`rtmp_video_*`） |
| `ATS/modules/video.py` | L120、L211（`dfs_video_start`） |
| `ATS/README.md` | L215、L218、L228、L243（命令示例与 FAQ） |
| `tests/test_video_bug007.py` | L5（docstring） |

> 注：`ATS/README.md` 位于 `ATS/` 目录下，属 Code Agent 可改范围。
> `tests/test_video_bug007.py` L40 用 `commands.VIDEO_START_COMMAND` 常量比较，**无需改逻辑**。

### 3.3 明确不改

- `ATS/modules/*.py` 的业务逻辑（除 3.2 注释）：全部经 `commands.*` 引用，迁移后自动生效。
- `ATS/config/**/*.yaml`：命令不在配置层（ADR-011）。
- `ATS/core/scenario_manager.py` L407 / L572：引用常量，无需改。
- 各 `*_TIMEOUT` 时长值：本次不变（若真机实测新命令耗时明显不同，只在 devlog 记录，不在本任务调值）。

## 4. 判定语义与风险（必须知情）

用户已确认：**新固件 `cam_set` 之后不再打印设置成功信息**。

现状（已核实）：脚本**从未依赖** `cam_set` 的正向成功打印，四处 `cam_set` 全是 `exec_sync(..., expect=None)` 负向判定：

| 调用点 | 判定方式 | 失败兜底 |
|---|---|---|
| `modules/photo.py:117` `cam_set photo` | `_ERROR_RE` 无错误关键字即成功 | 后续 `cam_run photo` 超时 → FAIL |
| `modules/video.py:99`、`:191` `cam_set video` | `_ERROR_RE` + `VIDEO_SET_ERROR` 二次判定 | **无**（分辨率未生效时可能按旧档录完仍 PASS） |
| `modules/rtmp.py:104` `cam_set live bitrate` | `_ERROR_RE` | **无** |

**因此本次迁移本身不会因「无成功打印」而 FAIL**；但存在「固件静默忽略设置 → 假 PASS」的既有风险，**用户已决定本次不处理**（§5.2）。

## 5. 已确认事项（用户 2026-11-10，无需再查）

### 5.1 ✅ 已确认：业务完成字符串**无变化**

新命令族仍输出原有业务完成串，`*_EXPECT` **一律不改**：

```text
PHOTO_CAPTURE_EXPECT = r"Capture completed successfully."
VIDEO_START_EXPECT   = r"Record Start|f_index\s*="
VIDEO_STOP_EXPECT    = r"Video recording completed successfully."
VIDEO_CLEANUP_EXPECT = r"Save Video|Please start|recording completed"
RTMP_START_EXPECT    = r"publish ready|Push Start"
RTMP_STOP_EXPECT     = r"Push Stop|Stop requested"
```

因此实施时**只改 5 个 `*_COMMAND` 常量值 + 注释**，判定链路零改动。

> 真机验证时仍按 §7 检查 TX 行与 PASS 结果；若出现判据不匹配，按「命令不被识别」与「完成串不匹配」区分后回报。

### 5.2 ✅ 已确认：`cam_set` 判据加固**本次不做**

`cam_set` 静默失败风险（video 分辨率无从校验、rtmp bitrate 无兜底、`_ERROR_RE` 不含 `unknown|unsupported`）**保持现状**，用户决定暂不处理。已记入 `05_handoff/known_issue.md` 待后续决策。

### 5.3 ✅ 已确认：`cam_set` **不改名**

`cam_set photo {mode}` / `cam_set video <组合>` / `cam_set live bitrate {bitrate}` 保持原字面量，本次零改动。

## 6. 禁止做法

- ❌ 在 `modules/*.py` 里内联 `"cam_run ..."`（违反 ADR-011）。
- ❌ 用命令回显（如 `cam_run photo` 自身）当 `exec_async` 的 expect。
- ❌ 为「等不到完成串」而把 expect 放宽成万能匹配（如 `.*`、`msh />`）。
- ❌ 借本次改动调整超时值、时序、`sleep`、重试次数。
- ❌ 修改 `docs/01_architecture/`、`docs/02_design/`、`docs/04_testing/`、`docs/05_handoff/`（Document Agent 负责同步）。
- ❌ 修改 `docs/03_development/archive/` 下的历史文档。

## 7. 验收标准

### 离线（必须全绿）

1. `grep -rn "dfs_capture_start\|dfs_video_start\|dfs_video_stop\|rtmp_video_start\|rtmp_video_stop" ATS tests` → **0 命中**（`docs/` 与 `.ats_cli_backups/` 除外）；
2. `grep -rn "cam_run" ATS/drivers ATS/modules` → 命中仅落在 5 个 `*_COMMAND` 常量定义处（modules 内为 0，证明业务层零内联）；
3. `python -m unittest discover -s tests` 全过（本分支基线 **90 tests OK**，2026-11-10 实测；mock 走常量，不受影响）；
4. `grep -rn "cam_run\|dfs_" ATS/config` → 无命令字面量（配置层不得出现协议串）。

### 真机（必须回填）

1. `python3 -m ATS.main --scenario normal`，photo / video / rtmp 全 PASS；
2. `serial.log` 中 TX 行确认为新命令（含 `cam_run live start rtmp://<pc_ip>/live/cam` 完整 URL，且未出现 `command not found` / 截断）；
3. 记录每条新命令到实际完成串的耗时，与迁移前对比（参考 `04_testing/test_report_20261105_压测耗时分析.md`：photo 3.56s、video 22.36s/轮）；
4. 若某项 FAIL，先区分「命令不被识别」与「判据字符串不匹配」，把原始日志贴进 devlog 再回报。

## 8. 交付要求（Code Agent 的文档义务）

只允许改：`ATS/drivers/photo_commands.py`、`video_commands.py`、`rtmp_commands.py`、上述 `ATS/` 内注释文件、`ATS/README.md`、`tests/`（若需）、`docs/03_development/devlog/`。

必须：

1. 新建 `docs/03_development/devlog/<YYYYMMDD>_<HHMM>_cam_run命令族迁移.md`，含：Change / Files / Reason / Verification（离线 + 真机原始日志片段） / 判据字符串是否变化 / Known limitation；
2. 在 `docs/03_development/devlog/README.md` 索引追加一行；
3. 在 devlog 中**逐条列出最终生效的 `*_COMMAND` 值**（Document Agent 据此同步 `01_architecture/module_design.md`、`data_flow.md`、`04_testing/test_case.md`、`05_handoff/`）；`*_EXPECT` 不变，无需列出；
4. 若真机发现某条命令 `command not found` / 被截断 / 完成串不匹配，**先回报再决定**，不要自行凑判据。

## 9. 完成后 Document Agent 的同步范围（不在本任务内）

- `01_architecture/module_design.md`（photo/video/rtmp 的 Input/Output 命令与判据）、`data_flow.md`（主判据串）、`system_architecture.md`（若举例过时）；
- `04_testing/test_case.md`（TC-006/007/008 输入列）、`test_strategy.md`（如判据变化）；
- `05_handoff/current_status.md`、`known_issue.md`、`next_step.md`；
- `02_design/decision_record/ADR-011` 等 ADR 中的旧字面量属历史记录，**不加改**（只在其 Status/备注需要时追加说明）。

---

## 10. 第二批（**未授权，待用户确认**）：`cam_set` 语法变更

> 用户 2026-11-10 提供固件新语法。**本批尚未拍板，Code Agent 不得实施**。
> **2026-11-10 更新**：用户已确认「每条参数显式写全、全排列」原则，
> 具体实施方案已拆出独立任务单 → [code_task_cam_set视频参数矩阵.md](code_task_cam_set视频参数矩阵.md)。
> 本节保留为语法/冲突/待确认项的原始记录。

### 10.1 固件给出的新语法

```text
cam_set video <4k|3k|1080p|sd1080p|720p|480p> [fps] [eis N] [h264|h265] [bitrate N] [gop N] [vui N]
cam_set photo <auto|single|mfnr|hdr|fcov|heif> [12m|8m|w8m|3m|1080p|720p|480p] [num]
cam_set live  <4k|1080p|sd1080p|720p|480p> [fps] [eis N] [bitrate N] [gop N] [vui N]
```

- `<res>` 后紧跟的**裸数字是帧率（30 / 60）**，不再是旧组合 ID 的变体序号。
- `eis N`：0=关 / 1=在线 / 2=离线；3k 强制离线。
- `bitrate` 50000–25000000；`gop` 0–1000；`vui`：709 / 6010 / 6011。
- `photo [num]`：hdr 下为连拍张数（0–3）；single 下为帧率（30/60）；其他模式忽略。
- photo 参数顺序自由（`photo 1080p single` ≡ `photo single 1080p`）。
- heif/heic 固定 1920×1440，不参与尺寸表校验。
- **录制/推流进行中配置会被拒绝（返回 busy）**。

### 10.2 与现状的冲突（已核实，勿重复论证）

| # | 冲突点 | 现状锚点 |
|---|---|---|
| 1 | 新语法仅 6 个视频分辨率名，**旧的 `_0/_1/_2` 变体选择不复存在** | `video_commands.py` L24-40 共 13 个组合：`sd1080p_2`=2016×1034、`720p_2`=1600×900、`480p_2`=800×600、`hd1080p_2`=1296×2304 竖屏，均为尺寸/方向不同的独立命令 |
| 2 | **`hd1080p` 已从固件列表消失**（旧唯一竖屏 1080p 档） | 同上；4 个场景引用 `hd1080p_1/_2` |
| 3 | 旧 `cam_set video <res> 0/1/2` 中的尾数字在新语法里会被当作 fps，**0/1/2 非法** | 13 个 profile 的 command 全部以 `" <0|1|2>"` 结尾 |
| 4 | `cam_set live bitrate N`（无 res）可能已非法 | `rtmp_commands.py` L17 `RTMP_BITRATE_COMMAND = "cam_set live bitrate {bitrate}"`；`modules/rtmp.py` L102-109 |
| 5 | 新增 codec 选择（h264/h265），但脚本产物扫描硬编码 `.h265` | `modules/video.py` L141/L230 正则 `\.h265`；`video_integrity.yaml` patterns `*.h265/*.hevc` |
| 6 | **busy 拒绝**：现有 cam_set 判定为纯负向（`_ERROR_RE`），不认识 `busy` | `core/serial_console.py` L70-74；`modules/photo.py` L117、`video.py` L99/L191、`rtmp.py` L104 |
| 7 | photo 新增 `fcov` 模式与 `8m/w8m/3m` 尺寸，现有枚举未覆盖 | `photo_commands.py` L14-27 `PHOTO_MODES` |
| 8 | `preclean` 只停录像、不停推流；残留推流会使后续 cam_set 返回 busy | `core/scenario_manager.py` L397-411 |

### 10.3 用户已确认的枚举原则（2026-11-10）

**每条命令的所有参数必须显式写全，每个取值组合单独作为一条 task，全排列遍历。**
命令形态固定为：

```text
cam_set video <res> <fps> eis <N> <h264|h265> bitrate <N> gop <N> vui <N>
```

组合数公式：

```text
N = fps数 × codec数 × bitrate数 × gop数 × vui数 × Σ_res(eis数)
其中 3k 的 eis 只有 1 种（固件强制离线），其余 5 个 res 各 3 种（0/1/2）
```

即 `N = 2 × 2 × Nb × Ng × Nv × (5×3 + 1×1) = 64 × Nb × Ng × Nv`。

| bitrate 数 | gop 数 | vui 数 | 组合总数 | 纯录像 22.4s/条 | 含 FTP 下载约 40s/条 |
|---|---|---|---|---|---|
| 1 | 1 | 1 | 64 | 0.4 h | 0.7 h |
| 1 | 1 | 3 | 192 | 1.2 h | 2.1 h |
| 3 | 3 | 3 | 1728 | 10.8 h | 19.2 h |

### 10.4 待用户答复（仅剩取值集合与落点）

> 组合数量已按用户「全排列」原则确定（§10.3）。以下仅剩**每个维度取哪些值**和**跑在哪个场景**。默认值已给出建议，用户只需确认或修改。

| # | 问题 | 建议默认（若用户不回即按此实施） |
|---|---|---|
| Q1 | fps 取值集合 | `[30, 60]`（固件仅这两种） |
| Q2 | eis 取值集合 | `[0, 1, 2]`；3k 强制离线，只发 `eis 2`（不重复发 3 次） |
| Q3 | codec 取值集合 | `[h264, h265]` |
| Q4 | **bitrate 取值集合**（50000–25000000） | `[8000000]` 单值起步；若要覆盖边界用 `[50000, 8000000, 25000000]`（组合数 ×3） |
| Q5 | **gop 取值集合**（0–1000） | `[30]` 单值起步；若要覆盖边界用 `[0, 30, 1000]`（组合数 ×3） |
| Q6 | vui 取值集合 | `[709, 6010, 6011]`（固件仅这三种） |
| Q7 | 命令里参数顺序 | 固定 `res fps eis N codec bitrate N gop N vui N`（显式写全，不依赖固件顺序自由） |
| Q8 | 跑在哪个场景 | **新建 `video_matrix.yaml`**，不改 `stress`/`video_size_traverse`（后者保留旧遍历用于回归对照） |
| Q9 | 5 个旧变体（2016×1034 / 1600×900 / 800×600 / 1296×2304 / `hd1080p`） | 新语法无法表达 → **从新矩阵场景中排除**，旧场景保留但标记「待固件确认后删除」 |
| Q10 | 两档分辨率无法表达的尺寸如何校验 | 矩阵场景**不做尺寸断言**（`width/height` 置 0 表示未校准），只校验录制成功 + 文件大小 + 可选 H265 完整性 |
| Q11 | 每条 task 时长 / 是否下载 | `duration: 10`，`ftp_download: false`（矩阵量大，先只验证命令被接受与录制成功；下载校验抽 1 条/分辨率单独跑） |
| Q12 | h264 任务的 H265 完整性检测 | 仅 `h265` 组合后接 `video_integrity`；h264 跳过（模块只解析 H265） |

**若 Q4/Q5 采用单值，总组合数 192（约 1.2h 纯录像）；若全取 3 值则 1728 条（约 10.8h）。请确认取哪一档。**

### 10.5 其余阻塞项（与矩阵无关，但会挡住真机跑通）

| # | 问题 | 建议 |
|---|---|---|
| B1 | `busy` 的**完整打印文本**（含前缀，用于正则） | 请提供一条真机日志原文；否则先按 `\bbusy\b` 宽松匹配 |
| B2 | `busy` 处置策略 | 判 FAIL（不重试）；`preclean` 补幂等 `cam_run live stop` 防跨轮残留 |
| B3 | `cam_set live` 用法 | 推流前是否必发 `<res> ...`？`cam_set live bitrate N`（无 res）是否已非法？ |
| B4 | 新 6 档的**实际落盘 w×h / 方向** | 真机 ffprobe 逐档校准后回填；校准前置 0（不校验尺寸） |
