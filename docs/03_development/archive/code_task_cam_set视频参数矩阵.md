# Code Agent 任务单：`cam_set video` 全参数显式排列组合

> 由 Document Agent 出具。**状态：已就绪，可交 Code Agent 实施**（三项确认已于 2026-11-10 拍板，见 §6）。
> 需求来源：用户 2026-11-10「每一条参数都显式写出来，都作为一种，所有排列组合」。
> 作用分支：`feat/windows_rebuild_app_arch`。
> 变更级别：**Level 2**（模块参数接口变更：`video_resolution` 组合 ID → 显式参数集）。
> 前置依赖：[cam_run 命令族迁移](code_task_cam_run命令族迁移.md)（已完成，devlog `20261110_1558`）。
> **规模：192 条 task**（方案 A：bitrate/gop 各单值，vui 全 3 值）。

## 1. 目标

把录像分辨率配置从「13 个预置组合 ID」改为**固件新语法的全参数枚举**，每一条命令的所有参数
显式写全，每个取值组合单独一条 task，全排列遍历。

## 2. 命令形态（固定，不得省略任何字段）

```text
cam_set video <res> <fps> eis <N> <codec> bitrate <N> gop <N> vui <N>
```

示例：

```text
cam_set video 4k 30 eis 0 h264 bitrate 8000000 gop 30 vui 709     (63 字节)
cam_set video 3k 60 eis 2 h265 bitrate 25000000 gop 1000 vui 6011 (65 字节)
```

- **不依赖固件缺省值**：即使某参数等于固件默认，也必须写出。
- 参数顺序固定为上表顺序（固件允许自由顺序，脚本固定一种便于比对日志）。
- 长度 63–65 字节，走既有 `_write_safe` 32B 分片（ADR-002），无需改串口层。

## 3. 取值域

| 参数 | 固件语义 | 脚本取值集合 | 说明 |
|---|---|---|---|
| `res` | 分辨率 | `4k, 3k, 1080p, sd1080p, 720p, 480p` | 6 个，完整枚举 |
| `fps` | 帧率 | `30, 60` | ✅ 用户确认 **4k/3k 也支持 60fps**（全 6 档 × 2 值） |
| `eis` | 0=关 1=在线 2=离线 | `0, 1, 2`；**3k 仅 `2`** | 3k 强制离线，共 5×3+1 = 16 种 |
| `codec` | 编码 | `h264, h265` | — |
| `bitrate` | 50000–25000000 | **`8000000`（方案 A，单值）** | ✅ 用户已定为单值 |
| `gop` | 0–1000 | **`30`（方案 A，单值）** | ✅ 用户已定为单值 |
| `vui` | 709 / 6010 / 6011 | `709, 6010, 6011` | 3 个，完整枚举 |

### 3.1 组合数公式（方案 A 已定：192 条）

```text
N = fps数 × codec数 × bitrate数 × gop数 × vui数 × Σ_res(eis数)
  = 2 × 2 × 1 × 1 × 3 × (5×3 + 1×1)
  = 192
```

按分辨率拆分：

| res | eis 取值数 | 该档组合数 | 明细 |
|---|---|---|---|
| `4k` | 3 | 36 | 2 fps × 3 eis × 2 codec × 1 × 1 × 3 vui |
| `3k` | 1 | 12 | 2 fps × 1 eis × 2 codec × 3 vui |
| `1080p` | 3 | 36 | 同行 4k |
| `sd1080p` | 3 | 36 | 同行 4k |
| `720p` | 3 | 36 | 同行 4k |
| `480p` | 3 | 36 | 同行 4k |
| **合计** | 16 | **192** | 纯录像 ≈ 1.2 h（22.4s/条） |

> 若后续需要扩展 bitrate/gop 边界值，按 `N = 192 × bitrate值数 × gop值数` 重算（各取 3 值 → 1728 条 ≈ 10.8 h）。

## 4. 实现方案

### 4.1 协议层 `ATS/drivers/video_commands.py`

**移除** `VIDEO_PROFILES`（13 个旧组合，命令已非法）与 `resolve_video_profile()`。

**新增**（仍符合 ADR-011：协议只存常量/纯函数，不读 YAML、不发串口）：

```python
VIDEO_RESOLUTIONS = ("4k", "3k", "1080p", "sd1080p", "720p", "480p")
VIDEO_FPS = (30, 60)
VIDEO_CODECS = ("h264", "h265")
VIDEO_EIS_MODES = (0, 1, 2)
VIDEO_EIS_FORCED_OFFLINE = {"3k": 2}      # 3k 只允许 eis 2
VIDEO_VUI = ("709", "6010", "6011")
VIDEO_BITRATE_RANGE = (50000, 25000000)
VIDEO_GOP_RANGE = (0, 1000)

VIDEO_SET_COMMAND = (
    "cam_set video {res} {fps} eis {eis} {codec} bitrate {bitrate} gop {gop} vui {vui}"
)

@dataclass(frozen=True)
class VideoParams:
    res: str
    fps: int
    eis: int
    codec: str
    bitrate: int
    gop: int
    vui: str

    @property
    def key(self) -> str:
        """报告/文件名用短键，如 4k-30-e0-h265-b8m-g30-v709。"""

    @property
    def command(self) -> str:
        """按固定顺序拼完整命令。"""
```

**校验函数** `resolve_video_params(params: dict) -> VideoParams`：
非法 res/fps/eis/codec/vui 枚举值、bitrate/gop 越界、3k 配 eis 0/1 → `VideoParamsError`（拒绝执行，不静默猜测）。

**保留** `VIDEO_START_COMMAND` / `VIDEO_STOP_COMMAND` / `VIDEO_START_EXPECT` / `VIDEO_STOP_EXPECT` /
`VIDEO_CLEANUP_EXPECT`（本次不改）；`VIDEO_SET_ERROR` 需**追加 `busy`**（见 §4.4）。

### 4.2 模块层 `ATS/modules/video.py`

- 参数接口由 `video_resolution: "sd1080p_0"` 改为 `video_params: {res, fps, eis, codec, bitrate, gop, vui}`。
- 用 `resolve_video_params()` 校验 → `params.command` 下发。
- **不再做尺寸断言**：新语法未提供落盘 w×h 映射，`width/height/orientation` 一律置 `0/0/"待校准"`，
  结果 detail 只展示 `设置命令` 与 `录像时长`（避免用旧映射误导）。
- 报告名 `video[<key>]` 使用短键（如 `video[4k-30-e0-h264-b8m-g30-v709]`）。
- 视频文件扫描正则 `\.h265` → `\.(h265|h264)`（codec 可配）。
- 模块内**仍不写循环**（红线 2）：192 条由 scenario tasks 驱动。

### 4.3 配置层

- `ATS/config/modules/video.yaml`：`video_resolution` 改为 `video_params` 默认值（建议 `4k/30/0/h265/8000000/30/709`）。
- **新增 `ATS/config/scenarios/video_matrix.yaml`**：192 条 task（见 §4.5）。
- 既有场景（`stress`、`video_size_traverse`、`recovery_validation`、`stress_NoFtp_NoRtmp`、`3k_2`、
  `stress_traverse_photo_mode_3k`）中的 `video_resolution: "<旧键>"` **全部非法**，需按 §6 处置。

> ⚠️ `TestModule._merge()` 是**浅合并**（`{**config, **params}`），task override 里的 `video_params`
> 会整体替换模块默认 dict。因此每条 task **必须写全 7 个键**，缺键在 `resolve_video_params()` 阶段报错，
> 不得依赖模块默认补齐（与「所有参数显式写出」原则一致）。

### 4.4 `busy` 前置（先做判定，日志文本后补）

固件在录制/推流中拒绝配置并返回 `busy`。现有 `cam_set` 是纯负向判定（`_ERROR_RE` 不含 `busy`），
会把 `busy` 当成功 → 后续按**上一条命令的参数**录制 → 矩阵结果全部失真。

**用户 2026-11-10 确认：`busy` 暂未在日志中观察到，后续提供原文。** 因此：

必须（本任务内完成）：

1. `VIDEO_SET_ERROR` 增加 `\bbusy\b`（宽松匹配；**真机原文到手后按实际字符串收紧**，只改这一处常量）；
2. 判定为 FAIL，错误信息带原始输出（**不重试**，避免掩盖状态机问题）；
3. `preclean`（`core/scenario_manager.py` L397-411）在 `cam_run video stop` 之后补一条幂等的
   `cam_run live stop`（RTMP 停止命令与 expect 已在 `rtmp_commands.py`，直接引用）。

`TODO-CONFIRM: busy 的完整打印文本待用户提供真机日志后收紧正则（不阻塞本任务实施）。`

### 4.5 场景文件生成方式

192 条 task 手写不可维护。**必须**新增生成脚本 `scripts/gen_video_matrix.py`，
按 §3 取值域笛卡尔积生成 `ATS/config/scenarios/video_matrix.yaml` 并写文件头注释
（生成时间 / 取值域 / 组合数 / 重新生成命令）。

**生成顺序（固定，便于日志对照与失败二分）**：
`res` 按 §3 表顺序 → `fps` 升序 → `eis` 升序 → `codec` 按 `h264, h265` → `vui` 按 `709, 6010, 6011`。

场景骨架：

```yaml
# 由 scripts/gen_video_matrix.py 生成，请勿手改
# 生成时间: <ts> | 取值域: res×fps×eis×codec×vui = 6×2×16×2×3 / eis合并 = 192 条
scenario:
  name: video_matrix
  preview: {enabled: false}
  prepare: [serial_init, wifi_connect, preclean, ftp_ready]
  loop: {enable: false}          # 单轮跑完矩阵即止；轮次由人工改
  tasks:
    # ── 4k / fps 30 / eis 0 ──
    - module: video
      duration: 10
      override:
        ftp_download: false
        video_params: {res: "4k", fps: 30, eis: 0, codec: "h264", bitrate: 8000000, gop: 30, vui: "709"}
    - module: video
      duration: 10
      override:
        ftp_download: false
        video_params: {res: "4k", fps: 30, eis: 0, codec: "h264", bitrate: 8000000, gop: 30, vui: "6010"}
    # ...（共 192 条）
    # ── 末尾：对 h265 产物统一做完整性检测 ──
    - module: video_integrity
      override:
        input: {source: "current_run", selection: "all_unchecked"}
```

- 每条 `duration: 10`、`ftp_download: false`（先只验证命令被接受 + 录制成功）。
  下载校验另抽每分辨率 1 条（6 条）单独 task 组，避免 192 条各付一次 FTP 连接。
- h264 组合不接 `video_integrity`（该模块只解析 H265）。

## 5. 验收标准

### 离线

1. `python -m unittest discover -s tests` 全过（基线 90），并新增 `tests/test_video_params.py`：
   - 全排列生成数量 = **192**（bitrate/gop 各 1 值、vui 3 值）；
   - 3k 只生成 `eis 2`（其他 5 档各 3 种 eis）；
   - 非法值（bitrate 49999 / gop 1001 / `eis 0` + `3k` / `res hd1080p` / 缺键）抛 `VideoParamsError`；
   - 生成的命令字段顺序与字节数符合 §2；
2. `grep -rn "video_resolution" ATS/` → 0 命中（旧接口已彻底移除）；
3. `ATS/config/scenarios/video_matrix.yaml` 的 task 数 = 192（不含末尾 `video_integrity`）；
4. `--dry-run --scenario video_matrix` 契约校验通过。

### 真机

1. 矩阵前 20 条 PASS、无 `command not found`（65 字节命令分片正确）；
2. `serial.log` 中每条 `cam_set video` 参数与 task 配置逐字一致（抽检 10 条，含 `4k 60` 与 `3k` 各 1 条）；
3. `busy` 判定：真机若出现 `busy`，必须判 FAIL 且 detail 带原文；未出现则记录「本次未观察到」（并保留宽松正则）；
4. 记录每条实际耗时，校准整轮预算（预计 192 × 22.4s ≈ 1.2h）。

## 6. 已确认事项（用户 2026-11-10，无需再问）

| # | 事项 | 结论 |
|---|---|---|
| **Q1** | bitrate 取值集合（区间 50000–25000000） | ✅ **方案 A**：单值 `8000000` |
| **Q2** | gop 取值集合（区间 0–1000） | ✅ **方案 A**：单值 `30` |
| **Q3** | vui 是否全取 3 值 | ✅ 是（`709/6010/6011`） |
| **Q4** | 4k / 3k 是否支持 60 fps | ✅ **支持**（6 档 × 30/60 全遍历） |
| **Q5** | 既有场景旧组合 ID 处置 | 按 §6.1 执行（本任务内一并改） |
| **Q6** | 旧尺寸变体（2016×1034 / 1600×900 / 800×600 / 1296×2304 竖屏 / `hd1080p`） | 按**已随固件移除**处理：不纳入矩阵，旧 task 删除 |
| **Q7** | `busy` 日志原文 | ⏳ **暂未观察到，后续提供**。先按 `\bbusy\b` 宽松匹配，原文到手后只改 `VIDEO_SET_ERROR` 一处 |

### 6.1 既有场景处置（Q5 已确认执行）

| 场景 | 现状 | 处置 |
|---|---|---|
| `stress.yaml` | 13 个 video task，各旧组合 ID | 改为 6 个 res × h265 × 30fps × eis 2 的代表组合；保留 12 个 photo task 与 rtmp |
| `video_size_traverse.yaml` | 11 个 task 遍历旧组合 | **由 `video_matrix.yaml` 取代**：从 `ATS/config/scenarios/` 删除，文件内容原件复制到 `docs/03_development/archive/` 留档（避免以后有人误以为它在跑） |
| `3k_2.yaml` | `video_resolution: "3k_2"` | 改 `video_params: {res: "3k", fps: 30, eis: 2, codec: "h265", bitrate: 8000000, gop: 30, vui: "709"}` |
| `stress_traverse_photo_mode_3k.yaml` | 同上 | 同 `3k_2.yaml` |
| `recovery_validation.yaml` | 12 个 video task 用旧 ID | 保留 1–2 个代表组合（恢复验证不关心分辨率矩阵） |
| `stress_NoFtp_NoRtmp.yaml` | 12 个 video task 用旧 ID | 同 `stress.yaml` |

## 7. 明确不做

- ❌ 不改 `VIDEO_START/STOP_COMMAND` 与判据串（本轮已完成迁移，业务完成串不变）。
- ❌ 不做 `cam_set photo` / `cam_set live` 的参数矩阵（用户本轮只要求 video；photo/live 待后续）。
- ❌ 不为新语法猜测 w×h 映射（未校准前一律 0，不用旧表反推）。
- ❌ 不在 `modules/video.py` 内写组合循环（红线 2）。

## 8. 交付要求

1. 新建 devlog `<YYYYMMDD>_<HHMM>_video参数矩阵.md`，含：取值域、组合数、生成命令、离线/真机证据、`busy` 处置结果；
2. 更新 `docs/03_development/devlog/README.md` 索引；
3. 在 devlog 中列出**最终取值域**与**新增/删除的场景文件**（Document Agent 据此同步架构与测试文档）；
4. 若真机发现某取值非法（如 4k 不支持 60fps），**记录并从矩阵剔除**，不要静默跳过。
