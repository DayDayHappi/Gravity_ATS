# 测试报告：`cam_set video` 关键字式语法 60 组合真机实测（2026-11-23）

> 需求来源：用户文件 `app重构后录像待测试命令.md`（60 条组合，每条录 5s）。
> 执行者：Code Agent（真机，devlog `20261123_1315`）。本报告由 Document Agent 依据原始数据落档。
> 原始数据（未入 git，临时目录）：`%TEMP%/video_rec_kw60.jsonl`、`%TEMP%/probe_video_kw.py`；
> 副本：[`_wip_video_probe/video_rec_kw60.jsonl`](_wip_video_probe/video_rec_kw60.jsonl)、[`_wip_video_probe/probe_video_kw.py`](_wip_video_probe/probe_video_kw.py)。

## 一、结论速览

| 项 | 结论 |
|---|---|
| **Q1 语法** | 固件**只接受关键字式**：`cam_set video <res> fps <N> eis <N> format <h264\|h265> bitrate <N> gop <N> vui <N>`；工程位置式模板（`{res} {fps} eis {eis} {codec}`）**被拒**（`bare number 30 not allowed`）→ **Level 2 协议变更**，需改 `drivers/video_commands.py` |
| **Q2 1080p+fps60** | **不支持**，原文 `fps 60 not supported on 1080p, use 30 or pick sd1080p\|720p\|480p for 60`；`VIDEO_FPS_FORCED` 应**补 1080p** |
| **Q3 选项对上限** | **6 个选项对可用**，不触发 `Too many args`；旧 `_wip_video_probe/README.md`「最多 3 对」规则**已过时**（本固件已放宽） |
| **Q4 bitrate** | 18Mbps 生效（5s 落盘 ≈23MB）；480p/720p 是否分档属产品决策，**未判定** |
| **新固件 bug** | `sd1080p fps 60 eis 2 format h265` 录像后 `cam_run video stop` **状态机挂死**（确定性复现，仅断电可解）→ 见 [`known_issue.md`](../05_handoff/known_issue.md) |

## 二、语法探针（Step 0，固件回显原文）

| 探针 | 命令 | 固件回显 | 判定 |
|---|---|---|---|
| A 位置式（工程 `video_commands.py` L30） | `cam_set video 3k 30 eis 2 h265 bitrate 18000000 gop 30 vui 709` | `I/CtrlCfg: bare number 30 not allowed, use "fps 30" or a keyword` | ❌ |
| B 关键字式（用户文件） | `cam_set video 3k fps 30 eis 2 format h265 bitrate 18000000 gop 30 vui 709` | `video: size=3k fps=30 eis=2 format=h265 bitrate=18000000 gop=30 vui=709` | ✅ |

> 串口：COM21 @ 2000000（`system.yaml` `serial.port=auto`；旧脚本写死的 COM23 已不存在）。

## 三、全 60 组合结果

**OK = 47 / SET_FAIL = 12 / STUCK = 1**（板卡共跑 3 轮，冷启动 2 次，合并去重后逐组合结果）。

### 3.1 SET_FAIL（12 条，命令被拒未录像）

全部为 **`fps 60` 打在 `3k` / `1080p`**（各 6 条 = eis 0/1/2 × h264/h265），与 Q2 规则一致：

```
I/CtrlCfg: fps 60 not supported on 3k,    use 30 or pick sd1080p|720p|480p for 60
I/CtrlCfg: fps 60 not supported on 1080p, use 30 or pick sd1080p|720p|480p for 60
```

### 3.2 STUCK（1 条，固件状态机挂死）

`sd1080p fps 60 eis 2 format h265` —— SET 成功、编码写盘成功（板上实落 41MB `.h265`），但 `cam_run video stop` 超时，
`cam_run status` 卡在 `state: stopping (backend: dfs)`；**软恢复全无效，仅断电可解**；**冷启动后复跑同组合确定性复现**。
详见 [`known_issue.md`](../05_handoff/known_issue.md)。

### 3.3 OK 的 47 条 → 去重后 **43 个唯一可用组合**

> `3k` 强制 `eis=2`（请求 eis 0/1 固件一律回 `eis=2`，原文 `3k requires offline eis, forcing it`），
> 故 3k 的 6 条 OK 只对应 2 个物理组合。43 = 47 − 4（3k 重复）。

| res | fps | 唯一可用组合（effective eis × codec） |
|---|---|---|
| 3k | 30 | eis2-h264, eis2-h265 |
| 1080p | 30 | eis0/1/2 × h264/h265（6） |
| sd1080p | 30 | eis0/1/2 × h264/h265（6） |
| sd1080p | 60 | eis0/1 × h264/h265 + eis2-h264（**eis2-h265 挂死排除**） |
| 720p | 30 | eis0/1/2 × h264/h265（6） |
| 720p | 60 | eis0/1/2 × h264/h265（6） |
| 480p | 30 | eis0/1/2 × h264/h265（6） |
| 480p | 60 | eis0/1/2 × h264/h265（6） |
| **合计** | | **43** |

## 四、对工程的影响（交 Document Agent / Code Agent）

| # | 影响 | 级别 | 处置 |
|---|---|---|---|
| 1 | `VIDEO_SET_COMMAND` 位置式 → 关键字式 | **Level 2** | 改 `drivers/video_commands.py` L30 一处常量（ADR-011 范式，**无需新 ADR**）；见 [`next_step.md`](../05_handoff/next_step.md) |
| 2 | `VIDEO_FPS_FORCED` 补 `1080p`（实测 1080p 不支持 fps60） | Level 1 | 同上文件一处常量 |
| 3 | `sd1080p fps60 eis2 h265` 固件挂死 | 固件 bug | 记入 [`known_issue.md`](../05_handoff/known_issue.md)；场景/矩阵须排除该组合 |
| 4 | 旧 WIP「最多 3 选项对」规则过时 | 文档 | 已在 `_wip_video_probe/README.md` 标注 |

## 五、TODO-CONFIRM

- `TODO-CONFIRM: 60 组合仅在 5s 短录下验证；长录像/连续压测下 sd1080p fps60 eis2 h265 是否同样挂死未验证。`
- `TODO-CONFIRM: 480p/720p 配 18Mbps 是否偏高（用户文件「待确认」项），属产品决策。`
- `TODO-CONFIRM: gop 是否需随 fps 变化（60fps 时 gop 30 = 0.5s），本次未测。`
