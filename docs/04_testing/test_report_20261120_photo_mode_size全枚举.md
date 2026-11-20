# 测试报告：`cam_set photo <mode> size <size>` mode × size 全枚举实测（2026-11-20）

**日期**：2026-11-20
**测试对象**：固件 `cam_set photo <mode> size <size>` 命令（6 mode × 7 size = 42 组合）
**方法**：逐条独立下发 `cam_set photo <mode> size <size>` → `cam_run photo`，每条后检测板子存活；主判据 = 固件回 `Capture completed successfully.`
**数据来源**：真机串口原始输出（COM23 @ 2000000）；历史日志 `logs/photo_only/20261119/182756`、`20261119/183849`、`20261120/092422`
**结论性质**：固件能力实测（**非脚本 bug**）；为 ADR-018「42 条全枚举」矩阵筛选提供依据

---

## 一、结论先行

| 类别 | 条数 | 含义 |
|---|---|---|
| ✅ 成功 | **15** | `cam_set` 接受 + `cam_run photo` 回 `Capture completed successfully.` |
| ⛔ SET 被拒 | **12** | `cam_set` 阶段即回 `size <S> does not support <mode> (supported: single)` |
| ❌ 打开相机失败 | **10** | `cam_set` 接受，`cam_run photo` 回 `cam open failed`（ATF 初始化 `ret=1541`） |
| ⚠️ 持续取流（非拍照） | **5** | `fcov`：`cam_run photo` 后无限取流、永不完成，并把板子锁进 `busy`（**只能断电恢复**） |
| 合计 | **42** | — |

**关键结论**：
1. **`heif` 全 7 档可拍成功**；`single` 除 `8m/w8m` 外全成功；`auto/mfnr/hdr` 仅 `12m` 成功。
2. **`3m/1080p/720p/480p` 是 `single` 专属**：其它 mode 一律被固件拒绝（`supported: single`）。
3. **`8m/w8m` 是坏档**（heif 除外）：`cam open failed`；**且会偶发升级为整板崩溃**（见 §四）。
4. **`fcov` 不是拍照动作**，是持续取流预览，会锁死板子 → **必须从拍照矩阵排除**。

---

## 二、完整 42 组合结果表

图例：✅ PASS　⛔ SET 被拒　❌ cam open failed　⚠️ 持续取流

| mode＼size | 12m | 8m | w8m | 3m | 1080p | 720p | 480p |
|---|---|---|---|---|---|---|---|
| **auto** | ✅ | ❌ | ❌ | ⛔ | ⛔ | ⛔ | ⛔ |
| **single** | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| **mfnr** | ✅ | ❌ | ❌ | ⛔ | ⛔ | ⛔ | ⛔ |
| **hdr** | ✅ | ❌ | ❌ | ⛔ | ⛔ | ⛔ | ⛔ |
| **fcov** | ⚠️ | ❌ | ❌ | ⚠️ | ⚠️* | ⚠️* | ⚠️* |
| **heif** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

\* `fcov` 的 `1080p/720p/480p`：SET 接受（未触 `does not support`）；`cam_run` 未逐条测，按同 mode 的 `12m/3m` 实测（均持续取流）推断同为持续取流。

---

## 三、可成功执行（15 条）

| # | 命令 | 固件回显（摘要） |
|---|---|---|
| 1 | `cam_set photo auto size 12m` | `photo: mode=auto size=12m` → `4032x3024 high_speed=1` → `Capture completed successfully.` |
| 2 | `cam_set photo single size 12m` | `size=12m fps=30` → `4032x3024` → 完成 |
| 3 | `cam_set photo single size 3m` | `size=3m fps=30` → `1920x1440` → 完成 |
| 4 | `cam_set photo single size 1080p` | `size=1080p fps=30` → `1920x1080` → 完成 |
| 5 | `cam_set photo single size 720p` | `size=720p fps=30` → `1280x720` → 完成 |
| 6 | `cam_set photo single size 480p` | `size=480p fps=30` → `640x480` → 完成 |
| 7 | `cam_set photo mfnr size 12m` | `size=12m` → `4032x3024` → 完成 |
| 8 | `cam_set photo hdr size 12m` | → 完成 |
| 9 | `cam_set photo heif size 12m` | heif 输出固定 `1920x1440` → 完成 |
| 10–15 | `cam_set photo heif size {8m,w8m,3m,1080p,720p,480p}` | heif 忽略 size，均完成 |

> heif 实测 `photo: mode=heif size=1920x1440`（固定输出），size 参数被接受但不改变输出尺寸。

### 3.1 "暂不支持"（实测可拍成功，但用户决定本轮暂不纳入）

> 依据用户 2026-11-20 决定：以下 3 条**固件实测能拍成功**，但 `photo_only` 场景**本轮暂不纳入**。**属策略取舍，不是固件不支持**，勿据此判固件缺陷。

| 命令 | 实测结果 | 处置 |
|---|---|---|
| `cam_set photo single size 3m` | ✅ PASS（`1920x1440`） | 暂不支持 |
| `cam_set photo heif size 8m` | ✅ PASS | 暂不支持 |
| `cam_set photo heif size 720p` | ✅ PASS | 暂不支持 |

→ 可用集合由 15 条 **收缩为 12 条**（`single` 去掉 3m；`heif` 去掉 8m、720p）。

---

## 四、不成功 / 特殊（27 条）

### A. `cam_set` 被固件拒绝（12 条）——尺寸 `3m/1080p/720p/480p` 只允许 `single`

| 组合 | 固件原话 |
|---|---|
| `auto` × `{3m,1080p,720p,480p}` | `I/CtrlCfg: size <S> does not support auto (supported: single)` |
| `mfnr` × `{3m,1080p,720p,480p}` | `I/CtrlCfg: size <S> does not support mfnr (supported: single)` |
| `hdr` × `{3m,1080p,720p,480p}` | `I/CtrlCfg: size <S> does not support hdr (supported: single)` |

### B. 打开相机失败（10 条）——`8m/w8m` 除 heif 外全部 `cam open failed`

`auto / single / mfnr / hdr / fcov` 各 × `{8m, w8m}`。固件日志（典型）：

```text
open photo: scenario=1 3328x2496 ... fps=24 ...
E/cam: [DfsSend][atf_wrapper_init:101]init atf failed, ret=1541
E/cam: [DfsSend][a5_core_init_task:425]id: 0, algo: 1, ret:1541, init failed
E/cam: [DfsSend][cam_open:953]open failed, camera_id[0]
I/NO_TAG: cam open failed
E/App Dfs: photo stop completed with error, ret=-22
```

> `3328x2496`(8m) / `3840x2160`(w8m) 走 PHOTO_2_1 路径，ATF 算法核初始化失败 `ret=1541`。

### C. 持续取流（5 条）——`fcov` 不是拍照

`fcov` × `{12m,3m,1080p,720p,480p}`：`cam_set` 接受 → `cam_run photo` 后**无限打印 AE 帧日志**（`[AE] fid=...` / `[awb0 proc][perf]`），**永不出现 `Capture completed successfully.`**，且板子进入 `busy`：

```text
cam_set photo ...            → [Ctrl] cannot reconfigure photo while idle
                               [CtrlCmd] set photo rejected: busy
cam_run status               → state: idle (backend: dfs)   # 谎报 idle，实则持续取流
cam_run photo stop / video stop / live stop / reboot         # 全部无效
```

**只能物理断电恢复**。`fcov-8m/w8m` 则在 `cam_run` 阶段 `cam open failed`（未进入取流）。

---

## 五、整板崩溃事件（严重，`8m/w8m` 的偶发升级）

`8m/w8m` 除了 `cam open failed`，**偶尔直接 panic 整板**，之后串口彻底静默、后续全部命令无效（假失败）：

| 时间 | 触发命令 | 异常 | 结果 |
|---|---|---|---|
| 2026-11-19 18:43:59（run `183849`） | `cam_set photo single size w8m` + `cam_run photo` | `[exception]mcause: 0x07[Store access fault]`（thread DfsSend） | 板子死机，此后 32 条全假失败 |
| 2026-11-20 09:26:59（run `092422`） | `cam_set photo mfnr size 8m` + `cam_run photo` | `[exception]mcause: 0x05[Load access fault]` | 板子死机，此后 26 条全假失败 |

> **非确定性**：同一组合（如 `mfnr-8m`）在本次逐条实测中只 `cam open failed`（未崩），历史两次才崩。故 `8m/w8m` 是「**大概率 open failed、小概率整板崩溃**」的危险档。

---

## 六、对 ADR-018「42 条全枚举」矩阵的影响（重要）

ADR-018 原计划 `photo_matrix.yaml` 遍历全部 42 组合。实测表明该矩阵**不可直接使用**：

- 12 条 SET_REJECTED：无害但纯浪费（命令被拒）；
- 10 条 OPEN_FAIL：多数无害，但 **`8m/w8m` 小概率崩板**，一旦崩，整轮后续全部假失败；
- 5 条 `fcov`：**必毒**（持续取流 + busy），崩板级后果。

**建议矩阵（待人工拍板，见 §七 TODO-CONFIRM）**：

| 方案 | 组合 | 说明 |
|---|---|---|
| **最小可用（推荐）** | **15 条**（§三全部） | 仅保留实测可拍成功的组合 |
| 扩展（保守，排除坏档/有毒） | 15 条 + 不含 8m/w8m/fcov | 即上表 ✅ 全保留 |
| 原 42 条 | ❌ 不建议 | 含崩板档，一次崩溃污染整轮 |

---

## 七、TODO-CONFIRM

| # | 事项 | 默认建议 |
|---|---|---|
| Q1 | `photo_matrix.yaml` 组合范围 | **收缩为 15 条成功集**（或至少排除 `fcov` 整列 + `8m/w8m`） |
| Q2 | `8m/w8m` 是否永远不用 | 建议**跳过**（heif 除外可保留）；若固件修复 ATF `ret=1541` 再评估 |
| Q3 | `fcov` 定位 | **排除出拍照矩阵**；如确需验证 fcov，单列独立场景、每轮后断电 |
| Q4 | 脚本是否识别 `does not support` / `rejected: busy` | 建议加固 `CAM_SET_ERROR`（观测性缺口，另案，见 known_issue） |

---

## 八、证据附录

| 日志 | 说明 |
|---|---|
| `logs/photo_only/20261119/20261119_182756` | 基线：6 条全 12m 组合，6/6 PASS |
| `logs/photo_only/20261119/20261119_183849` | 42 条运行；`single-w8m` 崩板（Store access fault） |
| `logs/photo_only/20261120/20261120_092422` | 42 条运行；`mfnr-8m` 崩板（Load access fault） |
| 2026-11-20 本次逐条实测 | 27 条安全组合单会话连续跑：15 PASS + 12 SET_REJECTED，与历史完全一致；`fcov` 单独验证为持续取流 |

**复现方法**：逐条 `cam_set photo <mode> size <size>` → `cam_run photo`，每条后 `echo` 探活 + `cam_run status` + 观察 2s 是否持续出 `[AE]` 流。崩板/取流即需断电。
