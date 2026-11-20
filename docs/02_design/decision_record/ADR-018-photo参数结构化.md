# ADR-018：photo 参数结构化（mode × size 全枚举，命令 `cam_set photo <mode> size <size>`）

## Background

固件 `cam_set photo` 语法（2026-11-19 用户提供固件串口原始日志，唯一权威）：

```text
cam_set photo <mode> [size <SIZE>] [num]
mode : auto | single | mfnr | hdr | fcov | heif
SIZE : 12m | 8m | w8m | 3m | 1080p | 720p | 480p
num  : hdr 连拍张数(0-3) / single 帧率(30/60) / 其它模式忽略
```

实测确认：`single` 之后的**裸 token 被当 `num`（帧率）**——`cam_set photo single 8m` 回落成 `size=12m fps=30`；
设尺寸**必须带 `size` 关键字**（`cam_set photo single size 8m` 才生效）。

当前脚本机制（ADR-011 搬移的产物）：

- `drivers/photo_commands.py`：`PHOTO_SET_COMMAND = "cam_set photo {mode}"` 模板 + `PHOTO_MODES` 字符串字典（零引用）。
- `modules/photo.py`：`console.exec_sync(PHOTO_SET_COMMAND.format(mode=mode), ...)`，`mode` 直接取配置 `photo_modes` 字符串。
- 即**配置字符串 = 「`cam_set photo` 之后的参数尾巴」**（`hdr 0`、`single 1080p` 均按此机制透传）。

因此脚本现发的 `single 12m` / `single 1080p` 均**非法**（第二 token 被当 fps）。

## Problem

1. **协议尾巴透传是漏抽象**：`mode` 字符串里混装了固件的 `mode` 与 `size` 两个正交字段，无法在脚本侧校验，语法演进只能靠字符串拼接。
2. **与 video 模块不对称**：video 已是「结构化参数 + 校验 + `params.command`」范式（`VideoParams` / `resolve_video_params()`）；photo 仍是裸字符串尾巴。
3. **需求是 mode × size 的全枚举**（6 mode × 7 size = 42 条），把它留作字符串不可维护、不可校验。
4. ADR-011 要求协议单一来源且可类型化；字符串尾巴无法表达「合法 size 枚举」。

## Decision

**photo 参数结构化为 (mode, size) 两个显式字段，模块经命令属性下发；对全部 mode × size 组合做全枚举。**

1. **命令形式（固定）**：

   ```text
   cam_set photo <mode> size <size>
   ```

   `size` 关键字**恒显式写出**（不依赖固件缺省）；**不建模、不发送 `num`**（用户 2026-11-19 明确「不用管 num」）。

2. **枚举范围（全排列，42 条）**：`mode` 6 值 × `size` 7 值，**每个组合一条命令**，**大小写/mode 全枚举**：

   | mode \ size | 12m | 8m | w8m | 3m | 1080p | 720p | 480p |
   |---|---|---|---|---|---|---|---|
   | auto / single / mfnr / hdr / fcov / heif | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

   - 顺序：**mode-major**（按上表 mode 列序），mode 内 size 按 `12m, 8m, w8m, 3m, 1080p, 720p, 480p` 序。
   - 42 = 6 × 7。**命令全集**见任务单 §3 明细表。
   - **取代**既有 `hdr 0~3`（num 形式）与裸 `single` / `single <SIZE>` 形式——hdr 现也走 `size`（`cam_set photo hdr size 12m`）。

3. **表示形式**：`photo_modes` 仍是**列表**（沿用「每 task 遍历配置列表」的既有编排），元素由字符串改为映射 `{mode, size}`：

   ```yaml
   photo_modes:
     - {mode: auto,   size: 12m}
     - {mode: auto,   size: 8m}
     # … 共 42 条
     - {mode: heif,   size: 480p}
   ```

4. **硬切，不保留旧字符串元素**：字符串元素一律拒绝（`PhotoParamsError`），不双读。依据：`video_params` 已确立「旧键全部非法、同批迁移」先例；双读引入两条真相路径，违背 ADR-011 单一来源。

5. **协议层（`drivers/photo_commands.py`）**：
   - 新增枚举：`PHOTO_MODE_NAMES = ("auto","single","mfnr","hdr","fcov","heif")`、`PHOTO_SIZES = ("12m","8m","w8m","3m","1080p","720p","480p")`。
   - 新增冻结 dataclass `PhotoParams(mode, size)`：
     - `command` 属性：`f"cam_set photo {self.mode} size {self.size}"`。
     - `key` 属性：报告名/本地目录用无空格短键 `f"{mode}-{size}"`（如 `auto-12m`、`single-1080p`）。
   - 新增 `resolve_photo_params(entry) -> PhotoParams`：`entry` 须为含 `mode`+`size` 的映射，二者必须在枚举内；非法抛 `PhotoParamsError`（拒绝执行，不猜测、不回退）。
   - **移除** `PHOTO_SET_COMMAND` 模板与 `PHOTO_MODES` 字符串字典。
   - `PHOTO_CAPTURE_COMMAND` / `PHOTO_CAPTURE_EXPECT` / 超时 / `_PIC_DIR` **不变**（判据链路零改动）。

6. **模块层（`modules/photo.py`）**：`run()` 把 `photo_modes` 元素逐个 `resolve_photo_params` → `params.command` 下发；报告名 `photo[{params.key}]`；本地下载子目录用 `params.key`（键无空格，`safe_mode` 的 `re.sub` sanitize 可保留）。默认回退值改为 `[{"mode": "auto", "size": "12m"}]`。

7. **默认值与全部引用点同批迁移**（见 Impact）。**关键**：`config/modules/photo.yaml` 默认 `photo_modes` 必须同步改为结构体，否则 `normal` / `aging` / `no_network` 等**未写 override 的场景**会因硬切命中字符串元素报错。

8. **全枚举的落点**：42 条作为**新场景 `config/scenarios/photo_matrix.yaml`** 的**单个 photo task** 的 `photo_modes` 列表（一次 task 遍历全 42 组合；photo 模块本身就是列表遍历模型）。既有场景（stress 等）的 photo_modes 同步改为结构体形式（**各自保留子集**，不统一指向 42 条）。

9. **本次不做**：`size→fps`（8m→24 / 12m→30）由固件决定，脚本**不校验、不映射、不断言尺寸**。

## Alternative

- **方案 A：字符串尾巴加 `size`**（`photo_modes: ["auto size 12m", ...]`，`photo.py` 零改动）。否决为**落点**——等于把「size 是显式维度」继续藏在字符串里，与 video 范式不对称，语法演进仍只能文本拼接。**保留为回退选项**。
- **扁平键**（`photo_mode`+`photo_size`，非列表）。否决——`photo_modes` 是多元素列表（一次 task 遍历多组合），扁平键无法表达。
- **保留 `num` 字段**（`{mode, size, num}`）。否决——用户明确本次不管 `num`；不建模不发送更简单，未来需要时再增量加回（可选能力增量语义）。
- **双读兼容**（同时接受字符串与结构体）。否决——两套真相路径 + 双分支测试负担。
- **维持现状**（继续发 `single 12m`）。否决——固件已证明其为非法形式（被当 fps），尺寸设置静默失效。

## Impact

**协议层**
- `ATS/drivers/photo_commands.py`：+ `PHOTO_MODE_NAMES` / `PHOTO_SIZES` / `PhotoParams` / `PhotoParamsError` / `resolve_photo_params()`；− `PHOTO_SET_COMMAND` / `PHOTO_MODES`。

**模块层**
- `ATS/modules/photo.py`：`run()` 解析改结构体；`_test_one()` 命令走 `params.command`；报告名/本地目录走 `params.key`；默认回退 `[{"mode": "auto", "size": "12m"}]`。

**配置层（schema 变更，全部同批迁移）**
- `ATS/config/modules/photo.yaml`：默认 `[{mode: auto, size: 12m}]` + 注释。
- **新增** `ATS/config/scenarios/photo_matrix.yaml`：42 条 `{mode, size}` 全枚举。
- 既有场景 photo_modes 改结构体：`stress.yaml`、`recovery_validation.yaml`、`stress_NoFtp_NoRtmp.yaml`、`stress_traverse_photo_mode.yaml`、`stress_traverse_photo_mode_3k.yaml`；顶部注释同步。
- `normal.yaml` / `aging.yaml` / `no_network.yaml`：无 photo override，随 `photo.yaml` 默认改动自动生效。

**测试**
- 新增 `tests/test_photo_params.py`（枚举校验 / 命令字面量与 `size` 关键字 / `key` 命名 / 缺键 / 非法 mode/size / 字符串元素报错）。现有 photo 单测不依赖 `photo_modes`，无需改。

**文档（由 Document Agent 后续同步，不在 Code Agent 范围）**
- `01_architecture/module_design.md`（photo Input）、必要时 `interface_spec.md`；
- ADR-011 photo 行追加「见 ADR-018」备注（历史正文不改）；`04_testing/test_case.md`、`05_handoff/`。

**行为不变**：判据/超时/时序/下载逻辑零改动。

## Open（已由 Document Agent 2026-11-19 收口；2026-11-20 补真机实测）

- **既有场景迁移口径（已定）**：各场景**保留子集**（不统一指向 42 条）；既有 `hdr 0~3`（num）4 条在新语义下完全等价 → **合并为 1 条 `{mode: hdr, size: 12m}`**；`stress_traverse_photo_mode.yaml` **归档删除**（被 `photo_matrix.yaml` 覆盖），`stress_traverse_photo_mode_3k.yaml` **保留**（3k 录像价值），其 photo 列表改为 42 条。
- **42 条落点（已定）**：新建 `photo_matrix.yaml`，**单 photo task 遍历 42 元素**（先例 `stress_traverse_photo_mode.yaml`；注意 `video_matrix.yaml` 是 168 个独立 task，非本形态）。
- **photo `cam_set` 无正向成功串、`_ERROR_RE` 不含 `not supported`/`Usage`**——非法 size 可能静默回落而当前判据不 FAIL（既有观测性缺口，另案，不在本次）。
- **工作区存在含 num 的未提交实现**——与本 ADR「无 num、size 必填」不符，实施时须对齐修订版（删除 num）。

### 🔴 真机实测（2026-11-20）：42 条**不可直接全枚举**，矩阵须收缩

逐条实测（报告见 [test_report_20261120](../../04_testing/test_report_20261120_photo_mode_size全枚举.md)）显示 §Decision-2 的「42 条全排列」**不能直接落进 `photo_matrix.yaml`**：

| 结果 | 条数 | 组合 |
|---|---|---|
| ✅ 可拍成功 | **15** | `single`×{12m,3m,1080p,720p,480p}、`auto/mfnr/hdr`×{12m}、`heif`×全 7 |
| ⛔ SET 被拒（`does not support <mode> (supported: single)`） | 12 | `auto/mfnr/hdr`×{3m,1080p,720p,480p} |
| ❌ `cam open failed`（ATF `ret=1541`） | 10 | `auto/single/mfnr/hdr/fcov`×{8m,w8m} |
| ⚠️ 持续取流 + 锁死板子（`fcov`） | 5 | `fcov`×{12m,3m,1080p,720p,480p} |

**影响本 ADR 的结论**：
1. **`8m/w8m` 危险**：heif 外全部 `cam open failed`，且**小概率整板 panic**（实测崩两次：`Store access fault`/`Load access fault`），崩后整轮后续全部假失败 → **矩阵应跳过 `8m/w8m`**（heif 可保留）。
2. **`fcov` 必须排除**：它是持续取流预览，非拍照动作，`cam_run photo` 后锁死板子、只能断电 → **从 `photo_matrix.yaml` 剔除整列**。
3. **`3m/1080p/720p/480p` 是 `single` 专属**：矩阵中这些尺寸只能配 `single`。

→ **`photo_matrix.yaml` 组合范围须由「42」收缩为「实测可拍成功的 15 条」**（或人工再定），见任务单 §TODO-CONFIRM 与 test_report §七。**是否需要据此修订本 ADR 的 Decision-2，待用户拍板。**

## Status

Accepted（接口定型：用户 2026-11-19 明确 mode × size 全枚举、忽略 num；2026-11-20 真机实测后**「42 条」组合范围待收缩**，接口形式不变，待 Code Agent 按收缩后矩阵实施）
