# 模块设计（Module Design）

> 每个模块的职责边界。修改模块前先读本表，确认「该模块负责什么、不该负责什么」。
>
> **WiFi 职责重划（ADR-008）**：WiFi 不再作为 normal 独立测试项。`wifi_check` 是「状态检测器」，由 prepare 的 `wifi_connect` 收敛器内部调用；`wifi_scan`/`wifi_join` 退出 normal 默认流程，模块代码保留可复用。
>
> **depends 字段语义（ADR-009）**：模块代码里 `depends = []`（已清空死依赖）。`depends` 字段只表达「运行时 task 间 fail-fast」；「逻辑依赖」（谁需要谁的前置环境）由 Scenario 的 prepare 编排保证，并记录在本文件各模块的 Dependency 描述中。

## 模块职责总览

| 模块 | 职责 | 成功判据 | normal 流程 |
|------|------|---------|------------|
| wifi_check | **状态检测器**：ifconfig 检测是否已联网 | 有非 0.0.0.0 IP | 由 prepare 调用，不作 task |
| wifi_scan | 扫描附近 WiFi AP | 表头 + ≥1 行数据 | 退出默认流程（保留代码） |
| wifi_join | 连接指定 WiFi | `Got IP address : <IP>` | 退出默认流程（保留代码） |
| emmc | 进入 eMMC 目录 | `cd /emmc` 无 error | ✓ task |
| ftp | 启动 FTP 服务 + 连接验证 | 列出 `/emmc` 成功 | prepare.ftp_ready 保证 |
| photo | 拍照并验证产物 | 串口 `Save Photo Successful` | ✓ task |
| video | 录像并验证产物 | 串口 `Save Video Successful` | ✓ task |
| rtmp | 推流并验证流到达 | ffprobe 探到 h264 + heartbeat 无超时 | ✓ task |
| rtmp_monitor | 订阅串口原始数据，检测推流 heartbeat | f_index 超时判异常 | 随 rtmp 运行 |
| preview_manager | RTMP 画面观察（ffplay 单例），生命周期归 Scenario | is_running() | prepare.preview_start 启动，不作 task（ADR-010） |

---

## wifi_check（状态检测器）

- **Responsibility**：检测当前板子是否已满足网络环境要求（`ifconfig` 有无非 0.0.0.0 IP）。
- **Input**：串口 `ifconfig` 输出。
- **Output**：`ctx.evb_ip`（已联网时）+ `ctx.wifi_ready`（True/False）。
- **Dependency**：无。
- **Forbidden Dependency**：**不 scan / join / 改配置**（只检测）。
- **Lifecycle**：被 prepare 的 `wifi_connect` 收敛器内部调用，不作为独立 task。

## wifi_scan

- **Responsibility**：扫描 AP，解析 SSID/RSSI（保留，供手动调试 / 未来场景）。
- **Input**：串口 `wifi scan` 输出。
- **Output**：AP 列表（RSSI<-70 只警告不判失败）。
- **Dependency**：逻辑依赖 wifi_check（已联网状态），由 prepare.wifi_connect 收敛器内部保证；代码 `depends=[]`。
- **Forbidden Dependency**：不解析 IP。
- **Lifecycle**：退出 normal 默认流程，模块代码保留。

## wifi_join

- **Responsibility**：连接 WiFi，异步等待拿到 IP（保留，供手动调试 / 未来场景）。
- **Input**：ssid/password（来自 system.wifi）。
- **Output**：`ctx.evb_ip`。
- **Dependency**：逻辑依赖 wifi_scan（AP 列表），退出 normal 默认流程；代码 `depends=[]`。
- **Forbidden Dependency**：不负责 FTP/RTMP。
- **Lifecycle**：退出 normal 默认流程；收敛器 `wifi_connect` 内部实现「未联网才 join」的逻辑。

## prepare.wifi_connect（状态收敛器）

- **Responsibility**：确保测试开始前 WiFi 一定达到可用状态。
- **逻辑**：先 wifi_check 检测 → 已联网则保留状态；未联网则执行 join → 最终设 `ctx.evb_ip`。
- **Forbidden Dependency**：不做 WiFi 的「测试判定」，只做「状态收敛」。

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
- **Dependency**：逻辑依赖 WiFi 就绪（需 evb_ip），由 prepare.wifi_connect 保证；代码 `depends=[]`。
- **Forbidden Dependency**：**全程只发一次 ftp_server**（重发触发固件崩溃）；**每次下载前重建连接**（不缓存复用）。
- **Lifecycle**：启动后长期 listen；会话 3s 空闲即断。

## photo

- **Responsibility**：遍历拍照模式，每拍一次验证产物。
- **Input**：photo_modes 参数。
- **Output**：串口 `Save Photo Successful`（主判据）。
- **Dependency**：逻辑依赖 FTP 就绪（需 FTP 客户端），由 prepare.ftp_ready 保证；代码 `depends=[]`。
- **Forbidden Dependency**：**不得写 for 循环重复**（重复由 Scenario 的 task.repeat 驱动）；不感知场景类型。
- **Lifecycle**：每模式一次动作；FTP 下载 JPEG 校验为辅助，失败降级不判 FAIL。

## video

- **Responsibility**：录一段视频并验证产物。
- **Input**：video_duration 参数。
- **Output**：串口 `Save Video Successful`（主判据）。
- **Dependency**：逻辑依赖 FTP 就绪，由 prepare.ftp_ready 保证；代码 `depends=[]`。
- **Forbidden Dependency**：同 photo（不写循环、不感知场景）。
- **Lifecycle**：拍摄 + 下载校验；FTP 校验为辅助。

## rtmp

- **Responsibility**：发起推流、保持、验证流到达、停止。**不负责画面展示**（ADR-010：ffplay 已剥离到 preview_manager）。
- **Input**：pc_ip、stream_duration、heartbeat_timeout。
- **Output**：ffprobe 探到 h264+分辨率 且 heartbeat 无超时。
- **Dependency**：逻辑依赖 WiFi 就绪，由 prepare.wifi_connect 保证；不依赖 FTP；代码 `depends=[]`。
- **Forbidden Dependency**：**不得在 rtmp_video_stop 之后才 ffprobe 探测**（探测的是实时流）；**不得启动 ffplay 或管理播放器进程**（ADR-010，属 preview_manager 职责）。
- **运行依赖**：本模块判据依赖 `ffprobe` 可执行（属运行依赖，**仓库不随附** `tools/ffmpeg/`，需自行安装或拷贝，见 `05_handoff/build_environment.md`）。
- **Lifecycle**：start → 等上线 → 探测 → 保持+heartbeat → stop。

## preview_manager（ADR-010）

- **Responsibility**：管理 ffplay 单例，观察 EVB 实时 RTMP 流（延时/首帧/卡顿/推流恢复），观察能力而非测试能力。
- **Input**：`ctx.pc_ip` + `rtmp.yaml.stream_url` 模板推导出的观看地址；`config/modules/preview.yaml` 播放器参数。
- **Output**：`is_running()` 状态；异常仅在 `preview_required: true` 时才影响整体结果。
- **Dependency**：逻辑依赖 nginx-rtmp 就绪（`RtmpServer.check_ready()`）+ WiFi 就绪；由 `prepare.preview_start` 保证。
- **运行依赖**：观察需 `ffplay` 可执行（属运行依赖，**仓库不随附** `tools/ffmpeg/`，需自行安装或拷贝，见 `05_handoff/build_environment.md`）；不可用时跳过画面观察，不影响判据。
- **Forbidden Dependency**：**不得由 video.py/rtmp.py 创建或持有**；**不得每轮 loop 重新实例化**（Scenario 生命周期内单例，start 内部自带断流重连 wrapper）。
- **Lifecycle**：`prepare.preview_start` 启动 → 跨整个 Scenario（含 loop 多轮 tasks）保持 → `cleanup.preview_stop` 关闭。存于 `ctx.preview_manager`。

## rtmp_monitor

- **Responsibility**：订阅串口原始数据，独立做 heartbeat 检测。
- **Input**：串口原始数据（`add_listener`）。
- **Output**：heartbeat 超时事件。
- **Dependency**：串口层。
- **Forbidden Dependency**：**串口层只转发原始数据、不加业务逻辑**；monitor 不控制推流。
- **Lifecycle**：与 rtmp 推流同生命周期。
