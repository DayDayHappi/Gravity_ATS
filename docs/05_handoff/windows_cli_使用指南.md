# Windows 命令行版安装与使用

版本：2026-09-16 / all_source(8) 增量移植。无 ATS GUI、无 Qt、无 EXE 打包。
**交付状态：源码及自动化测试已完成，Windows 原生 EVB 联调尚未验收。**
请先用 smoke 场景逐级联调，不要直接跑数百轮压力测试。

## 1. 应用增量包

增量包不是完整工程，只能应用到你已有的 Gravity_ATS。先结束正在运行的 ATS。
解压到工程外，例如 `D:\Temp\Gravity_ATS_Windows_CLI_20260916`。在该目录打开 PowerShell：

```powershell
py -3 .\apply_patch.py --target 'D:\prj\Gravity_ATS' --check
py -3 .\apply_patch.py --target 'D:\prj\Gravity_ATS'
```

第一条只检查，不改文件。第二条在全部文件核对通过后，先备份再应用。
安装器比较 all_source(8) 导出的基线文本，容忍 Git CRLF/LF、UTF-8 BOM 和文件末尾换行差异。
同一路径已被你另外改动、或新增文件与现有文件冲突时，**整包拒绝应用**；不要强制覆盖，保留冲突输出进行合并。
已应用过的相同版本可重复执行，不重复覆盖。
备份在工程 `.ats_cli_backups/<时间戳>/`，仅包含本次被替换文件的原始字节和安装记录。
应用期间发生可捕获异常会尝试恢复已触及文件；断电等不可捕获故障仍需借助备份/版本控制恢复。
根目录原有 requirements、虚拟环境、工具二进制和未涉及的源码不随包覆盖。

## 2. 创建独立 CLI 环境

以下以 **64位 Windows + Python 3.12** 作为建议的现场验收环境，不表示本次已在该环境测试。
使用已安装的64位Python；`py -3` 指向什么版本可用 `py -3 --version` 查看。

```powershell
cd D:\prj\Gravity_ATS
py -3 -m venv .venv-cli
.\.venv-cli\Scripts\python.exe -m pip install -r ATS\requirements-cli.txt
.\.venv-cli\Scripts\python.exe --version
.\.venv-cli\Scripts\python.exe -m pip freeze
```

依赖为 pyserial 3.5、PyYAML 6.0.3、Jinja2 3.1.6。不使用旧 UI 分支的 requirements-dev，避免带入 Qt/pytest-qt。
这里直接调用虚拟环境的 python.exe，**不需要 Activate.ps1，也不需要修改 PowerShell 执行策略**。
不要复制 Ubuntu 的 `.venv` 或把 Linux FFmpeg 重命名成 `.exe`。

## 3. 放置 Windows FFmpeg 套件

本包不含 FFmpeg、ffplay 或 nginx 的可执行文件。请提供适合本机架构的 Windows 构建：

```text
Gravity_ATS/
  tools/ffmpeg/
    ffmpeg                 # 原来的Linux工具可保留
    ffprobe
    ffplay
    windows/
      ffmpeg.exe
      ffprobe.exe
      ffplay.exe           # 只有需要画面观察时才必需
```

若构建包附带 DLL，要保留其所需的同版本 DLL，不要只拷贝依赖缺失的 exe。
FFmpeg 官方下载页列出 Windows 构建来源，选择后由现场记录下载来源、版本和SHA256。
本交付没有指定“已验证的Windows二进制版本”，不能把Linux验证的7.1.5当作Windows验收结果。

```powershell
.\tools\ffmpeg\windows\ffmpeg.exe -version
.\tools\ffmpeg\windows\ffprobe.exe -version
.\tools\ffmpeg\windows\ffmpeg.exe -hide_banner -bsfs
Get-FileHash .\tools\ffmpeg\windows\ffmpeg.exe -Algorithm SHA256
```

`trace_headers` 支持完整错误诊断；缺失时保留原模块的诊断降级行为，不把已发现的解码错误改为PASS。
工具默认查找：平台内置目录 → 兼容布局 → 系统PATH。找到后会真实运行 `-version` 验证。
原 YAML 的 `tools/ffmpeg/ffmpeg` 等默认值会自动适配平台，不必为Windows修改全部正式场景。
其它显式配置路径严格使用：写错路径会报错，不悄悄改用另一版本。
工具相对路径固定相对于工程根；`--config-dir`、输入目录和输出目录的相对路径仍相对于启动目录。

## 4. 不接板子，先验证 CLI 与本地视频

```powershell
.\.venv-cli\Scripts\python.exe -m ATS.main --list-modules
.\.venv-cli\Scripts\python.exe -m ATS.main --list-scenarios
.\.venv-cli\Scripts\python.exe -m ATS.main --list-ports

.\.venv-cli\Scripts\python.exe -m ATS.main --scenario video_integrity --input-dir 'D:\h265_cases' --dry-run --no-preview --no-problem-prompt
.\.venv-cli\Scripts\python.exe -m ATS.main --scenario video_integrity --input-dir 'D:\h265_cases' --no-preview --no-problem-prompt
```

先创建 `D:\h265_cases` 并放入真实 `.h265` / `.hevc` 文件。不要原样运行一个不存在的示例目录后把失败当移植失败。
`--input-dir` 覆盖为本地目录、选择全部匹配文件；其它匹配pattern/recursive等设置保留。
没有匹配文件时遵循原场景 empty_input_policy，默认失败。
独立检测不连串口、Wi-Fi、FTP 或 nginx；本地检测通过后再接板子。
`--dry-run` 校验配置/模块注册和实际工具可运行性，不证明板端连接、输入视频质量或网络服务通过。

## 5. 串口终端

安装USB串口芯片对应Windows驱动，查看 `--list-ports` 输出。下面COM10只是例子，按实际端口替换。
先关闭 Xcom 等占用同一个串口的程序：

```powershell
.\.venv-cli\Scripts\python.exe -m ATS.main --terminal --port COM10 --baudrate 2000000
```

回车发送；Tab切换ANSI剥离；退格编辑；Ctrl+C / exit / quit 退出。需要真实交互控制台，不从管道重定向stdin。
自动探测仍以EVB指纹和候选波特率确认身份，不把USB描述当作板子识别结果。
自动候选优先USB并排除蓝牙；`--port COM10` 显式指定则不受自动候选过滤限制。
2Mbps是否稳定必须用本机USB串口驱动与EVB验收，成功打开端口不足以证明持续通信可靠。

## 6. 拍照、录像和FTP冒烟

先确认Windows与EVB互通，并检查 `ATS/config/system.yaml` 的Wi-Fi目标和 `pc.ip`。
板子已有非零IP时，原 wifi_connect 逻辑会保留既有连接，不保证强制切换到你新填的SSID。
多网卡环境下 `pc.ip` 应为板子实际可达的Windows地址。

```powershell
.\.venv-cli\Scripts\python.exe -m ATS.main --scenario cli_smoke_capture --port COM10 --baudrate 2000000 --no-interactive-wifi --no-preview --no-problem-prompt
```

顺序：eMMC进入目录 → auto拍照一次 → sd1080p_0录像5秒 → 检测本次下载视频。
默认不格式化，没有 `--format`。录像完成后仍立即下载，没有改为最后批量下载。
此冒烟场景将录像检测无输入设为FAIL，避免“根本没下载视频”却只看到跳过。
照片仍保留原有辅助验证语义，**必须检查 photos 下实际下载文件，不能只看photo PASS**。
本地文件路径用Windows规则；板端 `/emmc/PIC`、`/emmc/VIDEO` 和所有串口命令保持原样。

### 主动FTP与Windows防火墙

FTP服务在EVB上，PC是客户端；不要在PC另装FTP服务端。保留 `pasv: false`。
主动模式要求EVB回连Windows Python的数据端口。下面规则仅作为受控测试网络的配置示例：

```powershell
# 仅此段需要管理员 PowerShell；把示例地址改为现场EVB地址。
$BoardIp = '192.168.1.50'
$PythonExe = (Resolve-Path 'D:\prj\Gravity_ATS\.venv-cli\Scripts\python.exe').Path
Get-NetConnectionProfile
New-NetFirewallRule -DisplayName 'Gravity ATS CLI FTP test' -Direction Inbound -Action Allow -Program $PythonExe -Protocol TCP -RemoteAddress $BoardIp -Profile Private
```

该规则只适用于匹配的Private配置文件。不要为使示例“生效”而把不可信公共网络改为Private，也不要关闭整机防火墙。
如果网络由公司管理，按管理员批准的范围配置；板子IP变化后规则也需更新。
规则仅授权这一个Python程序，和RTMP服务1935的规则不是一回事。

## 7. Windows本机RTMP服务与推流冒烟

这一步仍需要现场准备并验证 **支持 nginx-rtmp 的Windows构建**；本包不带服务器。
普通nginx.exe或1935端口被别的程序监听，都不能证明RTMP application配置正确。
本轮ATS只检查本机127.0.0.1:1935，**未新增远程RTMP服务端支持**。

在服务器自己的目录中配置并运行。以下为最小测试配置示例，不要直接覆盖承载其它服务的nginx配置：

```nginx
worker_processes 1;
error_log logs/error.log info;

events { worker_connections 1024; }

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

```powershell
# 位于你实际的nginx目录；先确认配置校验成功。
.\nginx.exe -V
.\nginx.exe -t
# 未启动时才启动；ATS不会替你反复启动。
.\nginx.exe
Test-NetConnection 127.0.0.1 -Port 1935
```

若 `nginx -t` 报 `unknown directive "rtmp"`，需补齐该构建所需模块或换用支持RTMP的构建。
nginx配置路径使用正斜杠；配置中的相对路径与启动前缀有关。Windows nginx有上游说明的运行限制，不作生产性能保证。

给实际 nginx.exe 添加仅来自EVB的1935入站规则；也需要管理员权限：

```powershell
$NginxExe = (Resolve-Path 'D:\tools\nginx-rtmp\nginx.exe').Path
$BoardIp = '192.168.1.50'  # 替换为现场值
New-NetFirewallRule -DisplayName 'Gravity ATS RTMP test' -Direction Inbound -Action Allow -Program $NginxExe -Protocol TCP -LocalPort 1935 -RemoteAddress $BoardIp -Profile Private
```

先在PC本机做发布/拉流自检。工程根的两个PowerShell终端分别运行，先启动发布再探测：

```powershell
# 终端1：持续发布测试视频；测完Ctrl+C结束本次发布。
.\tools\ffmpeg\windows\ffmpeg.exe -re -f lavfi -i 'testsrc2=size=320x240:rate=15' -c:v libx264 -preset ultrafast -tune zerolatency -g 15 -f flv rtmp://127.0.0.1/live/cam
```

```powershell
# 终端2：应识别到视频codec和宽高；所选FFmpeg构建需含libx264用于上面的自检。
.\tools\ffmpeg\windows\ffprobe.exe -v error -rw_timeout 15000000 -i rtmp://127.0.0.1/live/cam -select_streams v:0 -show_entries stream=codec_name,width,height -of json
```

结束本机发布后，再连接EVB测试，避免两个发布者争用同一stream key：

```powershell
.\.venv-cli\Scripts\python.exe -m ATS.main --scenario cli_smoke_rtmp --port COM10 --baudrate 2000000 --no-interactive-wifi --no-preview --no-problem-prompt
```

这是15秒保持、10秒heartbeat阈值的小场景，无FTP。关闭预览仍执行ffprobe和heartbeat。
先通过无预览版本，再去掉 `--no-preview` 验证ffplay窗口与断流重连。
本轮直接启动ffplay，不额外弹终端模拟器；手动关ffplay后会自动重连，结束ATS才停止监督。
`preview_required` 沿用基线，只影响异常日志级别，不是本轮新增的硬性失败开关。

## 8. 中断、报告与回归

正常Ctrl+C会尽力停止本次录像/推流，回收本次创建的工具进程，关闭串口/FTP，保存已有结果，返回130。
尚在启动检查阶段的中断可能没有用例报告；强制结束进程、断电、连续中断清理不等于可恢复的正常Ctrl+C。
板端断连时不能保证停止命令送达：检查run.log里的“未收到停止确认”，必要时现场确认板端状态。
RTMP正常停止未应答时写警告和结果详情，最终主判据没有改为强制stop-ack判FAIL。
外部启动的nginx不受ATS清理影响；你的其它ffplay也不会按进程名被杀掉。

| 退出码 | 含义 |
|---|---|
| 0 | 当前收集的用例无FAIL/ERROR；不等价于所有辅助文件均已下载 |
| 1 | 存在FAIL/ERROR |
| 2 | 配置/依赖/环境异常 |
| 130 | 用户中断 |

日志：`logs/<scenario>/<date>/<run_ts>/`；非normal报告：`logs/<scenario>/report/<date>/<run_ts>/`。
normal报告仍为 `reports/<date>/<run_ts>/`。本次没有重构目录体系。
终端中文乱码可尝试python的 `-X utf8`；文件日志和报告以UTF-8保存。

安装测试依赖并仅执行本轮测试：

```powershell
.\.venv-cli\Scripts\python.exe -m pip install -r ATS\requirements-cli-test.txt
.\.venv-cli\Scripts\python.exe -m pytest tests\windows_cli -q -rs
```

平台专属测试和缺少可执行工具的集成测试可SKIP，必须同时看 `-rs`；Windows分支模拟PASS不能代替实际COM/FTP/RTMP验收。
现有工程根目录未收录在快照中的旧测试不属于此次84项测试统计；用户工程已有旧测试应另外回归。
Ubuntu继续使用原虚拟环境和 `python -m ATS.main`；新增flags和smoke场景也可使用。
Ubuntu预览仍有ffplay画面窗口，但不再额外启动gnome-terminal/xterm，异常输出转到preview.log。

## 9. 现场验收和外部参考

逐项验收见 `../04_testing/windows_cli_acceptance.md`，尤其检查2Mbps串口、实际下载、断流失败及再次打开串口。
参考资料用于部署/API说明，不作为本交付的Windows实测证据：

- Python subprocess：https://docs.python.org/3/library/subprocess.html
- pySerial端口枚举：https://pyserial.readthedocs.io/en/latest/tools.html
- Windows键盘接口：https://docs.python.org/3/library/msvcrt.html
- FFmpeg构建来源：https://ffmpeg.org/download.html
- nginx Windows说明：https://nginx.org/en/docs/windows.html
- nginx-rtmp上游：https://github.com/arut/nginx-rtmp-module
- Windows防火墙配置：https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/configure
