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
| photo | 拍照并验证产物 | 串口 `Capture completed successfully.` | ✓ task |
| video | 录像并验证产物 | 串口 `Video recording completed successfully.` | ✓ task |
| rtmp | 推流并验证流到达 | ffprobe 探到 h264 + heartbeat 无超时 | ✓ task |
| rtmp_monitor | 订阅串口原始数据，检测推流 heartbeat | f_index 超时判异常 | 随 rtmp 运行 |
| string_hit_monitor | 订阅串口原始数据，检测配置选定的关键字符串 | 命中收集（不判 FAIL） | 随 video/rtmp 运行（ADR-014） |
| preview_manager | RTMP 画面观察（ffplay 单例），生命周期归 Scenario | is_running() | prepare.preview_start 启动，不作 task（ADR-010） |
| utest（模块组） | 跑一个固件 utest testcase，取框架 result 行 + per-case 业务关键串叠加判据 | result 行 PASSED + 业务串齐全 | 独立 `utest` 场景（ADR-012），8 个 `utest_<case>` task，不作 normal task |
| power_switch | 上下电控制能力（断电/上电/重启），被动接口 | 上电帧回 `A0 01 01 A2` | driver 能力，不作 task；由独立模块 import 调用（ADR-015，已实施·真机通过） |
| board_health_monitor | Scenario 生命周期级 EVB 健康监测，只观察判定、输出 HealthEvent | HEALTHY/SUSPECTED/UNRESPONSIVE 状态机 | application 服务，不作 task；挂 prepare.health_monitor_start（ADR-016，已实施·运行时闭环已修复·待真机） |
| recovery_coordinator | 消费健康状态，决策恢复策略、协调恢复流程 | 状态机 IDLE→…→HEALTHY | application 服务，不作 task；只认 RecoveryBackend 统一接口（ADR-016，已实施·运行时闭环已修复·待真机） |
| recovery_backend | 把统一 recover() 请求适配到具体恢复能力 | `available(ctx)`/`recover(ctx)` | application 服务；首实现 PowerCycleBackend 映射到 PowerSwitch.reboot()（ADR-016，已实施·运行时闭环已修复·待真机） |

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
- **Output**：串口 `Capture completed successfully.`（主判据，相机日志全部打印完的完成标志）。
- **Dependency**：逻辑依赖 FTP 就绪（需 FTP 客户端），由 prepare.ftp_ready 保证；代码 `depends=[]`。
- **Forbidden Dependency**：**不得写 for 循环重复**（重复由 Scenario 的 task.repeat 驱动）；不感知场景类型。
- **Lifecycle**：每模式一次动作；FTP 下载 JPEG 校验为辅助，失败降级不判 FAIL。

## video

- **Responsibility**：录一段视频并验证产物。
- **Input**：video_duration 参数。
- **Output**：串口 `Video recording completed successfully.`（主判据，录像全流程走完的最终完成标志；`Save Video Successful: <path>` 出现更早且路径会被串口分块截断，路径应从累积缓冲扫描）。
- **Dependency**：逻辑依赖 FTP 就绪，由 prepare.ftp_ready 保证；代码 `depends=[]`。
- **Forbidden Dependency**：同 photo（不写循环、不感知场景）。
- **Lifecycle**：拍摄 + 下载校验；FTP 校验为辅助。
- **关键字符串检测（ADR-014）**：读 `detect_strings`（modules yaml 选择键列表），逐个实例化 `StringHitMonitor` 订阅串口，命中只追加 detail、不判 FAIL；定义唯一来源在 `drivers/detect_strings.py`。

## rtmp

- **Responsibility**：发起推流、保持、验证流到达、停止。**不负责画面展示**（ADR-010：ffplay 已剥离到 preview_manager）。
- **Input**：pc_ip、stream_duration、heartbeat_timeout、bitrate（可选，0=不设置）、detect_strings（可选，未配置则不检测）。
- **Output**：ffprobe 探到 h264+分辨率 且 heartbeat 无超时。
- **Dependency**：逻辑依赖 WiFi 就绪，由 prepare.wifi_connect 保证；不依赖 FTP；代码 `depends=[]`。
- **Forbidden Dependency**：**不得在 rtmp_video_stop 之后才 ffprobe 探测**（探测的是实时流）；**不得启动 ffplay 或管理播放器进程**（ADR-010，属 preview_manager 职责）。
- **运行依赖**：本模块判据依赖 `ffprobe` 可执行（属运行依赖，**仓库不随附** `tools/ffmpeg/`，需自行安装或拷贝，见 `05_handoff/build_environment.md`）。
- **Lifecycle**：start → 等上线 → 探测 → 保持+heartbeat → stop。可选：start 之前若 `bitrate>0` 先发 `cam_set live bitrate`（协议在 `rtmp_commands.py`）。
- **关键字符串检测（ADR-014）**：读 `detect_strings`（modules yaml 选择键列表），逐个实例化 `StringHitMonitor` 订阅串口，命中只追加 detail、不判 FAIL；定义唯一来源在 `drivers/detect_strings.py`。

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

## string_hit_monitor（ADR-014）

- **Responsibility**：订阅串口原始数据，按配置选定的关键字符串做命中收集（不判 FAIL，只追加 `TestResult.detail`）。
- **Input**：串口原始数据（`add_listener`）+ `DetectString`（pattern/label）。
- **Output**：命中文本列表（去 ANSI、跨 chunk 字面串拼接还原）。
- **Dependency**：串口层；检测串定义唯一来源在 `drivers/detect_strings.py`。
- **Forbidden Dependency**：**不做 status 判定**（不判 PASS/FAIL/ERROR）；**不内联检测串**（pattern 从 `DetectString` 传入）。
- **Lifecycle**：与 video/rtmp 检测窗口同生命周期；由 `detect_strings` 配置（未配置则不实例化）。

## utest（ADR-012，每 case 一模块）

> 2026-09-17 演进：由「单模块 utest + `override.testcase` 分派」改为「每 case 一模块（8 个 `utest_<case>`）+ 叠加判据」，见 ADR-012 修订记录与需求稿 `新增需求_utest细粒度判据.md`。

- **Responsibility**：跑一个固件 utest testcase，取框架 result 行（主判据）+ per-case 业务关键串（补充校验）作**叠加判据**（固件已汇总，脚本不扫 unit 级业务输出，但 result 行 PASSED 后仍校验业务串是否齐全）。
- **Input**：testcase 名**内置模块**（无需 `override.testcase`）+ 可选 `timeout` 覆盖；`flash_xip_speed` 另有 `min_speed_kbs` 速率阈值（默认 0 不校验）。
- **Output**：result 行 `FAILED/ERROR/SKIPPED` → FAIL/ERROR/SKIP（业务串不反向救回）；result 行 `PASSED` + 业务串齐全 → PASS，业务串缺失/不符 → FAIL（detail 列缺失串）；无 result 行 → FAIL。
- **Dependency**：仅串口（prepare 的 `serial_init`）；**不依赖 WiFi/FTP/preview**。utest 固件 msh 提示符为 `msh >`（无斜杠），串口探测依赖 ADR-013 的 `serial_fingerprint: utest` 场景声明。
- **Forbidden Dependency**：**不扫 `fail`/`error` 关键字**（`qspi_test` 的 `1 lane fail!`、`filesystem` 的 `not a mountpoint!` 是合法中间态，必须显式传 result 行 expect 避开 serial_console 默认 `_ERROR_RE`）；**不写 for**（跑哪些 case 由 scenario 逐项声明）；**不并入 normal/stress/aging**（独立 `utest` 场景）。
- **协议**：命令/判据/超时映射唯一来源在 `ATS/drivers/utest/`（`_common.py` 公共 + `<case>_commands.py` 每 case 的 TESTCASE/BUSINESS_RES），业务只 import 引用（ADR-011）。
- **结构**：`modules/utest/base.py` 收敛叠加判据模板（`UtestCaseModule`），8 个子类（`utest_efuse`/`utest_filesystem`/`utest_i2c`/`utest_imu`/`utest_pvt_auto`/`utest_pvt`/`utest_flash_xip_speed`/`utest_flash_read`）只设 testcase + business_res 常量；`qspi_test` 本期不建模块（D6），超时映射保留。
- **Lifecycle**：一次动作 = `exec_sync(utest_run <name>)` 跑一个 testcase，8 项由 scenario 驱动。FAILED/ERROR/SKIPPED 的 result 行确切格式暂无实测样本，状态枚举已预留接口，未知状态走 `_error` 兜底。

## power_switch（ADR-015，上下电控制 driver 能力）

- **Responsibility**：通过独立串口控制上下电控制模块，对 EVB 板执行下电/上电/重启。**是环境/能力，不是测试动作**，不作 task。
- **Input**：控制器串口（115200）+ `power_switch` 配置（enabled/baudrate/reboot_delay）。
- **Output**：上电帧回 `A0 01 01 A2`（ON）为成功判据；`reboot()` = 下电 → 延时 → 上电。
- **Dependency**：逻辑依赖独立串口已探测成功；代码单向被 import，**禁止反向 import 触发模块**（触发时机由另一独立模块决策）。
- **Forbidden Dependency**：**不感知「何时触发重启」**（只提供 `power_on/power_off/reboot` 被动接口）；**不写协议字节**（唯一来源 `drivers/power_commands.py`，ADR-011）；**不复用 `detect_port`/`serial_init` 顺带识别控制器**（探测完全独立）。
- **端口区分**：启用时对候选串口按 115200 发上电帧，回 `A0 01 01 A2` 者 = 控制器，另一 = EVB（防接反）；`detect_port` 仍按 EVB 指纹找板子，互不干扰。
- **Lifecycle**：prepare `power_switch_init` 探测（enabled 时，候选端口 = 全部可访问串口 减去 EVB 端口），成功保持打开存 `ctx.power_switch`；cleanup `power_switch_close` 关闭；`enabled: false`（默认）时不探测、零影响。已实施（devlog `20260921_1104`），真机通过（TC-PS-001 压测 PASS）。

## board_health_monitor（ADR-016，Scenario 生命周期级健康监测，已实施·运行时闭环已修复·待真机）

- **Responsibility**：监听 EVB 串口活动、记录最后有效 RX 时间、检测长时间无活动、维护 `HEALTHY/SUSPECTED/UNRESPONSIVE` 状态、保存证据、请求进一步健康确认。**只观察判定，不处理**。
- **Input**：串口原始数据（`SerialConsole.add_listener()`）+ `config/modules/board_health.yaml` 参数（check_interval/inactivity_timeout/confirm_failures/confirm_interval）。
- **Output**：`HealthEvent`（含 health_state、reason、证据）。
- **Dependency**：串口层（listener）；配置来自 modules/board_health.yaml。
- **Forbidden Dependency**：**禁止**直接调用 PowerSwitch、power_on/power_off/reboot、决定是否重启、决定 Task 是否重跑、恢复 WiFi/FTP、修改 Scenario。listener 回调中**禁止** sleep/exec_sync/exec_async/PowerSwitch/FTP/网络 IO 等阻塞操作。
- **状态机**：`HEALTHY →（超 inactivity_timeout）→ SUSPECTED →（主动 health_check 连续失败 confirm_failures 次）→ UNRESPONSIVE`。UNRESPONSIVE 只表示 ATS 无法通过 EVB 控制链路取得有效响应，不推断根因。
- **Lifecycle**：Scenario 生命周期能力，挂 `prepare.health_monitor_start` / `cleanup.health_monitor_stop`，非 Task（不建 `modules/board_health.py`）。

## recovery_coordinator（ADR-016，恢复协调器，已实施·运行时闭环已修复·待真机）

- **Responsibility**：接收 BoardHealthMonitor 状态、防重复恢复、统计恢复次数、按 Scenario Recovery Policy 选择 RecoveryBackend、暂停/恢复监测、失效板端运行状态、执行恢复、等待 EVB ready、恢复环境、通知 Runner 恢复结果、决定 retry 或 abort。
- **Input**：`HealthEvent` + Scenario Recovery Policy（`recovery.backend/max_attempts/after_recovery/on_exhausted/restore`）。
- **Output**：恢复结果 + `ctx.recovery_history` 记录。
- **Dependency**：逻辑依赖 RecoveryBackend 统一接口（`backend.recover()`）；复用现有 prepare action 做环境收敛（不复制第二套 Recovery WiFi/FTP 逻辑）。
- **Forbidden Dependency**：**不负责**健康判据本身、PowerSwitch 二进制协议、具体上下电实现、photo/video/rtmp 业务逻辑；不直接依赖 PowerSwitch。
- **状态机**：`IDLE → REQUESTED → RECOVERING → RECONCILING → HEALTHY`（失败进 FAILED）；`recovery_in_progress` 互斥，同一时间只允许一个恢复流程。
- **Lifecycle**：由 Runner 在 recovery checkpoint 调用；推荐位置 `ATS/application/recovery_coordinator.py`。

## recovery_backend（ADR-016，恢复后端抽象，已实施·运行时闭环已修复·待真机）

- **Responsibility**：把统一 `recover()` 请求适配到某一种具体恢复能力。
- **Input**：`ctx`。
- **Output**：`available(ctx)` 判断能力是否可用；`recover(ctx)` 执行恢复。
- **Dependency**：首实现 `PowerCycleBackend` 内部映射到 `ctx.power_switch.reboot()`（复用 ADR-015，PowerSwitch 原职责不变）。
- **Forbidden Dependency**：不决定何时恢复（由 Coordinator 决策）；不支持静默 fallback（能力不可用时报 `RecoveryBackendUnavailable`）。
- **Lifecycle**：推荐位置 `ATS/application/recovery_backends/`（base.py + power_cycle.py）；未来可扩展 SoftReset/NetworkPdu/UsbRelay/Manual 等 Backend，无需改 Monitor/Runner/业务模块。
