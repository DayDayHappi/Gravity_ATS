# Code Agent 任务单：`cam_set photo` mode × size 全枚举

> 由 Document Agent 出具，交 Code Agent 执行。
> **状态：已定型，可实施**。接口由 [ADR-018](../../02_design/decision_record/ADR-018-photo参数结构化.md) 定型（Status=Accepted）。
> 作用分支：`feat/windows_rebuild_app_arch`。
> 变更级别：**Level 2**（模块参数接口变更：`photo_modes` 字符串列表 → 结构体列表）。
> 相关约定：[ADR-011 串口协议集中化](../../02_design/decision_record/ADR-011-串口协议集中化.md)、[ADR-018 photo 参数结构化](../../02_design/decision_record/ADR-018-photo参数结构化.md)。
> 需求来源：用户 2026-11-19（附固件串口原始日志 + 明确「mode × size 全枚举、不用管 num」）。

> ⚠ **工作区漂移（Document Agent 复核发现，实施前必读）**：本分支工作区当前存在一版**未提交**实现
> （`ATS/drivers/photo_commands.py`、`ATS/modules/photo.py`、各场景配置、`tests/test_photo_params.py`），
> 其口径为**含 `num`、`size` 可选**（`PhotoParams(mode, size=None, num=None)`；配置 `{mode: hdr, num: 0}` / `{mode: auto}`；测试含 `test_hdr_with_num`）。
> **本任务单 / ADR-018 已修订为「无 num、size 必填、42 条全枚举」**。Code Agent 实施时须**删除 num 相关代码/配置/测试并补 size**（对齐修订版），勿保留 `num` 字段；或按本任务单整体重做。

## 1. 现象（固件串口原始日志，2026-11-19）

帮助行（固件给出，唯一权威）：

```text
cam_set photo <auto|single|mfnr|hdr|fcov|heif> [size <12m|8m|w8m|3m|1080p|720p|480p>] [num]
```

实测（截取）：

```text
cam_set photo single            → photo: mode=single size=12m fps=30      # 不带 size：固件默认 12m/30
cam_set photo single size 8m    → photo: mode=single size=8m fps=24       # ✓ 带 size 关键字
cam_set photo single 8m         → photo fps 8m not supported on 12m, use 30; using 30
                                  photo: mode=single size=12m fps=30       # ✗ 裸 token 被当 fps，回落 12m/30
cam_set photo single size w8m   → photo: mode=single size=w8m fps=24      # ✓
```

**关键结论**：`single` 之后紧跟的**裸 token 被固件当作 `num`（fps）**，不是 size。要设尺寸**必须**带 `size` 关键字。
现状脚本发出的 `cam_set photo single 12m` / `single 1080p` 属**非法形式**（第二 token 被误读为 fps），必须加 `size`。

## 2. 需求（用户 2026-11-19 明确）

**对全部 `mode` × `size` 组合做全枚举**，命令形式固定为：

```text
cam_set photo <mode> size <size>
```

- `mode`：`auto | single | mfnr | hdr | fcov | heif`（6）
- `size`：`12m | 8m | w8m | 3m | 1080p | 720p | 480p`（7）
- `size` 关键字**恒显式写出**；**不建模、不发送 `num`**。
- **共 6 × 7 = 42 条命令**。
- 取代既有 `hdr 0~3`（num 形式）与裸 `single` / `single <SIZE>` 形式——hdr 也走 size（`cam_set photo hdr size 12m`）。

## 3. 命令全集（42 条，mode-major）

顺序：外层按 mode 列序，内层按 size 列序。**这是场景 `photo_matrix.yaml` 的权威清单**。

| # | 命令 | # | 命令 |
|---|---|---|---|
| 1 | `cam_set photo auto size 12m` | 22 | `cam_set photo hdr size 12m` |
| 2 | `cam_set photo auto size 8m` | 23 | `cam_set photo hdr size 8m` |
| 3 | `cam_set photo auto size w8m` | 24 | `cam_set photo hdr size w8m` |
| 4 | `cam_set photo auto size 3m` | 25 | `cam_set photo hdr size 3m` |
| 5 | `cam_set photo auto size 1080p` | 26 | `cam_set photo hdr size 1080p` |
| 6 | `cam_set photo auto size 720p` | 27 | `cam_set photo hdr size 720p` |
| 7 | `cam_set photo auto size 480p` | 28 | `cam_set photo hdr size 480p` |
| 8 | `cam_set photo single size 12m` | 29 | `cam_set photo fcov size 12m` |
| 9 | `cam_set photo single size 8m` | 30 | `cam_set photo fcov size 8m` |
| 10 | `cam_set photo single size w8m` | 31 | `cam_set photo fcov size w8m` |
| 11 | `cam_set photo single size 3m` | 32 | `cam_set photo fcov size 3m` |
| 12 | `cam_set photo single size 1080p` | 33 | `cam_set photo fcov size 1080p` |
| 13 | `cam_set photo single size 720p` | 34 | `cam_set photo fcov size 720p` |
| 14 | `cam_set photo single size 480p` | 35 | `cam_set photo fcov size 480p` |
| 15 | `cam_set photo mfnr size 12m` | 36 | `cam_set photo heif size 12m` |
| 16 | `cam_set photo mfnr size 8m` | 37 | `cam_set photo heif size 8m` |
| 17 | `cam_set photo mfnr size w8m` | 38 | `cam_set photo heif size w8m` |
| 18 | `cam_set photo mfnr size 3m` | 39 | `cam_set photo heif size 3m` |
| 19 | `cam_set photo mfnr size 1080p` | 40 | `cam_set photo heif size 1080p` |
| 20 | `cam_set photo mfnr size 720p` | 41 | `cam_set photo heif size 720p` |
| 21 | `cam_set photo mfnr size 480p` | 42 | `cam_set photo heif size 480p` |

## 4. 实现方案（ADR-018）

### 4.1 协议层 `ATS/drivers/photo_commands.py`

- 新增：`PHOTO_MODE_NAMES`（6 mode）、`PHOTO_SIZES`（7 size）枚举。
- 新增冻结 dataclass `PhotoParams(mode, size)`：
  - `command` → `f"cam_set photo {mode} size {size}"`
  - `key` → `f"{mode}-{size}"`（无空格，供报告名/本地目录：`auto-12m`、`single-1080p`）
- 新增 `resolve_photo_params(entry) -> PhotoParams`：`entry` 须为含 `mode`+`size` 的映射，二者必须在枚举内；非法抛 `PhotoParamsError`。
- **移除** `PHOTO_SET_COMMAND` 模板与 `PHOTO_MODES` 字典。
- `PHOTO_CAPTURE_COMMAND` / `PHOTO_CAPTURE_EXPECT` / `PHOTO_SET_TIMEOUT` / `PHOTO_CAPTURE_TIMEOUT` / `_PIC_DIR` **不变**。

### 4.2 模块层 `ATS/modules/photo.py`

- `run()`：`photo_modes` 元素逐个 `resolve_photo_params`；默认回退 `[{"mode": "auto", "size": "12m"}]`。
- `_test_one()`：命令改走 `params.command`；报告名 `photo[{params.key}]`；本地下载子目录用 `params.key`。
- 判据（`Capture completed successfully.`）+ 路径扫描 + 下载/校验逻辑**零改动**。

### 4.3 配置层

- `ATS/config/modules/photo.yaml`：默认 `photo_modes` 改 `[{"mode": "auto", "size": "12m"}]` + 注释（去 num）。
- **新增** `ATS/config/scenarios/photo_matrix.yaml`：42 条 `{mode, size}` 全枚举（§3 清单）。
  - **落点形态 = 单个 photo task 遍历 42 元素列表**（photo 模块本就是「一个 task 遍历 `photo_modes` 列表」模型，先例为 `stress_traverse_photo_mode.yaml`）。
  - **注意**：`video_matrix.yaml` **不是**同形先例——它是 **168 个独立 video task**（每组合一条，由 `scripts/gen_video_matrix.py` 生成），因 `video` 模块一次只跑一组 `video_params`。本任务单 §4.3 早期版本误引其为「单 task 遍历」先例，已修正。photo 侧**不**逐条拆 task（否则 42 个 photo task 重复下载/连接开销极大）。
  - 骨架参考 `stress_traverse_photo_mode.yaml`（prepare/preview/loop/cleanup 与 stress 一致，photo task `repeat: 1` 遍历列表）。
- 既有场景 photo_modes 改结构体（子集，见 §4.4）；顶部 TODO-CONFIRM 注释同步改为「已由 2026-11-19 固件日志核实」。
- `normal.yaml` / `aging.yaml` / `no_network.yaml` 无 photo override，**无需改**（随 photo.yaml 默认生效）。

### 4.4 既有场景迁移口径（已拍板，见 §5-Q5/Q6/Q7）

| 场景 | 现状 | 改法 |
|---|---|---|
| `stress.yaml` | 12 photo task | 各 task `photo_modes` 改结构体（**逐 task 单元素**，保留「每模式独立 repeat」骨架）：`{mode: auto, size: 12m}`、`{mode: single, size: 12m}`、`{mode: single, size: 1080p/720p/480p}`、`{mode: mfnr, size: 12m}`、`{mode: heif, size: 12m}`；**hdr 4 条（`hdr 0~3`）合并为 1 条 `{mode: hdr, size: 12m}`**（num 已无表达，4 条会完全相同 → 去重，12 task → 9 task） |
| `recovery_validation.yaml` | 11 task | 同 stress（hdr 4→1，11→8 task） |
| `stress_NoFtp_NoRtmp.yaml` | 11 task | 同上（11→8 task） |
| `stress_traverse_photo_mode.yaml` | 1 列表 7 元素 | **归档删除**（语义已被 `photo_matrix.yaml` 完全覆盖，见 §5-Q7） |
| `stress_traverse_photo_mode_3k.yaml` | 1 列表 7 元素 | 保留场景**其余部分**（3k 录像压测），仅把 photo task 的列表替换为「指向 photo_matrix 的同一 42 条」或删除该 photo task 交给 `photo_matrix`；**默认：photo_modes 改为与 photo_matrix 相同的 42 条列表**（该场景核心是 3k 录像，photo 仅顺带） |

> **注（hdr 语义变更）**：原 `hdr 0~3` 的 num 是**连拍张数**，新命令形式不含 num → hdr 无法表达连拍张数。
> 故既有场景的 4 条 hdr task 在新语义下**完全等价**（均退化为 `cam_set photo hdr size <X>`），
> **合并为 1 条、size 取 `12m`（默认档）**。若未来需按 num 遍历 hdr 连拍张数，用户需再给 num 形式（本次不做）。

> **注（single 重复项）**：`stress.yaml` 同时有 `single`(L51) 与 `single 12m`(L67)；`size` 必填后两者**规整为同一条** `{mode: single, size: 12m}`。
> Q6 结论「各自保留子集」未含去重 → **默认保留两条（冗余，各带独立 repeat 便于分别调次数）**；若人工认为应去重，stress 由 9→8 task（见 §6-Q10）。

## 5. TODO-CONFIRM 已拍板（Document Agent，2026-11-19）

| # | 事项 | 结论 |
|---|---|---|
| **Q1** | 接口方案 | ✅ **结构化为 `{mode, size}`**（ADR-018） |
| **Q2** | 是否枚举 `num`（hdr 张数 / single fps）？ | **否**，本次不管 num、不发送 |
| **Q3** | 枚举范围 | ✅ 全部 mode × size = **42 条**，命令 `cam_set photo <mode> size <size>` |
| **Q4** | size→fps（8m→24 / 12m→30）是否由脚本校验？ | 否（固件决定，不校验不映射不选尺寸断言） |
| **Q5** | 42 条落点 | ✅ **新建 `photo_matrix.yaml`，单 photo task 遍历 42 元素**（先例为 `stress_traverse_photo_mode.yaml`；`video_matrix.yaml` 是 168 个独立 task，非本形态） |
| **Q6** | 既有场景迁移 | ✅ **各自保留子集**（不统一指向 42 条）；**hdr 4 条合并为 1 条 `{mode: hdr, size: 12m}`**（num 无表达 → 4 条等价去重）；`single` / `single 12m` 均规整为 `{mode: single, size: 12m}` |
| **Q7** | `stress_traverse_photo_mode*.yaml` 去留 | ✅ `stress_traverse_photo_mode.yaml` **归档删除**（被 `photo_matrix` 完全覆盖）；`stress_traverse_photo_mode_3k.yaml` **保留**（3k 录像压测价值），其 photo task 列表改为与 photo_matrix 相同的 42 条 |
| **Q8** | 报告名/目录键格式 `{mode}-{size}` | ✅ 接受（`auto-12m`、`single-1080p`，无空格） |

## 6. TODO-CONFIRM（剩余，实施前请人工确认）

| # | 事项 | 建议默认 |
|---|---|---|
| **Q9** | 若某 mode 真机不接受某 size（如 `auto size 480p` 报 Usage/not supported） | 先回报原始日志，再决定剔除该组合；**不静默跳过**（§10-4） |
| **Q10** | `stress.yaml` 的 `single` 与 `single 12m` 规整后等价，是否去重？ | 保留两条（各带独立 repeat，便于分别调次数）；去重则该场景 9→8 task |

## 7. 精确改动锚点

| 文件 | 改动 |
|---|---|
| `ATS/drivers/photo_commands.py` | + `PHOTO_MODE_NAMES` / `PHOTO_SIZES` / `PhotoParams(mode, size)` / `PhotoParamsError` / `resolve_photo_params()`；− `PHOTO_SET_COMMAND` / `PHOTO_MODES`；**移除工作区现存的 `num` 字段** |
| `ATS/modules/photo.py` | `run()` 解析结构体（`{mode, size}`）；`_test_one()` 走 `params.command`；报告名/目录走 `params.key`；默认回退 `[{"mode": "auto", "size": "12m"}]` |
| `ATS/config/modules/photo.yaml` | 默认 `photo_modes: [{"mode": "auto", "size": "12m"}]` + 注释（去 num 示例） |
| `ATS/config/scenarios/photo_matrix.yaml` | **新增**：单 photo task，`photo_modes` 为 42 条全枚举（§3） |
| `ATS/config/scenarios/stress.yaml` | photo task 12→9（hdr 4 合 1）；各 `photo_modes` 结构体（含 size）；L17-23 顶部注释同步 |
| `ATS/config/scenarios/recovery_validation.yaml` | photo task 11→8（hdr 4 合 1）；同上 |
| `ATS/config/scenarios/stress_NoFtp_NoRtmp.yaml` | photo task 11→8（hdr 4 合 1）；同上 |
| `ATS/config/scenarios/stress_traverse_photo_mode.yaml` | **删除文件**（内容归档到 `docs/03_development/archive/`） |
| `ATS/config/scenarios/stress_traverse_photo_mode_3k.yaml` | 保留场景；photo task 列表改为与 photo_matrix 相同的 42 条结构体 |
| `tests/test_photo_params.py` | 改写/新增：枚举校验 / `command` 含 `size` 关键字 / `key` 无空格 / 缺 size / 非法 mode/size / 字符串元素报错；**移除 `test_hdr_with_num` 等 num 用例** |

> 工作区现存实现（含 num）**必须对齐修订版**：删 `num` 相关代码/配置/测试，`size` 改必填。

## 8. 验收标准

### 离线

1. `grep -rn "PHOTO_SET_COMMAND\|PHOTO_MODES" ATS/` → 0 命中（旧字符串机制已移除）；
2. `grep -rn "photo_modes" ATS/config/` → 全部结构体形式（`{mode: ...}`），**无**字符串元素残留；
3. `ATS/config/scenarios/photo_matrix.yaml` 的 photo_modes 元素数 = **42**；
4. 全部受影响场景 + `normal` + `no_network` `python3 -m ATS.main --scenario <name> --dry-run` 均 exit 0；
5. `python3 -m unittest discover -s tests` 全过，且 `test_photo_params.py` 覆盖上述用例。

### 真机（必须回填）

1. `serial.log` 中 TX 行确认为 `cam_set photo <mode> size <size>`（**含 `size` 关键字**），**不出现** `` `photo fps ... not supported` `` 告警；
2. 命令回显 `photo: mode=<mode> size=<size> fps=<fps>`，mode/size 与配置逐字一致；
3. photo PASS，产物下载校验正常；报告名 `photo[auto-12m]` 等（无空格）可读。

## 9. 明确不做

- ❌ 不建模、不发送 `num`（hdr 张数 / single fps）。
- ❌ 不改 `PHOTO_CAPTURE_COMMAND` / `PHOTO_CAPTURE_EXPECT` / 超时（判据链路零改动）。
- ❌ 不实现 size→fps 映射或尺寸断言。
- ❌ 不做旧字符串配置的双读兼容（硬切，见 ADR-018 Decision-4）。
- ❌ 不在 `modules/photo.py` 里内联 `cam_set photo ...` 协议串（ADR-011）。
- ❌ 不修改 `docs/01_architecture/`、`02_design/`、`04_testing/`、`05_handoff/`（Document Agent 负责同步）。
- ❌ 不修改 `docs/03_development/archive/` 下的历史文档（本任务单本身除外）。

## 10. 交付要求（Code Agent 的文档义务）

1. 新建 `docs/03_development/devlog/<YYYYMMDD>_<HHMM>_photo参数结构化.md`，含 Change / Files / Reason / Verification（离线 + 真机原始日志片段）/ Known limitation；
2. 在 `docs/03_development/devlog/README.md` 索引追加一行；
3. 在 devlog 中列出**最终生效的命令形式**、**`PhotoParams`/`resolve_photo_params` 最终签名**、**新增/改动场景清单**、**42 条是否全绿**；
4. 真机若发现某 mode 不接受 size（如某 mode 报 Usage/not supported），**先回报再决定**，不要自行凑判据。

## 11. 完成后 Document Agent 的同步范围（不在本任务内）

- `01_architecture/module_design.md`（photo Input/命令形式）、`interface_spec.md`（若涉及 photo_modes）、必要时 `data_flow.md`；
- `02_design/decision_record/ADR-011`（photo 行追加「见 ADR-018」备注；正文历史不改）；
- `04_testing/test_case.md`（photo 相关输入列）；`05_handoff/current_status.md` / `next_step.md` / `known_issue.md`；
- 更新 ADR-018 与本任务单状态为「已实施」。
