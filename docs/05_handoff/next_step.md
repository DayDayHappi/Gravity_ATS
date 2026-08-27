# 下一步（Next Step）

> 只保留未完成任务，按优先级。

## 🔴 紧急 — video 判据修正（源码 bug，待 Code Agent 修复）

`ATS/modules/video.py` 的 `dfs_video_stop` 判据错误，实测日志
（`logs/stress/logs/20260826_030311/serial.log`）确认：

- **正确判据**：`Video recording completed successfully.`（录像全流程走完的最终完成标志）
- **当前错误实现**：`expect=r"Save Video Successful:\s*(\S+)"`，且路径从捕获组 `r.matched` 取
- **两个问题**：
  1. `Save Video Successful` 出现更早（实测约早 2s），此时录像收尾（编码 finalize/落盘）未完成；
  2. 其路径会被串口分块截断（实测 `Save Video Successful: /emmc/VI`），捕获组取到截断路径，
     导致后续 `ftp2.size()` 校验对象错误 → 偶发 FAIL / 校验跳过（flaky）。
- **对称改法**（参考 `photo.py` 已完成的同类修复，`Capture completed successfully.` + 从累积缓冲扫描）：
  1. `expect=r"Video recording completed successfully."`
  2. 路径从 `r.clean` 累积缓冲扫描 `/emmc/VIDEO/<dir>/Video_<n>_0.h265`，不依赖 `r.matched` 捕获组。
- **文档已同步**（test_case / test_strategy / data_flow / module_design / README §7.4），源码待 Code Agent 改。

## 🔴 P0 — 全部改动待真机验证

以下改动均已离线验证通过，**尚未真机验证**：

- Scenario 层重构 + 第四次交接 4 项改动（TX/RX 时间戳、exec_async 去哨兵、RTMP heartbeat、测试结束询问）
- 20260824 改动：normal 移除重复 ftp task、修复 `--no-interactive-wifi` 断链、WiFi 职责重划（ADR-008）、depends 字段清理（ADR-009）
- 20260825 改动：ADR-010 PreviewManager 单例播放器源码已实施（design 层 devlog 留痕，见 [P1 验收项](#🟡-p1--adr-010-previewmanager-待实施)）

```bash
python3 -m ATS.main --scenario normal --no-interactive-wifi   # 先通正常链路
python3 -m ATS.main --scenario stress --no-interactive-wifi   # 再通压测循环
```

## 🟡 P1 — ADR-010 PreviewManager 待真机验收

设计已定（[ADR-010](../02_design/decision_record/ADR-010-PreviewManager单例播放器.md)），源码已实施（devlog `20260825_0111_PreviewManager单例播放器实施.md`），**待真机验收**：

- 已实施：`ATS/drivers/preview_manager.py`（单例，含断流重连 wrapper）+ `config/modules/preview.yaml`；`rtmp.py` 移除全部 ffplay 逻辑；`scenario_manager.py` 新增 `preview_start`/`preview_stop`；`normal.yaml`/`stress.yaml` 补配置（`aging.yaml` 不启用）。
- 验收项：normal 全程 1 个 ffplay 窗口；stress repeat=3/loop 多轮不重复开窗、无残留进程；cleanup 正常关闭窗口。
- 已知遗留（见 devlog）：终端窗口模式 `killpg` 属 best-effort；`preview_required: true` 尚未闭环「影响整体结果」。

## 🟡 P2 — 新增场景 stress_traverse_photo_mode（待实施）

需求已整理：[新增场景需求_stress_traverse_photo_mode.md](../03_development/archive/新增场景需求_stress_traverse_photo_mode.md)。

- 新增 `ATS/config/scenarios/stress_traverse_photo_mode.yaml`，与 `stress.yaml` 唯一差异是
  photo task 用 `override.photo_modes` 遍历全部拍照模式（`auto/single/mfnr/hdr_0~3`）。
- 已核查现有 `override` + `repeat` 机制足够，**预计不需要改 `photo.py`/Runner/Scenario**，
  纯新增配置文件。
- `photo_modes` 具体 7 个模式名需 Code Agent 真机核实（TODO-CONFIRM，见需求文档）。

## 🟡 P4 — loop 语义局限

当前 loop 只能循环「整轮 tasks」，不支持「A 任务循环 N 次 + B 只跑 1 次」混合编排（目前靠 task.repeat + scenario.loop 两层凑合）。

## 🟡 P5 — 破坏性 CLI 变更

`--modules`/`--skip` 已移除，`--scenario` 成为主入口。旧文档命令全部失效，需同步。

## 🟢 P6 — RTMP 类型2 网络异常未覆盖

heartbeat 只能证明「板端编码线程活着」，证明不了「网络断但板端仍在编码」（f_index 持续但 ffprobe 收不到）。如需覆盖需补周期 ffprobe 复探。
