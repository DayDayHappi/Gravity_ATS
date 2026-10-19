# P0 修复：power_switch_init 误改 EVB 串口波特率致 WiFi 零响应

## 问题描述

真机 stress（2026-09-30，`logs/stress/20260930/20260930_134705`、`134522`）：
`power_switch.enabled=true` + `serial.port=auto` 时，`power_switch_init` 在 `serial_init`
之后跑，把**已打开的 EVB 串口**（如 `/dev/ttyUSB2`）误当上下电控制器候选，以 115200 发
二进制帧 `A0 01 03 A4`。Linux tty 波特率是设备级（termios）持久状态，探测句柄 close 后
波特率不回退 → EVB 串口实际变 115200，而 `SerialConsole` 仍自认 2000000 → 后续
`wifi join` 零响应 30s 超时，WiFi/FTP 全挂。

触发条件：serial.port=auto + power_switch.enabled=true + prepare 顺序
serial_init→power_switch_init + 候选串口含 EVB（控制器未接、只剩 EVB 一个串口时必中）。

## 根因

`_action_power_switch_init` 的 `exclude` 只排除显式配置的 `serial.port`，未排除
`serial_init` 已实际探测出的 `ctx.console.port`。

## 修复内容

`ATS/core/scenario_manager.py` `_action_power_switch_init`：
- `exclude` 补充 `getattr(getattr(ctx, "console", None), "port", None)`——serial_init 已
  探测出的 EVB 端口；用 `getattr(..., None)` 兼容冷启动（console 为 None）零影响。
- 保留显式 `serial.port` 排除逻辑（去重后 append）。

## 验证结果（离线）

- `compileall ATS/` 通过。
- 离线 mock 三项：
  1. `ctx.console.port=/dev/ttyUSB2` + `_accessible_ports=[/dev/ttyUSB2, /dev/ttyUSB5]`
     → candidates 只剩 `/dev/ttyUSB5`（EVB 端口被排除）。
  2. 冷启动 `console=None` → 仍探测全部候选（recovery 回归零影响）。
  3. 显式 `serial.port=/dev/ttyUSB2` → candidates 空 → 不探测（去重后跳过）。
- `python3 -m unittest discover -s tests`：45 用例全过（新增 test_power_switch_init_exclude_evb.py 3 用例）。

**待真机**：
1. 只接 EVB、不接控制器，`power_switch.enabled=true` + `serial.port=auto` 跑 stress，
   确认 `wifi_connect` 正常拿到 `Got IP address`。
2. 回归 recovery_validation（冷启动顺序 power_switch_init→serial_init）仍能正常探测控制器。

## 还会再有吗

- 根治后 power_switch_init 不再误改 EVB 串口波特率；若未来出现「显式 serial.port 但
  仍是 auto 探测实际端口」的边界（serial.port 显式 + console.port 不同），当前双重排除
  （显式 serial.port + ctx.console.port）已覆盖。
- 生产机若配置稳定 by-id（power_switch.port / serial.port），本 bug 天然不触发。

## 经验沉淀

- 串口探测的「候选排除」必须覆盖「已打开的设备」而不只是「已配置的设备名」：serial_init
  后 ctx.console.port 是运行时事实，显式 serial.port 只是配置声明，二者可能不同（auto 探测）。
- Linux tty 波特率是设备级持久状态（termios），探测句柄 close 后不回退——对已打开串口做
  异波特率二进制探测会造成「设备实际波特率与持有者认知不一致」的隐性破坏，且无异常抛出。
- 上下电控制器探测（115200 二进制帧）与 EVB 串口（2000000 文本协议）虽协议互斥，但都走
  同一 `/dev/tty*` 命名空间，候选排除是防接反/防误改的最后一环。
