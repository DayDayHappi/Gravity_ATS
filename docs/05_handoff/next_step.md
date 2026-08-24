# 下一步（Next Step）

> 只保留未完成任务，按优先级。

## 🔴 P0-1 — WiFi 职责重划源码实施（ADR-008 已 Accepted，待 Code Agent）

决策已定（2026-08-24 用户确认），源码改动清单：

1. `ATS/config/scenarios/normal.yaml`：tasks 移除 `wifi_check` / `wifi_scan` / `wifi_join`（7 项 → 4 项：emmc/photo/video/rtmp）。
2. `ATS/core/scenario_manager.py` `_action_wifi_connect`：加「先 wifi_check 检测已联网则保留」逻辑，成为状态收敛器。
3. `ATS/modules/wifi.py`：`wifi_check` 产出 `ctx.wifi_ready`（True/False，检测到 IP 才 True）；`wifi_scan`/`wifi_join` 代码保留但退出默认流程。

实施后按留痕规则写 devlog，并回交 Document Agent 复核架构文档。

## 🔴 P0-2 — 全部改动待真机验证

以下改动均已离线验证通过，**尚未真机验证**：

- Scenario 层重构 + 第四次交接 4 项改动（TX/RX 时间戳、exec_async 去哨兵、RTMP heartbeat、测试结束询问）
- 20260824 改动：normal 移除重复 ftp task、修复 `--no-interactive-wifi` 断链
- 待 P0-1 实施的 WiFi 职责重划

```bash
python3 -m ATS.main --scenario normal --no-interactive-wifi   # 先通正常链路
python3 -m ATS.main --scenario stress --no-interactive-wifi   # 再通压测循环
```

## 🟡 P1 — loop 语义局限

当前 loop 只能循环「整轮 tasks」，不支持「A 任务循环 N 次 + B 只跑 1 次」混合编排（目前靠 task.repeat + scenario.loop 两层凑合）。

## 🟡 P2 — 破坏性 CLI 变更

`--modules`/`--skip` 已移除，`--scenario` 成为主入口。旧文档命令全部失效，需同步。

## 🟢 P3 — RTMP 类型2 网络异常未覆盖

heartbeat 只能证明「板端编码线程活着」，证明不了「网络断但板端仍在编码」（f_index 持续但 ffprobe 收不到）。如需覆盖需补周期 ffprobe 复探。
