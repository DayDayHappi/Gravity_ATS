# 模块设计（Module Design）

> 每个模块的职责边界。修改模块前先读本表，确认「该模块负责什么、不该负责什么」。

## 模块职责总览

| 模块 | 职责 | 成功判据 |
|------|------|---------|
| wifi_check | 检测 EVB 是否已联网 | ifconfig 有非 0.0.0.0 IP |
| wifi_scan | 扫描附近 WiFi AP | 表头 + ≥1 行数据 |
| wifi_join | 连接指定 WiFi | `Got IP address : <IP>` |
| emmc | 进入 eMMC 目录 | `cd /emmc` 无 error |
| ftp | 启动 FTP 服务 + 连接验证 | 列出 `/emmc` 成功 |
| photo | 拍照并验证产物 | 串口 `Save Photo Successful` |
| video | 录像并验证产物 | 串口 `Save Video Successful` |
| rtmp | 推流并验证流到达 | ffprobe 探到 h264 + heartbeat 无超时 |
| rtmp_monitor | 订阅串口原始数据，检测推流 heartbeat | f_index 超时判异常 |

---

## wifi_check

- **Responsibility**：检测已联网状态，联网则跳过后续 scan/join 并缓存 IP。
- **Input**：串口 `ifconfig` 输出。
- **Output**：`ctx.skip_wifi` 标志 + `ctx.evb_ip`。
- **Dependency**：无。
- **Forbidden Dependency**：不主动连接 WiFi。
- **Lifecycle**：单次执行，无清理。

## wifi_scan

- **Responsibility**：扫描 AP，解析 SSID/RSSI。
- **Input**：串口 `wifi scan` 输出。
- **Output**：AP 列表（RSSI<-70 只警告不判失败）。
- **Dependency**：wifi_check。
- **Forbidden Dependency**：不解析 IP。
- **Lifecycle**：单次执行。

## wifi_join

- **Responsibility**：连接 WiFi，异步等待拿到 IP。
- **Input**：ssid/password（来自 system.wifi）。
- **Output**：`ctx.evb_ip`。
- **Dependency**：wifi_scan。
- **Forbidden Dependency**：不负责 FTP/RTMP。
- **Lifecycle**：单次执行，成功后 sleep 等状态稳定。

## emmc

- **Responsibility**：验证可进入 `/emmc` 目录。
- **Input**：`cd /emmc` 命令。
- **Output**：无 error 即 PASS。
- **Dependency**：无。
- **Forbidden Dependency**：默认不格式化（`--format` 才 mkfs/mount）。
- **Lifecycle**：单次执行。

## ftp

- **Responsibility**：幂等启动 FTP 服务 + 建立连接验证。
- **Input**：`ctx.evb_ip`。
- **Output**：可用的 FTP 客户端（存入 ctx）。
- **Dependency**：wifi_join（需 evb_ip）。
- **Forbidden Dependency**：**全程只发一次 ftp_server**（重发触发固件崩溃）；**每次下载前重建连接**（不缓存复用）。
- **Lifecycle**：启动后长期 listen；会话 3s 空闲即断。

## photo

- **Responsibility**：遍历拍照模式，每拍一次验证产物。
- **Input**：photo_modes 参数。
- **Output**：串口 `Save Photo Successful`（主判据）。
- **Dependency**：ftp（需 FTP 客户端）。
- **Forbidden Dependency**：**不得写 for 循环重复**（重复由 Scenario 的 task.repeat 驱动）；不感知场景类型。
- **Lifecycle**：每模式一次动作；FTP 下载 JPEG 校验为辅助，失败降级不判 FAIL。

## video

- **Responsibility**：录一段视频并验证产物。
- **Input**：video_duration 参数。
- **Output**：串口 `Save Video Successful`（主判据）。
- **Dependency**：ftp。
- **Forbidden Dependency**：同 photo（不写循环、不感知场景）。
- **Lifecycle**：拍摄 + 下载校验；FTP 校验为辅助。

## rtmp

- **Responsibility**：发起推流、保持、验证流到达、停止。
- **Input**：pc_ip、stream_duration、heartbeat_timeout。
- **Output**：ffprobe 探到 h264+分辨率 且 heartbeat 无超时。
- **Dependency**：wifi_join（不依赖 ftp）。
- **Forbidden Dependency**：**不得在 rtmp_video_stop 之后才 ffprobe 探测**（探测的是实时流）。
- **Lifecycle**：start → 等上线 → 探测 → 保持+heartbeat → stop。

## rtmp_monitor

- **Responsibility**：订阅串口原始数据，独立做 heartbeat 检测。
- **Input**：串口原始数据（`add_listener`）。
- **Output**：heartbeat 超时事件。
- **Dependency**：串口层。
- **Forbidden Dependency**：**串口层只转发原始数据、不加业务逻辑**；monitor 不控制推流。
- **Lifecycle**：与 rtmp 推流同生命周期。
