# 下一步（Next Step）

> 只保留未完成任务，按优先级。

## 🔴 P0-1 — stress/aging 场景 WiFi 前置缺失

`--no-interactive-wifi + stress` 时：`wifi_connect` 动作跳过 → `ctx.evb_ip` 拿不到 → `ftp_ready` 的 `start_ftp` 因无 evb_ip 返回 None → photo/video 无 ftp_client 全 SKIP → rtmp FAIL。

两个方向：

- **方向 A（推荐）**：给 prepare 加「非交互连接 WiFi」动作（用 system.wifi 默认 ssid/pwd 连，不弹交互），stress/aging 的 prepare 用它替代 wifi_connect。
- **方向 B**：给 scenario 加 `pre_tasks`（循环外任务）结构，执行一次、tasks 被 loop 循环。改动更大但更通用。

## 🔴 P0-2 — 全部改动待真机验证

```bash
python3 -m ATS.main --scenario normal --no-interactive-wifi   # 先通正常链路
python3 -m ATS.main --scenario stress --no-interactive-wifi   # 再通压测循环（受 P0-1 影响）
```

## 🟡 P1 — loop 语义局限

当前 loop 只能循环「整轮 tasks」，不支持「A 任务循环 N 次 + B 只跑 1 次」混合编排（目前靠 task.repeat + scenario.loop 两层凑合）。

## 🟡 P2 — 破坏性 CLI 变更

`--modules`/`--skip` 已移除，`--scenario` 成为主入口。旧文档命令全部失效，需同步。

## 🟢 P3 — RTMP 类型2 网络异常未覆盖

heartbeat 只能证明「板端编码线程活着」，证明不了「网络断但板端仍在编码」（f_index 持续但 ffprobe 收不到）。如需覆盖需补周期 ffprobe 复探。
