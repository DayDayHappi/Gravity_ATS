# 数据流（Data Flow）

> 三条主数据流的走向，帮助理解「数据从哪来、到哪去、怎么验证」。

## 1. 串口控制流（命令 ↔ 响应）

```
PC 脚本 ──发送命令──> EVB (msh shell)
   ▲                      │
   │                      ▼
   └────接收响应──── 执行并输出结果
```

- 同步命令：发 `cmd` + 哨兵，等哨兵定界。
- 异步命令：只发 `cmd`，等业务正则。
- 常驻读线程持续采集串口字节 → 写 `serial.log` + 喂环形缓冲（每 chunk 打单调递增序号，
  命令响应按「序号游标」定位增量，见 BUG-005）。

## 2. 文件产物流（拍照 / 录像）

```
EVB 摄像头 ──拍照/录像──> /emmc/PIC/ 或 /emmc/VIDEO/
                              │
                              │ FTP 下载（主动模式）
                              ▼
                        PC 本地目录 ──校验──> 判据（JPEG 头 / 大小）
```

- 主判据：串口正向标志（`Capture completed successfully.`；录像为 `Video recording completed successfully.`）。
- 辅助判据：FTP 下载 + JPEG 头（FFD8FF）+ 大小阈值，失败降级不判 FAIL。

## 3. RTMP 推流流（推流 → 探测）

```
EVB 编码 ──RTMP──> PC nginx-rtmp (1935)
                     │
                     │ ffprobe 实时探测
                     ▼
                判据：h264 + 分辨率 + heartbeat 无超时
```

- 时序关键：先 `check_ready(1935)` → 推流 start → 等上线 → ffprobe 探测 → **探测必须在 stop 之前** → stop。
- heartbeat：订阅板端 `[RTMP] f_index` 日志，超时判推流异常。

## 4. 上下文流转（跨模块共享）

```
prepare.wifi_connect ──> ctx.evb_ip（收敛器：先 wifi_check 检测，未连才 join）
ftp_ready            ──> ctx.ftp_client（供 photo/video 复用）
photo/video          ──> 消费 ctx.ftp_client
rtmp                 ──> 消费 ctx.evb_ip + pc_ip
```

模块间通过共享上下文传递数据，不互相 import。

## 5. 电源控制流（上下电控制模块，ADR-015）

```
PC ──串口(115200)──> 上下电控制模块 ──电源线──> EVB 板（断电/上电）
```

- 4 字节 hex 帧，末字节 = 前三字节求和 `& 0xFF`；上电 `A0 01 03 A4`、下电 `A0 01 02 A3`、
  状态返回 `A0 01 <state> <sum>`（`01`=ON/`00`=OFF）。协议字节唯一来源 `drivers/power_commands.py`。
- 端口区分：启用时对候选串口按 115200 发上电帧，回 `A0 01 01 A2` 者 = 控制器，另一 = EVB（防接反）。
- `reboot()` = 下电 → 延时（`reboot_delay`）→ 上电；延时默认值待真机确定（TODO-CONFIRM）。
- 触发时机（何时重启）由独立模块 import 调用，本能力只被动执行，禁止耦合。
- 已实施（devlog `20260921_1104`），真机通过（TC-PS-001 压测 PASS）。

## 6. 健康监测与恢复流（板卡健康监测，ADR-016，已实施·待真机）

```
EVB 串口活动 ──> BoardHealthMonitor（观察 + 状态判定，不调 PowerSwitch）
                      │ HealthEvent
                      ▼
             RecoveryCoordinator（恢复决策 + 次数限制 + Context 失效）
                      │ 统一 recover() 请求
                      ▼
             RecoveryBackend（PowerCycleBackend → PowerSwitch.reboot()）
                      │ 上下电（复用 ADR-015 电源控制流）
                      ▼
             环境重新收敛（board_ready → WiFi → preclean → FTP ready）
                      │
                      ▼
             Runner 恢复流程（retry_current_task / abort_scenario）
```

- **状态机（Monitor）**：`HEALTHY →（超 inactivity_timeout）→ SUSPECTED →（主动 health_check 连续失败 confirm_failures 次）→ UNRESPONSIVE`。UNRESPONSIVE 只表示 ATS 无法通过 EVB 控制链路取得有效响应，不推断根因。
- **状态机（Coordinator）**：`IDLE → REQUESTED → RECOVERING → RECONCILING → HEALTHY`（失败进 FAILED）；`recovery_in_progress` 互斥，同一时间只允许一个恢复流程。
- **健康确认**：`last_rx` 超时只进 SUSPECTED；主动 probe 复用 `console.health_check()`（`echo EVBTEST_HELLO`），必须在 Runner 安全点执行（Monitor listener 只观察，禁止下发命令）。
- **Context 失效**：PowerCycle 后 `evb_ip`/`wifi_ready`/`skip_wifi`/`ftp_client`/`ftp_server_started` 失效（`invalidate_board_runtime_state()`，不调 `ctx.cleanup()`）；`system_config`/`power_switch`/`recovery_coordinator`/`board_health_monitor`/`pc_ip` 保持。
- **事件留痕**：`ctx.recovery_history` + 报告 `recovery_events` 区；恢复事件不被后续 PASS 覆盖；日志 `recovery.log` 独立于 `serial.log`。
- **红线**：Monitor 不认识 PowerSwitch；Module 不认识 Recovery；Runner 不认识具体硬件；RTMP heartbeat timeout 但 shell health_check PASS 只判 RTMP FAIL，禁止 PowerCycle。
