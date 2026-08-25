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
- 常驻读线程持续采集串口字节 → 写 `serial.log` + 喂环形缓冲。

## 2. 文件产物流（拍照 / 录像）

```
EVB 摄像头 ──拍照/录像──> /emmc/PIC/ 或 /emmc/VIDEO/
                              │
                              │ FTP 下载（主动模式）
                              ▼
                        PC 本地目录 ──校验──> 判据（JPEG 头 / 大小）
```

- 主判据：串口正向标志（`Capture completed successfully.`；录像为 `Save Video Successful`）。
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
