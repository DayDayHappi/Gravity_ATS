# RTMP 推流持续性检测：heartbeat 机制 + 独立 RTMPMonitor 模块

**日期**: 2026-08-20
**改动范围**: `modules/rtmp_monitor.py`（新增）、`modules/rtmp.py`（接入持续检测）、
`core/serial_console.py`（新增原始数据订阅 listener）、`config/test_config.yaml`（新增 `heartbeat_timeout`）

---

## 一、问题描述

当前 RTMP 测试只能验证「能否成功启动」，不能验证「整个测试周期内是否持续稳定运行」。

实测出现误判：板端 02:13 启动推流 → 02:14 推流异常停止（ImuThread 崩溃）→ ffplay 画面冻结，
但脚本**未发现异常**，继续 `sleep()` 干等剩余测试时间，直到 10 分钟结束 → **实际推流失败、结果却 PASS**。

## 二、根因分析

旧流程 `start → ffprobe 检测一次 → sleep(600) → stop` 里，ffprobe 只在**推流开始 10s 左右探测一次**，
探到即 PASS；之后的 `sleep(duration)` 是**盲等**，没有任何运行状态感知，板端中途崩溃无人察觉。

## 三、修复内容

### 3.1 新增 `modules/rtmp_monitor.py`（独立检测模块）

`RTMPMonitor` 类，职责单一：**只分析 RTMP 运行状态，不碰串口/不写文件/不判 PASS/FAIL**。

- **heartbeat 依据**：板端推流期间的 `[RTMP] f_index = N, f_len = M` 日志（代表「编码完成 + 发送流程运行」，
  即 RTMP 线程仍工作）。实测正常推流约每 2~4s 一条。
- **状态维护**：每收到 heartbeat 刷新 `last_frame_time`。
- **超时检测**：`check_timeout()` 判断 `now - last_frame_time > timeout`（默认 30s），超时置 `TIMEOUT`。
- **接口**：`start() / update(text) / check_timeout() / get_status() / stop()`。
- **正则精确匹配**：`\[RTMP\]\s+f_index\s*=`，严格区分推流的 `[RTMP] f_index` 与录像的
  `[App Dfs] f_index`，不会把录像日志误当 RTMP heartbeat。

### 3.2 `core/serial_console.py`（串口层只加"原始数据订阅"，不加业务逻辑）

新增 `add_listener(callback)` / `remove_listener(callback)`：

- 读线程收到串口数据后，除「写 serial.log + 喂缓冲」外，把**原始文本**转发给所有 listener。
- listener 异常被吞掉，不影响串口主流程。
- 串口层**不感知 RTMP**，只负责「转发原始数据」——符合"Serial 层保持纯净"原则。

### 3.3 `modules/rtmp.py`（接入持续检测）

保持阶段从盲等 `sleep(duration)` 改为 **heartbeat 持续检测循环**：

- 探测到流后 `monitor.start()` + `console.add_listener(monitor.update)`；
- 循环内每 1s `check_timeout()`，超时即 `break`（不再干等剩余时长），每 30s 打进度；
- `finally` 里 `remove_listener` + `monitor.stop()`（异常路径由 teardown 兜底移除）。
- **判据合并**：ffprobe 探测到流（主判据）**且** 无 heartbeat timeout 才 PASS；
  timeout 则 FAIL，`TestResult.detail` 写入结构化 Monitor Result（Status/Reason/Start/LastFrame/Timeout/Duration/FrameCount），供 report 展示。

### 3.4 `config/test_config.yaml`

`rtmp` 段新增 `heartbeat_timeout: 30`（默认 30s，初版 5s 过极端，板端关键帧稀疏时 f_index 间隔会拉长，易误判，故放宽到 30s）。

## 四、验证结果

- `python3 -m py_compile` 语法检查通过（serial_console.py / rtmp.py / rtmp_monitor.py）。
- `RTMPMonitor` 逻辑单测通过：
  - 正常推流（每 3s 一条 f_index）→ `ALIVE`，帧数正确计数；
  - 推流中途停止（超时无 f_index）→ `TIMEOUT`，reason 正确；
  - `[App Dfs] f_index`（录像）不触发 RTMP heartbeat（帧数 0）。
- **崩溃案例回放验证**：`logs/20260819_031823` 中最后一条 `[RTMP] f_index = 5310` 在 `03:28:08.701`，
  ImuThread 崩溃在 `03:28:13.058`，之后 f_index 停止——**30s 超时能捕捉到崩溃**，与预期一致。
- **待真机验证**：跑含 rtmp 的完整测试，人为制造板端推流中断（或观察自然崩溃），确认脚本在
  30s 内判 FAIL 并提前停止，report 里能看到 RTMP Monitor Result。

## 五、还会再有吗

- **heartbeat 只覆盖「板端编码/发送线程存活」**，无法检测「网络传输中断但板端仍在编码」的场景
  （此时 `[RTMP] f_index` 仍持续，但 ffprobe 已收不到数据）。规格文档异常分类里的"类型2 网络异常"
  尚未实现，需在后续用「周期 ffprobe 复探」或「ffplay 状态」补充检测。当前已覆盖最核心的
  "类型1 板端 RTMP 停止"。
- **阈值可调**：`heartbeat_timeout: 30` 默认值——初版定 5s 过于极端，实测正常推流 f_index 虽约
  2~4s 一条，但板端编码变慢（关键帧稀疏）时间隔会拉长到数秒甚至更久，5s 易误判；放宽到 30s
  在"及时发现异常"与"容忍正常抖动"之间取平衡。若真机仍误判/漏报，再结合结果微调。
- **listener 线程安全**：`update()` 只在读线程调用（正则匹配 + 标量赋值，极轻量），
  `check_timeout()` 在测试主线程调用，读的是单调标量，无共享可变状态竞争。

## 六、经验沉淀

- **"启动成功" ≠ "持续稳定"**：长时间压测场景必须加运行状态心跳检测，否则盲等 sleep 会把
  中途崩溃误判成 PASS。判据应从"点"（启动探测一次）升级到"线"（全程心跳）。
- **检测逻辑要模块化、串口层保持纯净**：串口层只做「转发原始数据」这一件事，通过 listener
  机制把数据喂给独立检测模块，RTMP 判断不侵入 serial/console，符合"高内聚、低耦合"。
- **heartbeat 选板端已有日志、不新增协议**：复用 `[RTMP] f_index` 这种板端本就周期性打印的日志
  作心跳，零改动板端固件、零新增命令，最省事也最可靠。选 heartbeat 时优先找"代表业务线程仍在工作"的周期性日志。
