# BUG-006 修复：serial_reconnect 端口探测与旧串口句柄冲突致恢复失败

## 问题描述

recovery_validation 真机（2026-09-23，日志 `logs/recovery_validation/20260923/20260923_105132`）：
录像中途拔掉板子电源后，死机检测（SUSPECTED→probe 3 次失败→UNRESPONSIVE）与 PowerCycle
（下电/上电 + 回帧校验）都成功，但 `serial_reconnect` 报「PowerCycle 后 EVB UART 未重新枚举」
→ restore 失败 → `on_exhausted=abort_scenario` → task 没重跑，`board_recovery` 判 ERROR。

## 根因分析

`_action_serial_reconnect` 的执行顺序 bug（两个句柄抢同一端口）：

```python
# 1. 先探测 EVB 端口（此时旧 SerialConsole reader 仍持有原端口的打开句柄）
new_port, _ = _detect_evb_with_wait(...)   # 内部 _probe_port_baud 会 open 同一端口
# 2. 探测到才 reconnect（reconnect 内部才 close 旧句柄）
console.reconnect(port=new_port, ...)
```

`_probe_port_baud` 对候选端口逐个 `serial.Serial(port).open()` 做指纹探测，但此时旧
`SerialConsole` 的 reader thread 仍持有原端口（`/dev/ttyUSB2`）的打开句柄 → 两个句柄抢同一
端口 → pyserial 报 `multiple access on port` → 探测 30s 超时 → 误判「未重新枚举」。

关键证据：serial.log 显示板子其实 boot 成功（原串口一直在收 `msh />`/`FW start ok`），
`/dev/ttyUSB2` 根本没消失（UART 桥独立供电）。「未重新枚举」是探测被旧句柄阻塞造成的假象。

## 修复内容

`_action_serial_reconnect`（`ATS/core/scenario_manager.py`）：

1. **探测前先 `console.close()`**：记录 `old_port` 后，先关旧 reader + 旧 pyserial 句柄，
   再谈端口探测（释放端口，避免探测 open 与旧 reader 抢同一端口）。
2. **原端口未消失时直接沿用**：`old_port` 仍在可访问列表（且非 PowerSwitch 端口）→ 直接
   `console.reconnect(old_port)`，不做 `_detect_evb_with_wait`（本次日志即此情况，省掉无谓的
   30s 空等 + 探测）；仅原端口消失（真重枚举到新设备名）才走 bounded wait 探测。

架构红线不变：serial_reconnect 仍只做 transport 重建、保持 SerialConsole 对象身份不变、
不碰 PowerSwitch/WiFi/FTP/health policy/Task retry。

## 验证结果（离线）

- `compileall ATS/` 通过。
- 新增离线单测 `SerialReconnectActionBug006Test`：mock「旧句柄持有原端口时」场景，确认
  `_action_serial_reconnect` 先 close 旧句柄、原端口未消失时直接 reconnect 原端口（不探测）。
- `python3 -m unittest discover -s tests`：37 用例全过。

**待真机复现**（BUG-006 Verification）：
1. 拔板子电源复现 → serial_reconnect 不再报「未重新枚举」；原端口未消失时快速完成。
2. 完整链走通：UNRESPONSIVE → OFF → ON → serial_reconnect → board_ready → health_check →
   WiFi → FTP → retry_current_task，video task 重跑一次，board_recovery 不再 ERROR。
3. 人为制造真重枚举（拔 EVB USB-UART 线再插回）→ 探测路径仍能找新端口并 reconnect。

## 还会再有吗

- 若真机仍偶发 `multiple access on port`，需进一步确认 PowerCycle 前是否还有其他 holder
  （当前已确保 serial_reconnect 探测前 close 旧句柄）。
- 探测路径（真重枚举）保留了 bounded wait，超时值 `power_on_detect_timeout` 需真机校准。

## 经验沉淀

- 串口探测/重连前必须先释放旧句柄：pyserial 对同一端口多个 open 会报 `multiple access on
  port`，探测逻辑被旧 reader 阻塞时会把「端口未消失」误判成「未重新枚举」。
- 优先「端口未消失直接沿用」而非「一律重新探测」：既避免句柄冲突，又省掉无谓的超时等待。
- 恢复链任一环节的失败定位要看日志证据链（serial.log 的 boot 成功 vs recovery.log 的「未
  枚举」矛盾），能直接区分「真未枚举」与「探测被阻塞」。
