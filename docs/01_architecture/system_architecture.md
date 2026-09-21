# 系统架构（System Architecture）

> 本文档描述系统分层与流转关系，是修改代码前必读。抽象描述，不含实现细节。

## 1. 分层模型

系统采用 **scenario 驱动的分层执行模型**，自上而下：

```
配置层    system.yaml + modules/*.yaml + scenarios/*.yaml
             │ 参数注入
编排层    ScenarioManager（prepare → tasks(loop) → cleanup）
             │ Task 列表
调度层    Runner（repeat / loop / 重试 / fail-fast）
             │ 逐个模块调用
模块层    wifi / emmc / ftp / photo / video / rtmp / utest（一次测试动作）
             │ 调用通信接口
通信层    SerialConsole（串口） / FtpClient / RtmpReceiver / PreviewManager / PowerSwitch
             │
硬件层    EVB 板（msh shell / FTP 服务 / RTMP 推流）+ 上下电控制模块（独立串口 115200）
```

- **上下电控制模块（ADR-015）**：新增一条与 EVB 主链路平行的系统边界 `PC →（串口 115200）→ 上下电控制模块 →（电源线）→ EVB`，提供「断电重启」能力。PowerSwitch 为 driver 能力（非测试模块），暴露 `power_on()/power_off()/reboot()` 被动接口，**不感知触发时机**（由独立模块 import 调用，单向依赖）。与 EVB 串口（2000000）靠「上电帧探测」区分防接反。已实施（devlog `20260921_1104`），**待真机验证**（控制器 115200 与 EVB 2000000 防接反、`reboot_delay` 电容放电值）。

- **PreviewManager**（ADR-010）是驱动层的观察能力，生命周期挂在 `prepare.preview_start`/`cleanup.preview_stop`（跨整个 Scenario，含 loop 多轮），不属任一 Task，不影响判据。

## 1.5 协议与判据分离（ADR-011，稳定约定）

> 与固件交互的「协议」（命令、判据、超时、正则、路径、枚举）与「业务逻辑」（怎么发、何时发、如何编排）**必须分离**。这是架构级稳定约定，**新增任何检测项/模块都必须遵守**。

- **协议唯一来源**：每模块新增 `ATS/drivers/<module>_commands.py`，只存协议常量（命令/判据/超时/正则/路径/枚举），**不写 IO、不写编排、不 import console/ftp/ctx**。
- **业务代码只 import 引用**：`modules/*.py` / `scenario_manager.py` 用 `commands.<CONST>` 引用，**不得内联协议字符串**。
- **命名规范**：
  - 命令 → `<ACTION>_COMMAND`（含 `{param}` 占位的用 `.format(...)` 拼，如 `RTMP_BITRATE_COMMAND = "cam_set live bitrate {bitrate}"`）
  - 判据 → `<ACTION>_EXPECT`；错误正则 → `<ACTION>_ERROR`
  - 超时 → `<ACTION>_TIMEOUT`（超时值也统一进 commands，**不得在业务侧写裸值**）
  - 路径 → `_XXX_DIR`；枚举/映射 → 不可变 `MappingProxyType`
- **可选能力**：可选项用「默认 0/空 → 不发送」的增量语义，业务侧 `if config.get(...)` 判断，不配置时行为与未加该能力前一致。
- **判据逻辑不迁**：计算型判据（如 ffprobe 的 codec/分辨率解析、H265 三阶段诊断）属驱动逻辑，保留在 `drivers/<validator>.py`，**不迁**入 `*_commands.py`。

详见 [ADR-011](../02_design/decision_record/ADR-011-串口协议集中化.md)。

## 2. 职责边界（架构约定，勿破坏）

| 层 | 职责 | 不负责 |
|----|------|--------|
| Scenario | 怎么组合测试（流程 / 循环 / 持续时间） | 不实现测试动作 |
| Runner | 什么时候执行（调度 / 重试 / fail-fast） | 不关心怎么测 |
| Module | 怎么测（一次测试动作 + 参数接口） | 不感知循环 / 场景 |
| Config | 参数是什么 | 不包含逻辑 |

## 3. 控制流

```
启动
 → 加载 scenario（system + modules + scenario 三层配置合并）
 → 执行 prepare 动作（串口初始化、WiFi 连接收敛、清理、FTP 就绪、preview 启动）
 → 按 loop 循环执行 tasks（每个 task 交给 Runner 调度到对应 Module）
 → 执行 cleanup 动作（停推流、关串口、preview 停止）
 → 生成报告，返回退出码
```

- **依赖关系（ADR-009）**：`depends` 字段只表达「运行时 task 间 fail-fast」（某 task FAIL/ERROR 时依赖它的 task SKIP）；**SKIP 不阻断依赖**（主动跳过不算失败）。当前三个场景均无 task 间依赖，模块代码 `depends` 已清空为 `[]`，逻辑依赖（如 photo 需 FTP、rtmp 需 WiFi）由 prepare 编排 + `module_design.md` 文档表达。
- 模块按 `scenario.tasks` **声明顺序**执行（不再拓扑排序）。
- **WiFi 属环境准备（prepare）而非测试项（task）**：`wifi_connect` 收敛器先检测、未连才 join（见 ADR-008）。
- **上下电控制生命周期（ADR-015）**：探测与串口长连接挂 `prepare`/`cleanup`（探测成功保持打开、存 ctx，cleanup 关闭），**不随单次 task 开关**；`enabled: false`（默认关）时零影响。

## 4. 数据流概览

- **串口流**：命令下行 → EVB 执行 → 响应上行 → 哨兵 / 正则解析
- **产物流**：拍照/录像 → EVB 落盘 `/emmc` → FTP 下载到 PC → 校验
- **推流流**：EVB 编码 → RTMP → PC nginx-rtmp → ffprobe 探测
- **电源控制流（ADR-015）**：PC →（串口 115200）→ 上下电控制模块 →（电源线）→ EVB（上电/下电/重启，协议字节在 `power_commands.py`，见 `data_flow.md`）

详见 [data_flow.md](data_flow.md)。
