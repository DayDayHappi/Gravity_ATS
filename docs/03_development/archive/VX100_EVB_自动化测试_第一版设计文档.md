# VX100 EVB 上位机自动化测试脚本 - 第一版详细设计文档

**文档版本**: v1.2 (设计稿，已根据用户反馈多次更新)
**日期**: 2026-08-12
**依据**: `VX100_EVB_自动化测试_软件需求文档.md` v1.1 + `res/` 实测日志
**状态**: **待用户最终确认 - 确认后即开始编码**

---

## 0. 本期范围与边界

### 0.1 第一版必须跑通的目标

完整测试链路（顺序固定）：

```
WiFi连接 -> eMMC(cd) -> FTP服务器 -> 拍照 -> 录像 -> RTMP推流
```

| # | 目标 | 验收标准 |
|---|------|----------|
| 1 | **串口通信跑通** | 连接 EVB UART0，发命令收响应，哨兵机制定界，能判定各命令成功失败 |
| 2 | **WiFi 交互连接** | 启动时交互选择：默认 G-Demo 或扫描选 AP 输密码；连上拿到 IP，wifi 用例 SKIP |
| 3 | **eMMC** | `cd emmc` 验证可进入目录（默认跳过格式化） |
| 4 | **FTP 跑通** | EVB 起 FTP 服务后，PC 通过 ftplib 连接、列目录、上传/下载；后续供拍照录像验证复用 |
| 5 | **拍照跑通** | 遍历拍照模式，每拍一张通过 FTP 拉取验证 JPEG 头(FFD8FF) + 大小 > 阈值 |
| 6 | **录像跑通** | 1080p 录 5 秒，通过 FTP 拉取验证文件大小 > 阈值 |
| 7 | **RTMP 推流接收跑通** | EVB 推流，PC 用 ffmpeg 拉流存盘 + ffprobe 验证流可用 |

### 0.2 第一版暂不实现（预留接口/空实现）

- 多 EVB 并行（已明确本期不考虑）
- 负向测试（第二阶段）
- 电源自动控制（第一阶段人工上电 + 脚本检测 msh 就绪）
- eFuse / Flash 烧录（C 类，明确不纳入）

### 0.3 关键决策（已与用户确认）

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 串口命令结束判定 | **哨兵 + 超时** | msh 提示符会被后台日志/回显打碎粘连（实测 `msh />[32m...`、`msh />wifi scan`），单纯等提示符不可靠 |
| 串口波特率 | **可配置，默认 2000000** | 用户指定；自动探测时按 [2000000, 250000, 115200, 921600] 回退，避免默认值与实际不符导致乱码 |
| WiFi 连接方式 | **启动时交互** | 默认连 G-Demo；否则扫描列 AP 让用户选并输密码。连上后 wifi_scan/wifi_join 用例 SKIP，直接进 eMMC |
| eMMC 挂载 | **默认跳过，仅 `cd emmc` 验证** | 实测板子上电已自动挂载 `sd mount to /emmc/ is successful`，重复 mount 可能冲突；`--format` 才触发 mkfs |
| FTP 服务器时机 | **WiFi 后即启动，先于拍照录像** | 拍照/录像产物通过 FTP 实时验证，故 FTP 必须先启动 |
| 拍照验证粒度 | **每拍即验** | 每拍一张立即 FTP 列目录识别新增文件并下载验证，失败可定位到具体模式 |
| 拍照模式范围 | **默认 auto，可配全遍历** | 第一版默认只测 auto 快速冒烟；配置 `photo_modes` 可扩为 auto/single/mfnr/hdr(0-3) 共 7 种 |
| 拍照失败处理 | **只标记该模式 FAIL，继续下一个** | 不 fail-fast 中断，不影响后续录像/推流；报表中每个模式独立结果 |
| 录像验证 | **1080p / 5 秒 / 验大小** | 文件大小 > 阈值（默认 100KB） |
| 串口端口识别 | **默认自动探测** | 未指定 `--port` 时扫描 `/dev/ttyUSB*`+`/dev/ttyACM*`，用 `JX009`+`msh />` 指纹匹配；多个匹配让用户选 |
| RTMP 验证 | **ffmpeg 拉流存盘 + ffprobe** | 真正验证流可解码，顺带产出可回放样本 |
| PC 端服务管理 | **脚本自动启停** | ffmpeg 拉流端由脚本 subprocess 起/停，无人值守 |
| WiFi 默认密码 | **`Gdemo@123` 作默认值** | 直接写进配置，避免每次输入；可用环境变量覆盖 |

---

## 1. 从实测日志中提取的硬事实（设计的地基）

> 以下结论全部来自 `res/start.txt`、`res/wifi_scan_connect.txt`、`res/ftp.txt`。

### 1.1 串口底层

| 事实 | 证据 | 设计影响 |
|------|------|----------|
| 波特率 | 手册 UART0=250000；用户要求默认 2000000 | **可配置，默认 2000000**；自动探测时按 [2000000, 250000, 115200, 921600] 顺序回退，匹配 msh 指纹即用 |
| 提示符为 `msh />` | 日志多处 | 启动就绪检测、辅助命令结束参考 |
| 提示符会被打碎/粘连 | `msh />[32m[I/WLAN.lwip]...`、`msh />wifi scan`、`msh />msh />` | **不能用"等到提示符"作为命令结束的唯一判据** -> 采用哨兵机制 |
| 输出含 ANSI 颜色转义 | `\x1b[32m...\x1b[0m`、`\x1b[31m`、`\x1b[43m` | 解析前**必须剥离 ANSI 转义**，否则正则失配 |
| 命令有回显 | 发 `wifi scan` 后先回显 `wifi scan` | 哨兵机制天然兼容回显；解析时注意回显行不算结果 |
| 行结束符混合 CRLF/CR/LF | `file` 检测 | 发送命令统一用 `\n`；接收按行分割要兼容三种 |
| 启动就绪标志 | `JX009 A45 RTOS FW start ok` 后跟首个 `msh />` | 启动检测正则：`FW start ok` 或等待首个 `msh />` |
| eMMC 启动自动挂载 | `sd mount to /emmc/ is successful` | 默认无需 mount，仅 `cd emmc` |

### 1.2 命令响应的关键正则（已对齐实测字节）

| 命令 | 成功判据正则 | 提取 |
|------|-------------|------|
| `wifi scan` | 表头 `SSID\s+MAC\s+security\s+rssi\s+chn\s+Mbps` 出现，且至少 1 行数据 | 数据行：`^(\S+)\s+([0-9a-fA-F:]{17})\s+(\S+)\s+(-?\d+)\s+(\d+)\s+(\d+)` |
| `wifi join` | `Got IP address\s*:\s*([0-9.]+)` | 提取 IP 存入 `ctx.evb_ip` |
| `cd emmc` | 无 `error`/`failed`/`cannot` 关键字 | - |
| `ftp_server` | `Ftp server init success` 或 `service launched success` | - |
| `cam_set photo <mode>` | 无错误输出 | - |
| `dfs_capture_start` | 无错误输出 | 文件验证靠 FTP |
| `dfs_video_start` / `dfs_video_stop` | 无错误输出 | 文件验证靠 FTP |
| `rtmp_video_start <url>` | 无错误输出 + ffprobe 侧验证流到达 | - |

### 1.3 异步行为（影响用例编排）

- `wifi join` 是**异步**：先 `wifi connect success`，后（数秒后）才 `Got IP address`，中间插 SNTP 日志。
  -> 哨兵超时确认下发，成功判据盯 `Got IP address`，长超时 30s。
- `ftp_server` 成功消息两条间隔出现（`Ftp server init success!!!` -> `service launched success.`）。
  -> 任一出现即判通过，FTP 客户端连接需重试（等服务真正 listen）。
- 拍照/录像命令的同步/异步性未知（Q10 未确认）。
  -> **统一按异步处理**：发命令后轮询 FTP 目录，等待新增文件出现（超时 10s），不依赖串口返回。

### 1.4 网络环境（实测）

- PC：`wlp44s0`，IP `10.1.64.35/23`（DHCP，不固定）
- EVB：`10.1.90.71`（同一 /23 大网段，可互通）
- -> PC 的 `pc_ip` 需自动检测（取与 EVB 同网段的本机接口 IP）或配置覆盖

---

## 2. 系统架构

### 2.1 分层

```
┌─────────────────────────────────────────────────────┐
│  CLI 层          main.py (argparse + 交互)            │
├─────────────────────────────────────────────────────┤
│  编排层          TestRunner / TestCase / Reporter    │
├─────────────────────────────────────────────────────┤
│  模块层          WifiModule / EmmcModule /           │
│                  FtpModule / PhotoModule /           │
│                  VideoModule / RtmpModule            │
├─────────────────────────────────────────────────────┤
│  通信层          SerialConsole (哨兵机制)            │
│                  FtpClient (ftplib 封装)             │
│                  RtmpReceiver (ffmpeg/ffprobe)      │
├─────────────────────────────────────────────────────┤
│  基础层          config / logger / ansi / context    │
└─────────────────────────────────────────────────────┘
```

### 2.2 目录结构（第一版）

```
AutoTestScripts_JX009/
├── main.py                      # 入口，CLI 解析 + WiFi 交互 + 调度
├── config/
│   └── test_config.yaml         # 默认配置（端口、wifi、ftp、rtmp、camera、用例开关）
├── core/                        # 框架核心（稳定，加用例不改这里）
│   ├── __init__.py
│   ├── config.py                # 配置加载 + schema 校验 + ${ENV} 替换
│   ├── logger.py                # 带时间戳的全量串口日志 + 控制台进度
│   ├── ansi.py                  # ANSI 转义剥离
│   ├── context.py               # 跨模块共享上下文（evb_ip, pc_ip, ftp_client 等）
│   ├── serial_console.py        # 串口封装 + 常驻读线程 + 哨兵机制（核心）
│   ├── result.py                # TestCase / TestResult 数据结构
│   ├── reporter.py              # JSON + HTML + JUnit XML + 控制台
│   └── runner.py                # TestRunner：依赖排序、执行、重试、fail-fast
├── modules/                     # 功能模块（每模块一文件，可增删）
│   ├── __init__.py
│   ├── base.py                  # TestModule 基类 + 注册装饰器
│   ├── wifi.py                  # wifi scan / wifi join（交互连上则 SKIP）
│   ├── emmc.py                  # cd emmc 验证（+ 可选 mkfs/mount）
│   ├── ftp.py                   # ftp_server 启动 + FTP 客户端连接验证
│   ├── photo.py                # 拍照：遍历模式 + 每拍即 FTP 验证
│   ├── video.py                # 录像：1080p 录 N 秒 + FTP 验证
│   └── rtmp.py                  # rtmp 推流 + ffmpeg 拉流 + ffprobe 验证
├── drivers/                     # PC 端辅助服务
│   ├── __init__.py
│   ├── ftp_client.py            # ftplib 封装（连接/列目录/上传/下载，带重试）
│   └── rtmp_receiver.py         # ffmpeg 拉流 subprocess + ffprobe 验证
├── reports/                     # 输出目录（运行时生成）
├── logs/                        # 全量串口日志（按时间戳分目录）
├── doc/                         # 需求 + 设计文档
└── res/                         # 实测日志样本
```

**可扩展性体现**：
- 加测试项 -> 在 `modules/` 加一个文件 + `test_config.yaml` 的 `enabled_modules` 加一行，**不改 core/**
- 改测试方法（如 RTMP 验证换方式）-> 只改对应 module/driver
- 改流程顺序 -> 调整 `enabled_modules` 列表顺序 + 依赖声明，runner 拓扑排序

---

## 3. 核心设计：串口哨兵机制与日志采集（本版最关键部分）

### 3.1 问题

msh 提示符 `msh />` 不可靠：
1. 后台日志插队：`msh />[32m[I/WLAN.lwip] Got IP address : 10.1.90.71[0m`
2. 回显粘连：`msh />wifi scan`
3. 连续提示符：`msh />msh />`

### 3.2 方案：echo 哨兵 + 超时

每次发命令，实际发送 `"<cmd>; echo <TOKEN>"`，TOKEN 形如 `__EVBTEST_END_<随机>__`。
等待输出中出现 `TOKEN` 即认为命令已执行完毕，截取 TOKEN 之前的内容作为响应。

```
发送:  "wifi scan; echo __EVBTEST_END_7f3a__\n"
              │
              ▼
EVB 输出:
   wifi scan                       <- 回显
   <ssid 表格 ...>                 <- 命令真实输出
   __EVBTEST_END_7f3a__            <- 哨兵出现 -> 命令结束
   msh />                          <- 提示符（可能随后）
```

**为什么用 `; echo`**：保证哨兵在目标命令**之后**执行，即使目标命令异步（`wifi join` 立即返回 shell，`echo` 紧随其后，哨兵标记"命令已下发完毕"）--异步命令的真实结果靠**期望正则 + 长超时**捕获，哨兵只界定"下发窗口"。

> **异步命令双阶段**（如 `wifi join`）：
> - 阶段1（下发）：发命令 + 哨兵，哨兵超时短（5s），确认命令被接受
> - 阶段2（等结果）：继续读流，用期望正则 `Got IP address` 在长超时（30s）内匹配

### 3.3 串口日志采集：常驻读线程（回答用户的第 7 问）

> **关键设计**：串口日志不是"发一条命令才读"，而是**后台读线程持续采集**。

原因：msh 的后台日志（WiFi 连接中的 `[I/WLAN...]`、SNTP 同步、拍照录像回调）随时插进来，只在发命令后读会漏掉异步事件、也会让缓冲区积压。

实现：

```
SerialConsole 内部：
  - 一个常驻读线程 (_reader_thread)
  - 持续把串口字节写进 logs/<时间戳>/serial.log（带毫秒时间戳前缀，保留 ANSI 原始字节）
  - 同时喂进一个 环形缓冲 (deque)
  - exec_sync / exec_async 从缓冲里做"哨兵匹配"和"正则匹配"，截取响应
```

| 存储层 | 位置 | 内容 | 生命周期 |
|--------|------|------|----------|
| **全量原始日志** | `logs/<运行时间戳>/serial.log` | 串口收发每个字节，带毫秒时间戳，**含 ANSI** | 每次运行一个子目录，长期保留 |
| **用例级上下文** | `reports/<时间戳>/result.json` 每用例 `output` 字段 | 该用例执行期间剥离 ANSI 后的 clean 输出 + 判定 | 随报告输出 |
| **控制台** | 终端实时 | `[PASS]/[FAIL]` 进度 + 失败关键上下文 | 实时 |

`serial.log` 格式示例：
```
[12:05:03.142] TX> wifi scan; echo __EVBTEST_END_7f3a__
[12:05:03.158] RX< wifi scan
[12:05:03.160] RX<              SSID ...
[12:05:03.812] RX< msh />
[12:05:03.815] RX< __EVBTEST_END_7f3a__
```

### 3.4 SerialConsole 接口（核心 API）

```python
class SerialConsole:
    @staticmethod
    def detect_port(baudrate=250000, logger=None) -> str:
        """自动探测 EVB 串口：枚举 /dev/ttyUSB* / /dev/ttyACM*，
        发 \\n 后匹配 JX009/msh />/GravityXR.cn 指纹。
        0 个 -> 抛异常；1 个 -> 返回路径；多个 -> 交互让用户选。"""

    def __init__(self, port, baudrate=250000, timeout=2.0, logger=None): ...

    def open(self) -> None:
        """打开串口，刷新输入缓冲，启动常驻读线程"""

    def wait_for_ready(self, timeout=60) -> bool:
        """上电后等待 msh 就绪：匹配 'FW start ok' 或首个 'msh />'"""

    def exec_sync(self, cmd, expect=None, timeout=10.0) -> Response:
        """同步命令：发 cmd+哨兵，等哨兵出现(超时timeout)，返回哨兵前输出。
        expect 为正则，提供则据此判定 success，否则看有无 error 关键字。"""

    def exec_async(self, cmd, expect, send_timeout=5.0, result_timeout=30.0) -> Response:
        """异步命令：阶段1哨兵确认下发，阶段2等期望正则(result_timeout)。"""

    def send_raw(self, data: bytes) -> None:
        """裸发送（如复位后回车唤醒 shell）"""

    def close(self) -> None:
        """停止读线程，关闭串口"""
```

`Response` 数据结构：
```python
@dataclass
class Response:
    raw: str          # 原始输出（含 ANSI，用于日志）
    clean: str        # 剥离 ANSI 后的输出（用于解析）
    success: bool     # 判定结果
    elapsed_ms: int   # 耗时
    matched: str = None  # 正则匹配到的内容（如 IP）
    error: str = None    # 异常信息
```

### 3.5 命令分类与执行策略

| 类型 | 例子 | 策略 |
|------|------|------|
| 同步 | `wifi scan`, `cd emmc`, `ftp_server`, `rtmp_video_stop` | `exec_sync`：哨兵定界 + 正则判定 |
| 异步-下发即等结果 | `wifi join` | `exec_async`：哨兵确认下发后，继续读流等 `Got IP address`（30s） |
| 异步-文件完成型 | `dfs_capture_start`, `dfs_video_start` | `exec_sync` 确认无错 + **轮询 FTP 目录等新增文件**（10s 超时），不依赖串口返回 |
| 异步-起停对 | `rtmp_video_start` | start 用 `exec_sync` 确认无错 + 侧信道(ffprobe)验证 |

### 3.6 ANSI 剥离

`core/ansi.py`：
```python
ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')
def strip(text): return ANSI_RE.sub('', text)
```
（实测颜色码都是 `\x1b[Nm` / `\x1b[N;Mm` 形式，此正则覆盖。）

### 3.7 串口自动探测

未指定 `--port` 时，脚本自动识别 EVB 串口。**同时自动探测波特率**（因为默认 2000000 可能与实际不符）：

```
候选端口: /dev/ttyUSB* 和 /dev/ttyACM*（当前用户可访问的）
候选波特率: [2000000, 250000, 115200, 921600]  # 按优先级，默认值优先

对每个 (端口, 波特率) 组合：
  - 用该波特率打开
  - 发送 "\n" 唤醒
  - 读 2 秒输出，匹配 EVB 指纹：
    * "JX009 A45 RTOS FW start ok"  (启动日志)
    * 或 "msh />" 提示符
    * 或 "GravityXR.cn Build @"  (厂商构建标识)
  - 命中指纹 -> 记录 (端口, 波特率) 为候选

结果：
  - 0 个匹配 -> 报错"未发现 EVB 串口，请检查连接/上电/权限(dialout组)"
  - 1 个匹配 -> 直接使用，打印 "探测到 EVB: <端口> @ <波特率>"
  - 多个匹配 -> 列出列表让用户交互选择
```

**为什么默认 2000000 还要回退 250000**：手册和实测日志 `start.txt` 显示 UART0 是 250000，但用户要求默认 2000000。若 EVB 实际是 250000，用 2000000 打开会全乱码、探不到指纹。回退机制确保无论实际波特率是多少都能找到。

**指纹选择理由**：`JX009`/`GravityXR.cn Build`/`msh />` 是 EVB 独有特征，能区分于机器上其他 USB 串口设备。

**风险与对策**：探测会向每个候选串口发 `\n`。严格指纹匹配把误判降到最低；探测前检查当前用户对该端口的读写权限，无权限的跳过不试。

### 3.8 串口异常恢复（REL-001）

- 读超时/串口断连：最多重连 3 次，每次重连后发 `\n` 唤醒 shell，重新发命令
- 重连仍失败：标记用例 ERROR，fail-fast 跳过依赖项

---

## 4. 模块设计

### 4.1 TestModule 基类

```python
class TestModule:
    name: str                         # 模块名
    depends: list[str] = []           # 依赖的模块名
    def setup(self, ctx, console): ...    # 前置（可空）
    def run(self, ctx, console) -> TestResult: ...  # 主逻辑，子类实现
    def teardown(self, ctx, console): ... # 后置清理（可空）
```

注册：`@register("wifi")` 装饰器，模块导入即注册到全局表。

### 4.2 各模块第一版实现

#### WifiModule (`modules/wifi.py`)
- **交互逻辑（在 main.py 启动时执行，不在 module.run 里）**：
  - 提示"是否连接默认 WiFi (G-Demo)? [Y/n]"
  - 选 Y -> `wifi join G-Demo <password>`（密码从配置/环境变量）
  - 选 n -> `wifi scan` 列出 AP -> 用户输入 SSID 和密码 -> `wifi join <ssid> <password>`
  - 连接成功（`Got IP address`）后，把 `wifi_scan`/`wifi_join` 用例标记 SKIP
- `scan`：`exec_sync("wifi scan")`，正则匹配表头 + 解析至少 1 个 AP；记录 RSSI，<-70 警告
- `join`：`exec_async("wifi join {ssid} {password}", expect=r"Got IP address\s*:\s*([0-9.]+)", result_timeout=30)`，IP 存入 `ctx.evb_ip`
- 依赖：无

#### EmmcModule (`modules/emmc.py`)
- 默认：`exec_sync("cd emmc")`，验证无错误 + 能进目录
- `--format` 时：`exec_sync("mkfs -t elm sd", timeout=60)` -> `mount sd /emmc elm` -> `cd emmc`
- 依赖：无

#### FtpModule (`modules/ftp.py`)
- `run`：
  1. `exec_sync("ftp_server")`，等 `Ftp server init success` / `service launched success`
  2. `FtpClient` 连接 `ctx.evb_ip`（重试 3 次，间隔 1s）
  3. 验证：`list("/emmc")` 成功（非空或目录存在即通过）
  4. 把已连接的 `ftp_client` 存入 `ctx.ftp_client`，供拍照/录像模块复用
- 依赖：`wifi`（需要 evb_ip）

#### PhotoModule (`modules/photo.py`)
- `run`：
  1. 拍照前：`ctx.ftp_client.list_dir("/emmc/pic")` 记录旧文件集合 `before`
  2. 对每个模式（默认 `["auto"]`，可配全 7 种）：
     - `exec_sync("cam_set photo {mode}")` 确认无错误
     - 短延时（1s，可配）等 ISP 稳定
     - `exec_sync("dfs_capture_start")` 确认无错误
     - 轮询 `ctx.ftp_client.list_dir("/emmc/pic")`，等出现 `before` 之外的新文件（超时 10s）
     - 下载新文件，验证 JPEG 头 `FF D8 FF` + 大小 > 阈值（默认 10KB）
     - 记录模式/文件名/大小/RSSI 诊断到报告
  3. 失败模式：标记 FAIL，继续下一个模式（不 fail-fast 中断录像）
- 依赖：`ftp`（需要 ftp_client）

#### VideoModule (`modules/video.py`)
- `run`：
  1. 拍照前记录 `/emmc/video` 旧文件集合 `before`
  2. `exec_sync("cam_set video 1080p")` 确认无错误
  3. `exec_sync("dfs_video_start")` 确认无错误
  4. `time.sleep(video_duration)`（默认 5s）
  5. `exec_sync("dfs_video_stop")` 确认无错误
  6. 轮询 `ctx.ftp_client.list_dir("/emmc/video")` 等新文件（超时 15s，给编码落盘时间）
  7. 下载新文件，验证大小 > 阈值（默认 100KB）
- 依赖：`ftp`

#### RtmpModule (`modules/rtmp.py`)
- `setup`：确定 `pc_ip`（自动检测或配置）；`RtmpReceiver.start(url, duration)` 在 PC 起 ffmpeg 拉流端
- `run`：
  1. `exec_sync("rtmp_video_start rtmp://{pc_ip}/live/cam1")` 确认无错误
  2. 等 `stream_duration`（默认 10s）
  3. `RtmpReceiver.verify()`：ffprobe 拉到的流，检查有视频流/分辨率/编码
  4. `exec_sync("rtmp_video_stop")`
- `teardown`：`RtmpReceiver.stop()`
- 依赖：`wifi`（不依赖 ftp）

### 4.3 用例依赖图（第一版）

```
WiFi(交互连上) ──> eMMC(cd) ──> FTP服务器 ──> 拍照
                                            ├─> 录像
                                            └─> RTMP(只依赖WiFi,不依赖FTP)
```

实际执行顺序（`enabled_modules` 列表序）：
`wifi -> emmc -> ftp_server -> photo -> video -> rtmp_stream`

依赖在配置里声明，runner 拓扑排序校验；某模块失败时，依赖它的模块按 fail-fast 跳过（可配置 `retry_on_fail`）。

---

## 5. 配置文件设计 (`config/test_config.yaml`)

```yaml
serial:
  port: "auto"             # auto=自动探测(默认)；或填具体 /dev/ttyUSB0
  baudrate: 2000000        # 默认2000000(用户指定)；自动探测时按[2000000,250000,115200,921600]回退
  baudrate_candidates: [2000000, 250000, 115200, 921600]  # 探测候选
  timeout: 2.0
  ready_timeout: 60        # 等 msh 就绪
  sentinel_timeout: 5      # 哨兵下发确认超时
  detect_timeout: 2.0      # 自动探测时每个端口读响应超时

wifi:
  default_ssid: "G-Demo"
  default_password: "Gdemo@123"   # 默认密码(可用 ${WIFI_PASSWORD} 环境变量覆盖)
  interactive: true        # 启动时交互选择 WiFi

emmc:
  format: false            # 默认跳过格式化，仅 cd 验证

ftp:
  user: "loogg"
  password: "loogg"
  port: 21
  connect_retry: 3
  connect_interval: 1.0

camera:
  photo_modes: ["auto"]    # 默认只测 auto；可扩为 [auto, single, mfnr, hdr_0, hdr_1, hdr_2, hdr_3]
  photo_min_size_kb: 10    # 拍照文件最小有效大小
  photo_settle_delay: 1.0  # 模式切换后稳定延时(秒)
  photo_capture_timeout: 10  # 等新文件出现超时(秒)
  video_resolution: "1080p"
  video_duration: 5        # 录像时长(秒)
  video_min_size_kb: 100  # 录像文件最小有效大小
  video_capture_timeout: 15

rtmp:
  stream_url: "rtmp://{pc_ip}/live/cam1"
  stream_duration: 10
  pc_ip: "auto"            # auto=自动检测，或填具体 IP
  ffprobe_path: "ffprobe"
  ffmpeg_path: "ffmpeg"

test:
  enabled_modules:
    - wifi
    - emmc
    - ftp_server
    - photo
    - video
    - rtmp_stream
  retry_on_fail: 1
  fail_fast: true

report:
  output_dir: "reports"
  log_dir: "logs"
  junit: true
  html: true
```

- `${ENV_VAR}`：敏感信息从环境变量读；未设则交互提示输入
- `pc_ip: auto`：自动取本机与 `evb_ip` 同网段的接口 IP
- 启动时 schema 校验，配置错即报错退出（MAI-004）

---

## 6. PC 端辅助服务

### 6.1 环境依赖（第一版需安装）

| 依赖 | 用途 | 安装 |
|------|------|------|
| pyserial | 串口 | `pip install pyserial` |
| ffmpeg + ffprobe | RTMP 拉流验证 | `sudo apt install ffmpeg` |
| pyyaml | 配置 | 已装 |
| jinja2 | HTML 报告 | 已装 |

> 当前环境 pyserial/ffmpeg/ffprobe 未安装。代码里启动前检查依赖存在性，缺失则明确报错。

### 6.2 RtmpReceiver (`drivers/rtmp_receiver.py`)

```python
class RtmpReceiver:
    def start(self, url, duration):
        """subprocess 启动 ffmpeg 拉流存盘:
           ffmpeg -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 2 \\
                  -i <url> -t <duration> -c copy out.flv"""
    def verify(self) -> dict:
        """ffprobe out.flv，返回 {has_video, width, height, codec, duration}"""
    def stop(self):
        """终止 ffmpeg 进程，清理临时文件"""
```

### 6.3 FtpClient (`drivers/ftp_client.py`)

封装 `ftplib.FTP`，所有操作带重试：`connect_retry` 次，间隔 `connect_interval`。
**下载即"从板子复制文件到本地"**，用 `retrbinary` 二进制下载（保证照片/视频字节不被破坏）。

```python
class FtpClient:
    def connect(self, ip, port=21, user="loogg", pwd="loogg",
                retry=3, interval=1.0, pasv=True): ...
    def list_dir(self, path) -> list[str]:
        """列目录，返回文件名列表（用于拍照前后对比找新增文件）"""
    def download(self, remote, local) -> bool:
        """从板子复制文件到本地: ftp.retrbinary('RETR <remote>', 本地文件写)"""
    def upload(self, local, remote) -> bool:
        """从本地传文件到板子: ftp.storbinary('STOR <remote>', 本地文件读)"""
    def close(self): ...
```

被动模式 `pasv=True`（默认，跨 NAT 友好）；若 EVB FTP 服务不支持 PASV，可配 `pasv: false` 走主动模式。

---

## 7. 报告与日志

- **控制台**：实时进度 `[PASS] wifi_join (3.2s)` / `[FAIL] photo[hdr_2]: ...`
- **JSON**：`reports/<timestamp>/result.json`，每用例含 cmd/output/clean/elapsed/verdict
- **JUnit XML**：`reports/<timestamp>/junit.xml`（CI 集成）
- **HTML**：`reports/<timestamp>/report.html`（jinja2 模板）
- **全量串口日志**：`logs/<timestamp>/serial.log`（常驻读线程写入，含时间戳、原始字节）
- 退出码：0 全过 / 1 有失败 / 2 环境配置错

---

## 8. 执行流程

```
main.py
 ├─ 解析 CLI / 加载配置 / schema 校验
 ├─ 检查 PC 端依赖 (pyserial, ffmpeg)
 ├─ 确定串口：--port 指定则用；否则自动探测 (指纹匹配)
 ├─ 打开串口 -> wait_for_ready()
 ├─ WiFi 交互连接 (默认 G-Demo 或扫描选 AP)
 │    └─ 成功则 wifi_scan/wifi_join 用例 SKIP
 ├─ 拓扑排序 enabled_modules
 ├─ 依次执行：emmc -> ftp_server -> photo -> video -> rtmp
 │    ├─ module.setup()
 │    ├─ module.run()  (失败则 retry_on_fail 重试；拍照某模式失败只标该模式,继续下一个)
 │    ├─ module.teardown()
 │    └─ 失败且 fail_fast -> 跳过依赖项
 ├─ 生成 JSON / JUnit / HTML 报告
 ├─ 关闭串口 / 停止 PC 端服务 / 关闭 FTP 连接
 └─ 返回退出码
```

---

## 9. 关键风险与对策

| 风险 | 对策 |
|------|------|
| 250000 非标波特率，USB-串口芯片不支持 -> 丢字节/乱码 | open 后做"发 echo 测试"自检；乱码即报错。需在真实板子上验证芯片型号 |
| 哨兵 `echo` 本身被 msh 限制/不可用 | 先在板子上手动验证 `wifi scan; echo END` 是否正常输出 END；不可用则退化为"纯超时+正则" |
| 拍照/录像命令异步性未知 | 统一按异步处理：轮询 FTP 目录等新增文件，不依赖串口返回判完成 |
| ffmpeg 拉流端先于 EVB 推流启动，连接被拒 | ffmpeg 加 `-reconnect 1 -reconnect_streamed 1` 重连参数 |
| `wifi join` 异步，30s 仍拿不到 IP | 判失败，保留扫描列表/RSSI 诊断信息进报告 |
| EVB 掉电记忆 WiFi，二次测试"假通过" | 第一版不处理（预留），后续可加 `wifi disconnect` 前置 |
| eMMC 空间被照片视频累积占满 | 每用例下载验证后，可选清理（配置 `cleanup_files: false`，默认不清理，先观察） |

---

## 10. 已确认事项（v1.1 更新）

> 以下均已与用户确认，确认后即开始编码。

1. ✅ **哨兵机制**：用 `cmd; echo <TOKEN>` 定界（用户确认可行）
2. ✅ **目录结构**：`core/modules/drivers/config/` 划分认可
3. ✅ **WiFi 交互**：默认 G-Demo，否则扫描选 AP 输密码，连上后跳过 wifi 用例
4. ✅ **WiFi 默认密码**：`Gdemo@123` 直接作默认值
5. ✅ **流程顺序**：wifi -> emmc -> ftp -> 拍照 -> 录像 -> rtmp
6. ✅ **拍照**：默认 auto 可配全遍历，每拍即 FTP 验证 JPEG 头 + 大小
7. ✅ **拍照失败**：只标该模式 FAIL，继续下一个模式，不影响后续录像/推流
8. ✅ **录像**：1080p/5 秒，FTP 验证大小 > 100KB
9. ✅ **RTMP**：ffmpeg 拉流存盘 + ffprobe 验证
10. ✅ **串口自动探测**：默认自动扫描，用 JX009/msh /> 指纹匹配，多个则交互选
11. ✅ **环境安装**：授权使用 sudo 安装 pyserial + ffmpeg
12. ✅ **串口日志**：常驻读线程写 `logs/<时间戳>/serial.log`，全量原始字节带时间戳
13. ✅ **波特率**：可配置，默认 2000000；自动探测时按 [2000000,250000,115200,921600] 回退
14. ✅ **FTP 下载**：ftplib `retrbinary` 从板子复制文件到本地（二进制，保照片/视频字节完整）

---

## 附录 A：真机实测发现与代码修正（2026-08-12）

> 本附录记录真机验证阶段发现的、与设计文档原假设不符的固件特性，以及对应的代码修正。这些已固化到代码，修改此文档时需同步。

### A.1 波特率：实测 2000000（手册 250000 为旧固件）

- 手册和 `res/start.txt`（旧固件日志）是 250000，当前固件 UART0 实为 **2000000**
- 自动探测命中 2000000；代码默认 2000000 + 回退候选正确

### A.2 msh 命令分隔：不支持 `;`，哨兵改换行分隔

原设计 §3.2 哨兵用 `cmd; echo <TOKEN>`。**实测 msh 不支持 `;` 分隔命令**：
- `cmd1; cmd2` 被 echo 当成单参数，报 `Usage: echo "string" [filename]`
- **修正**：哨兵改用换行分隔 `cmd\necho "TOKEN"`（`serial_console.py` 的 `exec_sync`/`exec_async`）
- **echo 必须带引号**：`echo "string"` 用法，无引号报 Usage（`health_check` 也改为带引号）

### A.3 msh 提示符：两种形态

- 根目录 `msh />`，子目录 `msh /emmc>`
- 原就绪正则 `msh\s*/?>` 只匹配 `msh />`，**修正**为 `msh\s+/[^>]*>|msh\s*/>`（`serial_console.py`）

### A.4 FTP 服务重大限制（RT-Thread 自带）

原设计假设 FTP 标准可用（PASV/NLST/STOR/SIZE）。**实测有重大限制**：

| 功能 | 实测 | 代码修正 |
|------|------|----------|
| PASV 被动模式 | ❌ `502 Not Implemented` | `FtpClient` 默认 `pasv=False`（主动模式） |
| 主动模式数据连接 | 需 PC 防火墙放行入站 | 文档要求 `sudo ufw disable` 或放行高位端口 |
| `LIST <path>` | ❌ 忽略路径参数，列当前目录 | `_list_entries` 改为先 `CWD` 再无参 `LIST` |
| NLST | ❌ 502 | `list_dir`/`list_files` 改用 `LIST` 解析 |
| STOR 上传 | ❌ 502 | `upload` 标记不可用（FTP 只读） |
| SIZE | ❌ 502 | `size` 改用 `LIST` 父目录解析 |

**⚠️ 固件 bug：FTP 服务在摄像头操作（拍照/录像）后崩溃**（`[W/ftp] service go wrong` 反复）。重发 `ftp_server` 可恢复。`ftp.py` 新增 `ensure_ftp()` 自动检查恢复，`photo`/`video` 模块在使用 FTP 前调用。

### A.5 拍照/录像文件结构（与手册完全不同）

手册说 `/emmc/pic`（小写）直接放文件。**实测**：

```
/emmc/PIC/<时间戳目录>/Image_<时间戳>_<序号>.jpg   (大写 PIC，子目录，auto 模式多个 jpg)
/emmc/VIDEO/<时间戳目录>/Video_<序号>_0.h265        (大写 VIDEO，h265)
                        /Imu_<序号>.bin
```

`photo.py`/`video.py` 已适配此结构，文件验证改为从串口输出解析保存路径。

### A.6 拍照/录像命令：海量日志打乱哨兵，改用 exec_async

原设计 §3.5 拍照/录像用 `exec_sync`（哨兵定界）。**实测**：
- 这两个命令输出**海量摄像头初始化日志**（sensor probe、AE/AWB、mem_laySolv 等），打乱哨兵回显（引号丢失、行错位）
- **修正**：`photo.py`/`video.py` 的拍照/录像改用 `exec_async`（发命令后直接等正则，不依赖哨兵）
- 成功判据用串口正向标志：
  - 拍照：`Save Photo Successful:\s*(\S+)`（解析保存目录）
  - 录像：`Save Video Successful:\s*(\S+)`（解析视频路径）
- 不再用"无 error 关键字"判定（初始化日志含 `invalid`/`failed` 等词会误判）
- FTP 下载 JPEG 验证降级为**辅助**：FTP 崩溃时优雅降级（不判 FAIL，串口已确认成功）

### A.7 WiFi 命令实测确认

- `wifi scan` 存在，输出表头 + AP 列表
- `wifi join` 异步：`connect success` 后约 9s 才 `Got IP address`，`exec_async` result_timeout=35s
- `wifi status` 查状态，`wifi disc` 断开
- 注意 `wifi join` 阻塞执行，echo 哨兵要等命令返回才输出；`exec_async` 不强制等哨兵，直接等 `Got IP` 正则

### A.8 待验证

- RTMP 推流（待装 ffmpeg）

---

*文档结束*
