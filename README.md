# Gravity ATS

**面向 VX100 EVB 的场景驱动自动化测试框架。**

Gravity ATS 在 PC 端通过串口控制开发板，通过 FTP 获取拍照和录像产物，通过 Nginx RTMP 与 FFmpeg 工具验证视频链路，并统一输出测试日志与报告。测试流程由 YAML 配置，普通测试、压力测试和老化测试复用同一套功能模块。

> 本文面向 `new_arch` 分支的 Ubuntu / Linux 命令行使用方式。功能与配置说明按 2026-09-23 源码快照整理；具体参数以检出版本的源码和 YAML 为准。Windows CLI 与 GUI 迁移不作为本文所述主线版本的已验收能力。

[背景与用途](#背景与用途) · [功能概览](#功能概览) · [工程架构](#工程架构) · [依赖与安装](#依赖与安装) · [首次运行](#首次运行) · [场景与配置](#场景与配置) · [日志与报告](#日志与报告) · [使用边界](#使用边界) · [文档导航](#文档导航)

## 背景与用途

嵌入式开发板的功能验证通常需要反复执行串口命令、连接网络、拍照、录像、观察推流，再人工收集日志和检查文件。测试次数增加后，手动操作难以保持一致，异常发生时也容易缺少对应的命令、运行轮次和产物记录。

Gravity ATS 将这些重复操作组织成可配置的测试场景：由框架完成环境准备、任务执行、循环调度和收尾，再将结果与诊断信息集中保存。测试人员可以调整测试组合、执行次数、录像时长和检测选项，而不必为每一种测试流程重新编写脚本。

工程主要用于固件功能回归、拍照与录像参数遍历、RTMP 稳定性观察、长时间压力与老化测试、板端 UTest 自检，以及本地 H.265 文件的解码和参考链异常诊断。它是面向已适配固件的上位机测试工具，不是任意开发板都能直接使用的通用烧录或测试平台。

## 功能概览

下表说明当前代码提供的能力，不代表所有固件版本、硬件组合和参数组合均已完成真机验收。

| 能力 | 当前实现 |
| --- | --- |
| 场景编排 | YAML 定义 `prepare → tasks → cleanup`；支持任务重复、整轮循环、限时循环和模块参数覆盖。 |
| 串口通信与调试 | 自动探测或显式指定串口；配置波特率；同步命令与异步完成标志等待；持续采集串口日志；提供交互式串口终端。 |
| WiFi 与 FTP 环境准备 | 在场景准备阶段连接 WiFi、取得板端 IP、启动 FTP 服务并准备客户端；下载链路支持重连与断点续传。 |
| eMMC 检查 | 验证板端 `/emmc` 目录访问；默认不格式化，格式化需要显式启用。 |
| 拍照测试 | 配置拍照模式和执行次数；等待固件最终完成标志；可启用 FTP 下载及 JPEG 文件头、大小辅助检查，也可只拍摄不下载。 |
| 录像与 size 遍历 | 通过完整命令 profile 选择录像组合；每个组合独立配置次数与时长；等待启动和最终完成标志；可下载录像并辅助校验文件大小。 |
| RTMP 推流验证 | 检查 Nginx RTMP 就绪；使用 `ffprobe` 探测视频流；以板端 `f_index` 日志进行心跳超时检测；支持可选码率配置。 |
| 推流画面观察 | `PreviewManager` 在场景生命周期内管理 `ffplay`，支持跨测试轮次复用和断流后重连；默认不将人工预览作为测试主判据。 |
| H.265 完整性诊断 | 独立的 `video_integrity` 模块检测当前运行产物或指定本地目录；解码失败后按配置执行 `showinfo` 和 `trace_headers` 诊断。 |
| 板端 UTest 自检 | 独立模块覆盖 eFuse、文件系统、I²C、IMU、PVT、PVT 自动测试、Flash XIP 速度和 Flash 读取，按各项固件输出判定。 |
| 关键字符串记录 | 录像与推流期间按配置检测 `tt_error`、`imu_fmq_overflow` 等关键词，记录到结果详情；命中本身不自动判定 FAIL。 |
| 板卡健康与恢复 | 可选健康监测、主动响应确认和串口电源控制；专用恢复场景支持 PowerCycle、串口重连、环境重建及当前任务重跑。 |
| 日志与报告 | 输出运行日志、EVB 串口日志，以及 JSON / JUnit XML / HTML 报告；记录场景轮次和任务重复序号，按场景、日期、运行时间分层保存。 |

具体模块与场景可通过以下命令查看：

```bash
python -m ATS.main --list-modules
python -m ATS.main --list-scenarios
```

功能实现入口：[业务模块](ATS/modules/) · [驱动与协议](ATS/drivers/) · [场景配置](ATS/config/scenarios/) · [健康监测与恢复](ATS/application/)

## 工程架构

### 总体设计

<p align="center">
  <img src="assets/readme/architecture.png" alt="Gravity ATS 工程架构总览" width="900">
</p>

| 层次 | 职责 | 主要位置 |
| --- | --- | --- |
| CLI 入口 | 解析命令行参数、选择场景、检查依赖、组织输出目录。 | `ATS/main.py` |
| 场景层 | 声明测试组合、准备与清理动作，以及整轮循环策略。 | `ATS/config/scenarios/`、`ATS/core/scenario_manager.py` |
| 执行层 | 按声明顺序执行任务，处理 `repeat`、`loop`、参数覆盖和执行结果。 | `ATS/core/runner.py` |
| 功能模块层 | 实现拍照、录像、推流、文件检测、UTest 等具体测试动作。 | `ATS/modules/` |
| 驱动与协议层 | 集中维护串口命令与判据，封装 FTP、FFmpeg、预览和电源控制。 | `ATS/drivers/` |
| 应用协调层 | 协调板卡健康状态、恢复策略及运行时等待；与具体测试任务分离。 | `ATS/application/` |
| 公共基础设施 | 配置加载、共享上下文、串口采集、日志和报告。 | `ATS/core/` |

**普通测试和压力测试复用同一套 `photo`、`video`、`rtmp` 模块。** 测试次数与流程由场景和 Runner 调度，不另建 `photo_stress`、`video_stress` 等重复实现。录像命令组合集中在 `drivers/video_commands.py`，不在场景或业务发送逻辑中重复拼接。

### 执行流程

<p align="center">
  <img src="assets/readme/workflow.png" alt="Gravity ATS 测试执行流程" width="900">
</p>

场景运行分为环境准备、任务执行和清理三个阶段。WiFi 连接、FTP 服务准备、预览启动等属于 `prepare`；拍照、录像、推流和文件检测属于 `tasks`；资源关闭与兜底停止属于 `cleanup`。不同场景只声明自身需要的动作。

健康监测与恢复属于场景生命周期中的系统级能力，不是要求每个业务模块自行执行的重启逻辑。以 PowerCycle 恢复为例，电源控制负责上下电，恢复协调器负责串口重连、等待板卡就绪和环境重建，Runner 根据恢复结果决定重跑或中止。

### 目录结构

以下为主要维护目录，省略各层中的具体实现文件：

```text
Gravity_ATS/
├── README.md                         # 仓库首页：项目介绍与使用入口
├── assets/readme/                    # 首页使用的架构图与流程图
│   ├── architecture.png
│   └── workflow.png
├── ATS/
│   ├── main.py                       # CLI 主入口
│   ├── README.md                     # 模块使用说明，部分章节保留历史内容
│   ├── application/                  # 健康监测、恢复协调、运行时控制
│   │   └── recovery_backends/        # 可插拔恢复后端，当前提供 PowerCycle
│   ├── config/
│   │   ├── system.yaml               # 串口、WiFi、PC 地址、报告等系统环境
│   │   ├── modules/                  # 各模块的默认能力参数
│   │   └── scenarios/                # 场景流程、任务组合、循环与覆盖参数
│   ├── core/                         # 场景管理、Runner、串口、上下文、日志、报告
│   ├── drivers/                      # 设备协议及 PC 端工具封装
│   │   └── utest/                    # 各 UTest 项的命令、判据与超时定义
│   ├── modules/                      # 可复用测试模块
│   │   └── utest/                    # 每个 UTest case 对应的独立模块
│   └── tools/                        # 串口终端等辅助工具
├── docs/
│   ├── README.md                     # 文档导航
│   ├── 00_project/                   # 项目总览、术语、路线图
│   ├── 01_architecture/              # 架构、接口、模块设计、数据流
│   ├── 02_design/decision_record/    # 架构决策记录 ADR
│   ├── 03_development/               # 开发日志、问题修复及历史资料
│   ├── 04_testing/                   # 测试策略与用例
│   └── 05_handoff/                   # 环境、当前状态、已知问题和交接
├── tests/                            # 工程测试代码
├── .claude/                          # Agent 协作资料，不是运行依赖
├── CLAUDE.md                         # 工程协作约定
├── export_source.py                  # 源码快照导出工具
└── .gitignore                        # Git 忽略规则
```

`.venv/`、`logs/`、`reports/` 属于本地环境或运行产物，不应作为使用工程前必须从 GitHub 下载的内容。根目录可选的 `tools/ffmpeg/` 是本地工具存放位置，与已跟踪的 `ATS/tools/` 不是同一个目录。源码树中的 `ATS/gui/`、`ATS/platform/` 预留目录也不等同于已经交付的 GUI 或跨平台支持。

## 依赖与安装

### 依赖工具

| 依赖 | 用途 | 是否需要 |
| --- | --- | --- |
| Python 3 | 运行 ATS；使用独立 `.venv` 管理 Python 包。 | 必需 |
| `pyserial` | 主机串口通信。 | 必需 |
| `PyYAML` | 读取系统、模块和场景 YAML。 | 必需 |
| `Jinja2` | 渲染 HTML 报告模板。 | 建议安装 |
| `ffmpeg` | 本地 H.265 解码、定位与码流诊断。 | 执行视频完整性检测时需要 |
| `ffprobe` | 探测 RTMP 视频流的编码和分辨率。 | 执行 RTMP 测试时需要 |
| `ffplay` | 实时画面观察。 | 可选；需要可用桌面显示环境 |
| Nginx + `libnginx-mod-rtmp` | 接收板端 RTMP 推流并向主机播放器、探测器提供流。 | 执行 RTMP 测试时需要 |
| Git | 克隆和更新工程。 | 源码管理需要 |
| `pytest` | 执行工程开发测试。 | 开发时按需安装，不是 CLI 运行前置 |

本分支的命令行运行不要求安装 Qt、PySide6、PyQt 或 PyInstaller。板端应运行已适配的固件，提供对应的 msh 命令；使用拍照或录像功能还需要正确连接摄像头并具备可用存储。

### 获取源码

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip ffmpeg

git clone --branch new_arch https://github.com/DayDayHappi/Gravity_ATS.git
cd Gravity_ATS
```

已有本地工程时，直接进入现有仓库，不必再次克隆。以下命令均从仓库根目录执行。

### 创建 Python 环境

```bash
python3 -m venv .venv
source .venv/bin/activate

python -m pip install pyserial PyYAML Jinja2

python --version
python -c "import serial, yaml, jinja2; print('Python dependencies OK')"
```

再次打开终端后，先进入工程并执行 `source .venv/bin/activate`。这里直接安装 CLI 所需的包，不依赖其他分支才可能提供的 `requirements-dev.txt`。

### 检查 FFmpeg 工具

```bash
command -v ffmpeg ffprobe ffplay
ffmpeg -version
ffprobe -version
```

FFmpeg 可以由系统安装，不必位于项目目录内。当前驱动在配置路径不可用时会尝试系统 `PATH`；需要明确指定版本时，将相关配置键设置为工具的实际绝对路径：

| 配置文件 | 工具路径键 |
| --- | --- |
| `ATS/config/modules/rtmp.yaml` | `ffprobe_path`、`ffmpeg_path`、`ffplay_path` |
| `ATS/config/modules/preview.yaml` | `ffplay_path` |
| `ATS/config/modules/video_integrity.yaml` | `ffmpeg_path` |

例如，`command -v ffmpeg` 返回 `/usr/bin/ffmpeg` 时，可将对应的 `ffmpeg_path` 配置为该值。仓库不随附 FFmpeg 二进制，不能把克隆成功等同于这些工具已经安装。

### 串口权限

```bash
sudo usermod -aG dialout "$USER"
```

注销并重新登录后检查串口设备和用户组：

```bash
id -nG
ls -l /dev/serial/by-id/
```

EVB 串口默认波特率为 **2000000**。可选电源控制器使用另一条串口，默认波特率为 **115200**，两者不要混用。运行 ATS 前关闭占用同一串口的其他终端或调试工具。

### Nginx RTMP 环境

只使用无网络拍摄、UTest 或本地视频检测时，不需要配置 Nginx。已有可用 RTMP 服务时，不要重复创建配置块或重复添加 `include`。

需要在本机部署时，安装：

```bash
sudo apt install -y nginx libnginx-mod-rtmp
```

将以下内容合入独立配置 `/etc/nginx/rtmp.conf`：

```nginx
rtmp_auto_push on;

rtmp {
    server {
        listen 1935;
        chunk_size 4096;

        application live {
            live on;
            record off;
        }
    }
}
```

在 `/etc/nginx/nginx.conf` 顶层引入一次，位置必须在 `http {}`、`events {}` 之外：

```nginx
include /etc/nginx/rtmp.conf;
```

校验成功后启动或重载服务：

```bash
sudo nginx -t && \
  sudo systemctl enable --now nginx && \
  sudo systemctl reload nginx
ss -lnt | grep ':1935'
```

默认推流目标为 `rtmp://<PC_IP>/live/cam`。`<PC_IP>` 必须是开发板可访问的主机地址，不能将板端的目标地址填写为 `127.0.0.1`。ATS 只检查 Nginx 的就绪状态，不负责替用户启动或停止系统服务。

主机有多块网卡时，明确设置 `system.yaml` 中的 `pc.ip`。FTP 使用主动模式，除 RTMP 的 TCP 1935 外，还需要允许板端回连主机的 FTP 数据端口。防火墙规则应限定为实际 EVB 地址或可信测试网段，不要为了测试直接关闭整个防火墙或对公网开放所有高端口。

## 首次运行

### 1. 调整系统环境

编辑 [ATS/config/system.yaml](ATS/config/system.yaml)，修改对应配置项，**不要用下面的片段覆盖整个文件**：

```yaml
serial:
  port: "/dev/ttyUSB0"
  baudrate: 2000000

wifi:
  default_ssid: "${WIFI_SSID}"
  default_password: "${WIFI_PASSWORD}"
  interactive: false

pc:
  ip: "auto"

power_switch:
  enabled: false
```

`serial.port` 替换为实际 EVB 设备；也可使用 `auto` 或稳定的 `/dev/serial/by-id/...` 路径。多网卡环境中的 `pc.ip` 可改为开发板能够访问的固定主机 IP。

**没有串口电源控制器时，请将已有的 `power_switch.enabled` 改为 `false` 并手动给板卡上电。** 核对基线中的实际值为 `true`，不能依据旁边“默认关”的历史注释判断开关。只有明确需要电源控制或恢复测试时才配置并启用该硬件。

采用上述环境变量写法时，在运行 ATS 的同一个终端设置：

```bash
read -r -p "WiFi SSID: " WIFI_SSID
read -r -s -p "WiFi password: " WIFI_PASSWORD
printf '\n'
export WIFI_SSID WIFI_PASSWORD
```

不要将真实密码提交到公开仓库。环境变量展开不会自动从 `.env` 文件加载内容；WiFi 密码还可能出现在原始串口收发日志中，共享日志前应进行脱敏。

### 2. 查看命令和进行静态检查

```bash
python -m ATS.main --help
python -m ATS.main --list-modules
python -m ATS.main --list-scenarios
python -m ATS.main --scenario normal --dry-run
```

`--dry-run` 校验部分配置、场景契约、模块注册及入口检查的依赖，不执行真实测试。它不证明串口、WiFi、FTP、Nginx 或摄像头链路已经通过，也不保证所有运行时工具和参数都已验证。

### 3. 验证串口交互

```bash
python -m ATS.main --terminal --port /dev/ttyUSB0 --baudrate 2000000
```

在终端中输入已确认由板端支持的命令，例如：

```text
echo "ATS_SERIAL_OK"
```

确认回显正常后，输入 `exit` 退出串口终端，再启动自动化测试。不要同时运行终端模式和测试模式占用同一设备。

### 4. 执行测试

首次使用建议先运行下节给出的 `quick_check` 短场景。准备好完整网络和 RTMP 环境后，可执行普通场景：

```bash
python -m ATS.main --scenario normal --port /dev/ttyUSB0 --baudrate 2000000
```

使用已配置的 WiFi 参数、跳过 WiFi 选择提示：

```bash
python -m ATS.main --scenario normal --port /dev/ttyUSB0 --no-interactive-wifi
```

`normal` 不是几秒钟的自检命令：它会执行真实拍照、录像和推流，持续时间来自模块或场景配置。`--no-interactive-wifi` 也只控制 WiFi 交互，测试结束时仍可能出现问题记录提示，不能将这个参数理解为全流程“无交互模式”。

## 场景与配置

### 三层配置职责

| 位置 | 应修改的内容 |
| --- | --- |
| `ATS/config/system.yaml` | EVB 串口、WiFi 凭据、PC IP、电源控制器、输出目录、执行策略。 |
| `ATS/config/modules/*.yaml` | 拍照模式、下载开关、录像默认组合与时长、推流参数、视频检测规则等。 |
| `ATS/config/scenarios/*.yaml` | 准备与清理动作、测试项顺序、任务重复次数、整轮循环、任务参数覆盖。 |

对某个任务而言，模块默认参数由该任务的 `override` 覆盖；对于声明了 `duration_key` 的模块，`task.duration` 再覆盖相应时长参数。`video` 对应 `video_duration`，`rtmp` 对应 `stream_duration`。CLI 只覆盖其明确提供的选项，不是任意 YAML 键的通用覆盖入口。

### 现有场景

| 场景名 | 主要用途与注意事项 |
| --- | --- |
| `normal` | 环境准备后执行 eMMC、拍照、录像和 RTMP。 |
| `stress` | 多拍照模式、多录像组合、视频检测和推流的循环压测；核对基线配置为 200 轮，运行前检查次数与时长。 |
| `aging` | 基于整轮时间预算的拍照和 RTMP 老化；时间预算在整轮结束时判断，不是强制到点打断当前任务。 |
| `Rtmp` | 独立 RTMP 推流与预览；场景名的大小写需保持一致。 |
| `no_network` | 不连接 WiFi、不启动 FTP 或 RTMP，执行 eMMC 与不下载的拍照、录像。 |
| `video_size_traverse` | 遍历录像命令组合并进行视频检测；当前配置末尾还包含拍照和 RTMP，不能仅凭名字认为它只录像。 |
| `stress_traverse_photo_mode` | 拍照模式遍历与录像、推流组合测试；具体任务以 YAML 为准。 |
| `stress_traverse_photo_mode_3k` | 使用 3k 录像组合的拍照模式遍历场景；具体任务以 YAML 为准。 |
| `utest` | 独立板级自检场景，不要求 WiFi、FTP 和预览。 |
| `video_integrity` | 仅检测指定本地目录，不连接板卡；先修改输入目录。 |
| `recovery_validation` | 健康监测与 PowerCycle 恢复验证；需要适配的电源控制器及正确的恢复配置。 |

这些 YAML 是可调整的测试策略，不是固定的产品指标。实际名称通过 `--list-scenarios` 确认；执行前阅读对应文件中的任务和参数。

### 示例：创建一个短测试场景

以下是**新增示例**，不是仓库已有文件。保存为 `ATS/config/scenarios/quick_check.yaml`：

```yaml
scenario:
  name: quick_check
  preview:
    enabled: false
  prepare:
    - serial_init
    - wifi_connect
    - preclean
    - ftp_ready
  loop:
    enable: false
  tasks:
    - module: emmc
    - module: photo
      repeat: 3
      override:
        photo_modes: [auto]
        ftp_download: true
    - module: video
      repeat: 2
      duration: 10
      override:
        video_resolution: "sd1080p_0"
        ftp_download: true
    - module: video_integrity
      override:
        input:
          source: "current_run"
          selection: "all_unchecked"
          empty_input_policy: "fail"
  cleanup:
    - close_serial
```

运行：

```bash
python -m ATS.main --scenario quick_check --dry-run
python -m ATS.main --scenario quick_check --port /dev/ttyUSB0 --no-interactive-wifi
```

此示例执行一轮：eMMC 检查、3 次 auto 拍照、2 次各保持 10 秒的录像，随后检测本次已下载且未检测的视频。它需要串口、WiFi、FTP 和 FFmpeg，不需要 Nginx，也不会初始化电源控制器。录像的 10 秒不包含启动、停止、下载与检测耗时。

`repeat` 控制一个任务的重复次数，`loop.count` 控制整个任务列表的重复轮数。同一 `photo` 任务中配置多个 `photo_modes` 时，每次 repeat 会遍历一次这些模式。需要为不同模式配置不同次数时，在场景中声明多个独立 `photo` 任务。

**禁用测试项应删除或注释整个 task，不要设置 `repeat: 0`。** 当前 Runner 会将该值按至少 1 次处理。启用 `loop` 却同时省略 `count` 和 `duration` 会进入无限循环，使用前应明确退出方式。

### 录像组合与诊断开关

录像组合 ID 来自 [ATS/drivers/video_commands.py](ATS/drivers/video_commands.py)，例如 `sd1080p_0`、`hd1080p_2`、`3k_2`、`720p_0`。场景只选择 profile，不直接拼接完整串口命令：

```yaml
- module: video
  repeat: 1
  duration: 20
  override:
    video_resolution: "3k_2"
    ftp_download: true
    detect_strings: [tt_error, imu_fmq_overflow]
```

上面是 `scenario.tasks` 内的任务片段，不是完整场景文件。`detect_strings: []` 表示不启用这组关键字符串检测；启用后命中内容写入结果详情，不单独改变 PASS/FAIL。

### 独立检测本地 H.265 文件

编辑现有的 `ATS/config/scenarios/video_integrity.yaml`，将输入目录改为真实的本地绝对路径。例如：

```yaml
scenario:
  name: video_integrity
  prepare: []
  tasks:
    - module: video_integrity
      override:
        input:
          source: "directory"
          directory: "/absolute/path/to/h265_cases"
          selection: "all"
          recursive: true
          empty_input_policy: "fail"
  cleanup: []
```

替换示例目录后执行：

```bash
python -m ATS.main --scenario video_integrity
```

默认匹配 `.h265`、`.hevc` 文件。检测规则位于 `ATS/config/modules/video_integrity.yaml`，包括解码、错误定位、trace 分析、超时、预期帧率与 GOP 参数。作为录像后置步骤使用时，需在场景中显式加入 `video_integrity` 任务；未选择就不会自动执行。

## 日志与报告

一次运行的日志与产物保存在：

```text
logs/<scenario>/<YYYYMMDD>/<YYYYMMDD_HHMMSS>/
├── serial.log                 # EVB 串口收发记录，保留 ANSI 内容
├── run.log                    # 框架执行过程与结果
├── photos/                    # 本次下载的 JPEG 样本，启用相关操作时生成
├── videos/                    # 本次下载的录像，启用相关操作时生成
├── video_integrity/           # 视频检测汇总、manifest 与诊断文件，按需生成
├── power_switch.log           # 电源控制器通信记录，按需生成
└── recovery.log               # 恢复协调过程记录，按需生成
```

默认报告目录按场景区分：

| 场景或设置 | 报告路径 |
| --- | --- |
| `normal` | `reports/<YYYYMMDD>/<YYYYMMDD_HHMMSS>/` |
| 其他场景 | `logs/<scenario>/report/<YYYYMMDD>/<YYYYMMDD_HHMMSS>/` |
| 显式传入 `--output-dir` | `<output-dir>/<YYYYMMDD>/<YYYYMMDD_HHMMSS>/` |

报告目录包含 `result.json`，并根据开关生成 `junit.xml` 和 `report.html`。HTML 适合人工查看，JSON 适合程序处理，JUnit XML 供测试系统解析。问题补充记录保存在 `logs/<scenario>/problem/<run_ts>.log`。

测试分析和恢复信息使用各自日志与报告，不应向 `serial.log` 插入人工分析结论。出现故障时，结合对应轮次的运行记录、串口原文、下载结果和视频诊断一起分析，不要只看最后一行 PASS。

| 退出码 | 当前入口含义 |
| --- | --- |
| `0` | 无入口识别的环境错误，且收集到的结果中没有 FAIL / ERROR；不表示所有检查都已执行，需同时查看 SKIP 和详情。 |
| `1` | 测试结果中存在 FAIL / ERROR。 |
| `2` | 配置、依赖或场景执行环境错误。 |

## 使用边界

**下载与拍摄判定是不同层次。** 当前联网拍照会在拍摄后下载该时间戳目录中的第一个 JPEG 作为样本，不是下载整目录所有图片；录像同样保留每次录完后的下载。视频可以在一组录像之后集中检测，但这不等于已经实现“全部拍完再统一下载”。部分 FTP 辅助校验失败或跳过时，拍摄仍可能根据串口完成标志报告 PASS，应查看结果详情。

**无网络场景只负责采集。** `no_network` 将拍照与录像的 `ftp_download` 关闭，不包含回到室内后自动补下载的工作流，也不在板端文件尚未传回主机时执行本地视频检测。

**录像 profile 中的尺寸是协议映射，不是本次文件测量结果。** 部分新增组合仍需真机校准，例如 `4k_0` 的尺寸字段为待校准占位值。拍照模式及其参数是否合法，也取决于实际固件支持。

**RTMP 心跳与视频诊断都有观测边界。** `f_index` 用于检测板端活动超时，不能替代持续的服务端收流或码率测量。H.265 检测用于发现可观察的解码、参考链和部分 POC 异常；解码成功不等同于证明原始采集零丢帧。无法可靠重建帧序时，诊断结果不会承诺精确的全局缺帧位置。

**恢复测试需要独立验证。** `recovery_validation` 显式启用健康监测与恢复，并要求先初始化电源控制器，再初始化 EVB 串口；恢复链按配置执行串口重连、板卡就绪检查、WiFi 和 FTP 重建。主线业务场景不因此自动开启故障恢复。项目状态文档记录了部分恢复链真机验证，但不代表全部边界用例已经完成；控制器确认也不能代替必要的实际供电验证。

**破坏性操作与平台支持需要明确区分。** `--format` 会触发 eMMC 格式化，可能清除数据，不应作为普通启动选项。UTest 中的 eFuse / Flash 项是板端自检接入，不是通用烧录工具，运行前应确认所用固件用例的副作用。多 EVB 并行测试尚不属于本文主线的已交付能力；Windows 或 GUI 使用方式应查阅对应分支，不能直接套用本页命令。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [文档入口](docs/README.md) | 按角色和主题查找工程资料。 |
| [项目总览](docs/00_project/overview.md) | 项目目的、背景和系统边界。 |
| [系统架构](docs/01_architecture/system_architecture.md) | 分层职责与执行模型。 |
| [模块设计](docs/01_architecture/module_design.md) | 功能模块职责与接口关系。 |
| [架构决策](docs/02_design/decision_record/README.md) | 串口、FTP、场景配置、预览、恢复等 ADR。 |
| [构建与运行环境](docs/05_handoff/build_environment.md) | 环境说明与部署背景。 |
| [当前状态](docs/05_handoff/current_status.md) | 当前实现、验证记录与进行中的事项。 |
| [已知问题](docs/05_handoff/known_issue.md) | 风险、限制和待处理问题。 |
| [测试策略](docs/04_testing/test_strategy.md) | 测试组织方式与验收思路。 |
| [开发记录](docs/03_development/devlog/README.md) | 历次改动背景、实现与验证留痕。 |

历史文档可能保留旧路径、旧命令或旧默认值。运行时以当前 `ATS/main.py`、模块实现和 YAML 配置为准；修改命令、模块或场景后，应同步维护对应说明。
