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
- 已实施（devlog `20260921_1104`），待真机验证。
