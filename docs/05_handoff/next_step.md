# 下一步（Next Step）

> 只保留未完成任务，按优先级。

## 🔴 紧急 — video 启动判据改 f_index + 失败清理 dfs_video_stop（待 Code Agent）

**问题**（实测 `logs/stress_traverse_photo_mode/logs/20260827_034923`）：连续压测第 10 轮，
`dfs_video_start` 后固件漏打 `Record Start`（摄像头资源退化），但编码实际在跑（`f_index` 持续增长）。
当前 `video.py` 只等 `Record Start`（`result_timeout=25s`），于是误判「开始录像失败」FAIL，
且失败分支**直接 return、没有发 `dfs_video_stop` 清理**，把 stream_on 半初始化态泄漏给下一个
rtmp task → ffprobe `Input/output error`（run.log cycle 10~12 连锁 FAIL/SKIP）。

**需求**（用户明确要求）：
1. 启动成功判据加 `f_index` 检测——`f_index` 是录像编码心跳，每 90 帧发一次，
   第一次 `f_index = 0`、第二次 `f_index = 90`。有 `Record Start` **或** `f_index` 出现
   都应判启动成功（不只看 `Record Start`）。
2. 判定启动失败后，补发一次 `dfs_video_stop` 清理状态（best-effort，不判结果）。

**f_index 实测格式**（video 录像，无 `[RTMP]` 前缀，区别于 rtmp_monitor 监听的 `[RTMP] f_index`）：
```
[05:22:48.401] I/NO_TAG: Gravity_XR Record Start
[05:22:50.385] I/NO_TAG: f_index = 0, f_len = 83618, cur_total_len = 83709     ← Record Start 后约 2s
[05:22:53.384] I/NO_TAG: f_index = 90, f_len = 159743, ...                     ← 再约 3s
[05:22:56.392] I/NO_TAG: f_index = 180, ...
```
剥 ANSI 后形如 `... I/NO_TAG: f_index = 0, f_len = 83618, cur_total_len = 83709`。

**修复建议**（`ATS/modules/video.py` L64-66，由 Code Agent 落地，参考 rtmp_monitor.py 的 `_HEARTBEAT_RE`）：
- 判据正则：`expect=r"Record Start|f_index\s*="`（兼容 Record Start 与 f_index）；
  若要求「稳定」，可等到 `f_index\s*=\s*(?:90|[1-9]\d\d)`（跳过 f_index=0 等到第二次 ≥90）。
- 失败清理：`if not r.success:` 分支里，先 `console.exec_async("dfs_video_stop", expect=..., result_timeout=短超时)` 尽力停掉，
  再 return FAIL。注意 `dfs_video_stop` 的完成判据用 `Video recording completed successfully.`（见上个 video 判据修复）。

**参考**：`ATS/modules/rtmp_monitor.py`（f_index 正则）、`ATS/README.md` §7.9（同源摄像头资源冲突已知问题）。

## 🔴 P0 — 全部改动待真机验证

以下改动均已离线验证通过，**尚未真机验证**：

- Scenario 层重构 + 第四次交接 4 项改动（TX/RX 时间戳、exec_async 去哨兵、RTMP heartbeat、测试结束询问）
- 20260824 改动：normal 移除重复 ftp task、修复 `--no-interactive-wifi` 断链、WiFi 职责重划（ADR-008）、depends 字段清理（ADR-009）
- 20260825 改动：ADR-010 PreviewManager 单例播放器源码已实施（design 层 devlog 留痕，见 [P1 验收项](#🟡-p1--adr-010-previewmanager-待真机验收)）
- 20260826 改动：
  - video 判据修复：`Save Video Successful` → `Video recording completed successfully.` + 路径从 `r.clean` 累积缓冲扫描（devlog `20260826_2321`；与 photo 判据修复同类的对称 bug，实测路径分块截断致 flaky）
  - 新增场景 `stress_traverse_photo_mode.yaml`：photo task 用 `override.photo_modes` 遍历全部拍照模式（`auto/single/mfnr/hdr_0~3`），其余与 stress 一致；`hdr` 模式名待真机核实（TODO-CONFIRM，见场景文件注释）

```bash
python3 -m ATS.main --scenario normal --no-interactive-wifi            # 先通正常链路
python3 -m ATS.main --scenario stress --no-interactive-wifi            # 再通压测循环
python3 -m ATS.main --scenario stress_traverse_photo_mode --no-interactive-wifi  # 遍历全拍照模式压测（先小 repeat 冒烟）
```

## 🟡 P1 — 新增场景 stress_traverse_photo_mode_seq（待实施）

需求已整理：[新增场景需求_stress_traverse_photo_mode_seq.md](../03_development/archive/新增场景需求_stress_traverse_photo_mode_seq.md)。

- 新增 `ATS/config/scenarios/stress_traverse_photo_mode_seq.yaml`，实现「模式优先」顺序：
  auto×N → single×N → … → hdr_3×N（与 `stress_traverse_photo_mode.yaml` 的 round-robin 相对）。
- **纯配置，不改源码**：每模式一个 photo task + 单元素 `override.photo_modes` + `repeat`。
- `hdr_0~3` 模式名仍带 TODO-CONFIRM（与上个场景同源），真机一并核实。

## 🟡 P2 — ADR-010 PreviewManager 待真机验收

设计已定（[ADR-010](../02_design/decision_record/ADR-010-PreviewManager单例播放器.md)），源码已实施（devlog `20260825_0111_PreviewManager单例播放器实施.md`），**待真机验收**：

- 已实施：`ATS/drivers/preview_manager.py`（单例，含断流重连 wrapper）+ `config/modules/preview.yaml`；`rtmp.py` 移除全部 ffplay 逻辑；`scenario_manager.py` 新增 `preview_start`/`preview_stop`；`normal.yaml`/`stress.yaml` 补配置（`aging.yaml` 不启用）。
- 验收项：normal 全程 1 个 ffplay 窗口；stress repeat=3/loop 多轮不重复开窗、无残留进程；cleanup 正常关闭窗口。
- 已知遗留（见 devlog）：终端窗口模式 `killpg` 属 best-effort；`preview_required: true` 尚未闭环「影响整体结果」。

## 🟡 P3 — loop 语义局限

当前 loop 只能循环「整轮 tasks」，不支持「A 任务循环 N 次 + B 只跑 1 次」混合编排（目前靠 task.repeat + scenario.loop 两层凑合）。

## 🟡 P4 — 破坏性 CLI 变更

`--modules`/`--skip` 已移除，`--scenario` 成为主入口。旧文档命令全部失效，需同步。

## 🟢 P5 — RTMP 类型2 网络异常未覆盖

heartbeat 只能证明「板端编码线程活着」，证明不了「网络断但板端仍在编码」（f_index 持续但 ffprobe 收不到）。如需覆盖需补周期 ffprobe 复探。
