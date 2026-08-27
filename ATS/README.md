# VX100 EVB 上位机自动化测试脚本

通过串口 + 网络与 VX100 EVB 板交互，自动执行功能测试（WiFi / eMMC / FTP / 拍照 / 录像 / RTMP），生成 JSON / JUnit / HTML 报告。

- **被测系统**：RT-Thread msh shell（UART0），双核异构 RISC-V
- **运行环境**：Ubuntu 20.04+，Python 3.8+
- **设计文档**：`../docs/03_development/archive/VX100_EVB_自动化测试_第一版设计文档.md`

---

## 1. 快速开始

### 1.1 安装依赖

```bash
# Python 串口库
sudo apt install -y python3-serial
#   或: pip install pyserial

# ffmpeg + ffprobe（RTMP 推流验证用）
sudo apt install -y ffmpeg
```

> 若机器离线/镜像故障，见下方「附录 A：离线安装 pyserial」。

### 1.2 运行

```bash
cd /home/gravity/AutoTestScripts_JX009

# 列出所有可用模块
python3 -m ATS.main --list-modules

# 列出所有可用场景
python3 -m ATS.main --list-scenarios

# 校验配置和依赖（不连板子）
python3 -m ATS.main --dry-run

# 完整测试（普通场景，自动探测串口 + WiFi 交互连接）
python3 -m ATS.main --scenario normal

# 压测场景（photo 50 次 + video 3min + rtmp 10min，循环 3 轮）
python3 -m ATS.main --scenario stress --no-interactive-wifi

# 指定串口
python3 -m ATS.main --port /dev/ttyUSB0

# 详细日志
python3 -m ATS.main -v
```

### 1.3 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 全部通过 |
| 1 | 有失败用例 |
| 2 | 环境/配置错误（依赖缺失、串口找不到等） |

---

## 2. 测试流程

```
WiFi连接(交互) -> eMMC(cd) -> FTP服务器 -> 拍照 -> 录像 -> RTMP推流
```

启动时交互选择 WiFi：
- 默认连 `G-Demo`（密码 `Gdemo@123`，可在配置改）
- 或扫描列出 AP 让你选并输密码
- 连上后 `wifi_scan`/`wifi_join` 用例自动 SKIP，直接进 eMMC

---

## 3. 配置

配置拆为三层（`config/` 目录），各司其职：

```
config/system.yaml            系统/环境级：串口、WiFi 网络环境、PC 地址、报告
config/modules/<name>.yaml    模块能力参数（photo/video/rtmp/...）
config/scenarios/<name>.yaml  测试策略：流程/组合/循环次数/持续时间
```

常用项：

```yaml
# system.yaml
serial:
  port: "auto"          # 自动探测；或填 /dev/ttyUSB0
  baudrate: 2000000     # 默认；探测时自动回退 [2000000,250000,115200,921600]
wifi:
  default_ssid: "G-Demo"
  default_password: "Gdemo@123"
pc:
  ip: "auto"            # RTMP 推流目标

# modules/photo.yaml
photo_modes: ["auto"]   # 可扩为 [auto,single,mfnr,hdr_0,hdr_1,hdr_2,hdr_3]
```

敏感字段支持 `${ENV_VAR}` 从环境变量读。

**新增测试项**：`modules/` 新建文件 + `@register("xxx")` + `config/modules/xxx.yaml` + 场景 tasks 加一行。无需改 core。
**新增测试模式**（压测/老化/自定义组合）：只需新增 `config/scenarios/<name>.yaml`，不改模块核心逻辑。

---

## 4. 架构（解耦设计）

```
core/      框架核心（稳定，加用例不改这里）
  serial_console.py   哨兵机制 + 常驻读线程 + 自动探测 + 波特率回退
  scenario.py         Scenario/Task/LoopConfig 数据结构 + prepare/cleanup 动作注册表
  scenario_manager.py 加载场景 + 编排 prepare→tasks(loop)→cleanup
  runner.py           按 Task 列表调度 + repeat/loop + 重试 + fail-fast
  reporter.py         JSON + JUnit + HTML
modules/   功能模块（每模块一文件，可增删）
  base.py             TestModule 基类 + @register 装饰器
drivers/   PC 端辅助
  ftp_client.py       ftplib 封装（重试 + 下载）
  rtmp_receiver.py    ffprobe 实时探测 RTMP 流
  rtmp_server.py      nginx-rtmp 就绪检查（不启停 nginx）
```

**职责边界**：Scenario=怎么组合测试，Runner=什么时候执行，Module=怎么测，Config=参数是什么。

**模块间解耦**：通过共享上下文 `ctx` 传数据（`wifi` 存 `evb_ip`、`ftp` 存 `ftp_client`），不互相 import。删某个模块不影响其他。

---

## 5. 串口哨兵机制（核心）

msh 提示符 `msh />` 会被后台日志/回显打碎粘连（实测 `msh />[32m...`、`msh />wifi scan`），单纯等提示符不可靠。

方案：每条命令实际发 `cmd; echo <TOKEN>`，等 TOKEN **作为独立行**出现即定界命令结束。解析前剥离 ANSI 转义。异步命令（如 `wifi join`）用双阶段：哨兵确认下发后，继续读流等 `Got IP address`（长超时 30s）。

---

## 6. 输出

每次运行生成时间戳子目录：

```
reports/<时间戳>/
  result.json     机器可读，含每用例详情
  junit.xml       CI 集成（Jenkins/GitLab）
  report.html     人可读可视化
logs/<时间戳>/
  serial.log      全量串口原始字节（带毫秒时间戳，含 ANSI）
  run.log         框架运行日志
  photos/         下载的拍照文件
  videos/         下载的录像文件
```

---

## 7. 实测发现与固件特性（2026-08-12 真机验证）

> 以下为真机实测确认的固件特性，与手册/设计文档的差异已固化到代码。供后续维护参考。

### 7.1 ✅ 波特率

- **实测 UART0 = 2000000 bps**（手册写的 250000 是旧固件；当前固件已改 2000000）
- 自动探测按 `[2000000, 250000, 115200, 921600]` 回退，实测命中 2000000
- 串口：`/dev/ttyUSB0`（FT2232 双通道之一）

### 7.2 ✅ msh 命令分隔与 echo（哨兵机制关键）

- **msh 不支持 `;` 分隔命令**：`cmd1; cmd2` 会被 echo 当成单参数报 `Usage`。哨兵改用**换行分隔** `cmd\necho "TOKEN"`
- **echo 必须带引号**：`echo "string"` 用法，`echo string`（无引号）会报 `Usage: echo "string" [filename]`
- **提示符有两种**：`msh />`（根目录）和 `msh /emmc>`（子目录），就绪正则已适配 `msh\s+/[^>]*>`

### 7.3 ✅ FTP 服务（RT-Thread 自带，有重大限制）

- **只支持主动模式（PORT），不支持 PASV**（返回 `502 Not Implemented`）
- `pasv: false`（已设为默认）；需 **PC 防火墙放行入站数据端口**（`sudo ufw disable` 或 `ufw allow 1024:65535/tcp`）
- **`LIST <path>` 忽略路径参数**：必须先 `CWD` 再无参 `LIST` 才列对目录（代码已处理）
- **不支持 NLST/STOR/SIZE**：`list_files` 用 LIST 解析；上传不可用；`size` 用 LIST 父目录解析
- **⚠️ FTP 服务在摄像头操作（拍照/录像）后会崩溃**：`[W/ftp] service go wrong` 反复。重发 `ftp_server` 可恢复。`ensure_ftp()` 已实现自动恢复
- 用户 `loogg`/密码 `loogg`，端口 21

### 7.4 ✅ 拍照/录像文件结构（与手册不同）

手册说 `/emmc/pic`（小写）直接放文件，**实测完全不同**：

```
/emmc/PIC/<时间戳目录>/Image_<时间戳>_<序号>.jpg   (auto 模式生成多个 jpg)
/emmc/VIDEO/<时间戳目录>/Video_<序号>_0.h265        (主视频)
                        /Imu_<序号>.bin              (附加 IMU 数据)
```

- 目录大写 `PIC`/`VIDEO`，每次拍照/录像生成一个**时间戳命名的子目录**
- 拍照成功标志（串口）：`[App Dfs] Capture completed successfully.`（相机日志全部打印完的完成标志；保存路径在其前一条日志 `[App Dfs] Save Photo Successful: /emmc/PIC/<dir>/`，脚本从累积缓冲扫描路径）
- 录像完成标志（串口）：`[App Dfs] Video recording completed successfully.`（`Save Video Successful: <path>` 出现更早约 2s，且其路径会被串口分块截断，不能作完成判据；路径从累积缓冲扫描）

### 7.5 ✅ 拍照/录像命令的异步性（哨兵失效，改 exec_async）

- 拍照/录像命令**输出海量摄像头初始化日志**（sensor probe、AE/AWB、mem_laySolv 等），会**打乱哨兵回显**（引号丢失、行错位）
- **不能用 exec_sync（哨兵定界）**，改用 `exec_async`（发命令后直接等正则，不依赖哨兵）
- 成功判据用串口正向标志（拍照 `Capture completed successfully.`、录像 `Video recording completed successfully.`），不靠"无 error 关键字"（初始化日志含 `invalid` 等词会误判）
- FTP 下载 JPEG 验证作为**辅助**：FTP 崩溃时优雅降级（不判 FAIL，串口已确认成功）

### 7.6 ✅ WiFi 命令

- `wifi scan` 输出表头 + AP 列表
- `wifi join <ssid> <pwd>` 异步：先 `wifi connect success`，后（约 9s）`Got IP address : <IP>`
- `Got IP address` 正则：`Got IP address\s*:\s*([0-9.]+)`（注意冒号前后有空格）
- `wifi status` 查连接状态；`wifi disc` 断开

### 7.7 ✅ RTMP 推流

- PC 端需起 **nginx-rtmp** 服务端（`systemctl start nginx`，监听 1935，配 `application live { live on; record off; }`）
- 命令：`rtmp_video_start rtmp://<pc_ip>/live/cam`、`rtmp_video_stop`
- PC 的 IP 自动检测（多网卡建议在 `config/system.yaml` 写死 EVB 可达的 `pc.ip`）
- 验证：`ffprobe` 实时探测 `rtmp://<pc_ip>/live/cam`（探到 h264 + 分辨率即 PASS），可选 `ffplay` 画面确认（无 DISPLAY 自动跳过）
- ★ 关键时序：ffprobe 探测必须在 `rtmp_video_stop` 之前（探测的是实时流）

### 7.8 ✅ eMMC

- 板子上电**自动挂载**到 `/emmc`，默认只 `cd emmc` 验证
- 若不自动挂载，加 `--format` 或配 `emmc.format: true`

### 7.9 ⚠️ 测试稳定性注意

- **连续拍照+录像可能触发摄像头资源冲突**：若录像 start 卡住（无 `Record Start`），可能上次操作未释放。建议复杂场景下测试前重启板子
- **FTP 在每次摄像头操作后会崩**：`ensure_ftp` 会恢复，但连续操作间隔太短可能来不及
- 建议每轮完整测试前重启板子，保证干净状态

---

## 8. 常见问题

**Q: 自动探测找不到串口？**
检查：1) EVB 已上电并连接  2) 当前用户在 `dialout` 组（`sudo usermod -aG dialout $USER` 后重新登录）  3) `ls /dev/ttyUSB*` 有设备

**Q: WiFi 连不上？**
看 `logs/<时间戳>/serial.log` 里的 `wifi join` 输出。RSSI < -70 信号弱，换近一点的 AP。

**Q: 拍照后等不到新文件？**
看串口日志 `dfs_capture_start` 是否报错；FTP 列 `/emmc/pic` 是否成功；eMMC 是否已挂载。

**Q: RTMP 推流验证失败？**
确认 PC 的 IP 与 EVB 同网段；防火墙放行 1935 端口；`logs/<时间戳>/rtmp/` 下的 flv 文件大小。

---

## 附录 A：离线安装 pyserial

若 `apt install python3-serial` 因镜像故障失败（如 `File has unexpected size`）：

```bash
# 方法1: 换源重试
sudo apt update
sudo apt install -y python3-serial --fix-missing

# 方法2: 换清华源
sudo sed -i 's|mirrors.aliyun.com|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list
sudo apt update && sudo apt install -y python3-serial

# 方法3: pip 离线包（在能上网的机器上下载）
#   能联网的机器: pip download pyserial -d ./pyserial_pkg
#   拷到本机:     pip install --no-index --find-links=./pyserial_pkg pyserial

# 方法4: 直接从 GitHub 装（若有 git 访问）
pip install git+https://github.com/pyserial/pyserial.git
```

## 附录 B：目录约定

```
ATS/                 本脚本
docs/                文档知识库（设计/需求归档见 docs/03_development/archive/）
res/                 实测日志样本（开发参考）
reports/             测试报告（运行时生成）
logs/                全量日志（运行时生成）
```
