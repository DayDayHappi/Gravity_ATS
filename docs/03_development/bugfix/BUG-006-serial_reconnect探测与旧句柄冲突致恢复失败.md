# BUG-006：serial_reconnect 端口探测与旧串口句柄冲突致恢复失败

## Problem

recovery_validation 真机（2026-09-23，日志 `logs/recovery_validation/20260923/20260923_105132`）：
录像中途人为拔掉板子电源后，死机检测与 PowerCycle 均成功，但恢复链在 `serial_reconnect` 失败：

```
10:54:26.672 PowerCycleBackend: power cycle 完成
10:54:27.916 [WARN] 串口读异常: device reports readiness to read but returned no data
                     (device disconnected or multiple access on port?)
10:55:03.296 [ERROR] 环境重新收敛失败(serial_reconnect): serial_reconnect: PowerCycle 后 EVB UART 未重新枚举
10:55:03.296 [ERROR] board_recovery - 恢复失败：... reason=restore failed at serial_reconnect
```

最终 `on_exhausted=abort_scenario` 直接中止 Scenario，**没有走到 `after_recovery=retry_current_task`**。

现象：串口控制器确实重新下电→上电了（power_switch.log 有 OFF/ON 帧 + 回帧），但 task 未重跑。

## Root Cause

`_action_serial_reconnect`（`ATS/core/scenario_manager.py`）的执行顺序有 bug：

```python
# 1. 先探测 EVB 端口（此时旧 SerialConsole 仍持有原端口的打开句柄）
new_port, detected_baud = _detect_evb_with_wait(...)   # 内部 _probe_port_baud 会 open 同一端口
# 2. 探测到才 reconnect（reconnect 内部才 close 旧句柄）
console.reconnect(port=new_port, baudrate=baudrate)
```

`_detect_evb_with_wait` → `_probe_port_baud` 会对候选端口逐个 `serial.Serial(port, ...).open()` 做指纹探测。
但此时旧 `SerialConsole` 的 reader thread 仍持有原 EVB 端口（本次为 `/dev/ttyUSB2`）的打开句柄，
两个句柄抢同一端口 → pyserial 报 `multiple access on port` → 探测失败 → 30s 超时 → 误判「EVB UART 未重新枚举」。

**关键证据**：serial.log 显示板子其实 boot 成功了（原串口一直在收到 `msh />` / `FW start ok`），
`/dev/ttyUSB2` 根本没有消失（说明 UART 桥独立供电）。「未重新枚举」是探测逻辑被旧句柄阻塞造成的假象。

## Solution（给 Code Agent 的修复方案）

`_action_serial_reconnect` 需修正：**先关旧 transport 再探测**，或**端口未消失时直接沿用原端口**。

推荐分两步：

### 1. 先关闭旧 transport（探测前）

在 `_action_serial_reconnect` 开头，探测端口**之前**，先关掉旧句柄：

```python
console = getattr(ctx, "console", None)
if console is None:
    raise ScenarioError("serial_reconnect: 无 console，无法重建 transport")

old_port = console.port   # 记录原端口

# 先关旧 transport（释放端口，避免探测时与旧 reader 抢同一端口）
console.close()

# 之后再做端口探测 / 直接 reconnect
```

### 2. 端口未消失时直接沿用原端口（避免无谓的 30s 空等 + 探测）

如果 `old_port` 仍在候选端口列表里（本次日志即如此，说明 USB-UART 独立供电、未消失），
**直接 `console.reconnect(old_port)`，不做 `_detect_evb_with_wait`**；仅当原端口已消失
（真重枚举到新设备名）时才走探测。

```python
# auto 模式下：
#   a. 原端口仍在可访问列表 → 直接 reconnect(old_port)
#   b. 原端口消失 → 才 _detect_evb_with_wait 找新端口（此时旧句柄已 close，无冲突）
```

### 约束（保持架构红线，见 design 文档 §33）

- `serial_reconnect` 只做 transport 重建，仍不负责 board_ready（msh ready + health_check 由 `board_ready` 单独做）。
- 保持 `SerialConsole` 对象身份不变（`reconnect()` 不新建对象）。
- 不碰 PowerSwitch / WiFi / FTP / health policy / Task retry。
- 若最终仍要保留探测路径，`_probe_port_baud` 探测时必须先确保旧句柄已 close，否则必现 `multiple access on port`。

## Verification

真机验证通过（2026-09-23，日志 `logs/recovery_validation/20260923/20260923_111113`）：

1. ✅ `serial_reconnect` 不再报「EVB UART 未重新枚举」；原端口未消失时直接重连，**不再空等 30s**（`serial_reconnect: 原端口 /dev/ttyUSB2 仍在，直接重连（不探测）`）。
2. ✅ 完整恢复链走通：`UNRESPONSIVE → OFF → ON → serial_reconnect → board_ready（fresh-ready）→ health_check → WiFi → FTP → retry_current_task`，video task 成功重跑一次。
3. ✅ `board_recovery` 不再 ERROR；`recovery_history` 记录 `recovery_result=ok, restore_result=ok`。
4. ✅ 离线单测 37 用例全过（新增 `SerialReconnectActionBug006Test`：mock 旧句柄持有原端口时，确认先 close、原端口未消失直接 reconnect 不探测）。

> 注：重跑后的 video task 因用户手动 Ctrl+C 中断（`用户中断循环`）未完成第二次录像，属测试过程主动终止，非恢复链路缺陷；恢复本身已完整 PASS。

## 关联

- devlog：`20260923_1110_BUG006_serial_reconnect探测与旧句柄冲突修复.md`
- 设计：`../archive/ADR016_电源控制冷启动与串口生命周期修复设计.md`（§12~§17 serial_reconnect 契约）
- 真机日志：`logs/recovery_validation/20260923/20260923_111113/`
- 待办：`../../05_handoff/next_step.md`（ADR-016 P0）
