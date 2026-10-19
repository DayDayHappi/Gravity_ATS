# Windows CLI 启动指南（feature/windows-cli）

> 本文件是 `feature/windows-cli` **分支专属**运行指南，短期不合入 `new_arch`。
> Linux 运行方式见主线 [build_environment.md](build_environment.md)。
> 本文是 Windows 下唯一可信的启动入口说明，接手者照此跑通即可，不必读 Linux 文档。

## 1. 前置环境

| 依赖 | 现状 | 说明 |
|------|------|------|
| Python | `.venv-cli`（Python 3.13.15） | 已装 `pyserial 3.5` + `pyyaml`，直接用其解释器 |
| ffmpeg 套件 | winget Gyan.FFmpeg 9.0.1（ffmpeg/ffplay/ffprobe 已在 PATH） | `ResourceLocator.find_tool()` 找不到 `tools/ffmpeg/` 时会回退 PATH 命中 |
| RTMP 服务端 | nginx-rtmp-win32-dev（监听 1935） | 见第 3 节，未就绪只跳过 preview，不影响 photo/video 判据 |
| 防火墙 | 规则 `Gravity ATS CLI FTP - Board101` 已放行 `192.168.1.0/24` | 见第 4 节「常见问题」 |

> `.venv-cli` 目录**未被 git 跟踪、也未被 `.gitignore` 忽略**（游离本地目录）。换机器后需自行重建：
> TODO-CONFIRM 是否补 `.gitignore` 规则或提供 venv 重建说明。

## 2. 启动命令

正确入口（**不要用 `python3`**，见下方警告）：

```powershell
# 完整压测（最常用）
.\.venv-cli\Scripts\python.exe -m ATS.main --scenario stress --no-interactive-wifi

# 其他变体
.\.venv-cli\Scripts\python.exe -m ATS.main --dry-run            # 校验配置，不连板子
.\.venv-cli\Scripts\python.exe -m ATS.main --list-modules       # 列模块
.\.venv-cli\Scripts\python.exe -m ATS.main --list-scenarios     # 列场景
.\.venv-cli\Scripts\python.exe -m ATS.main --terminal           # 串口终端调试
```

**警告**：Windows 下 `python3` 会被 `WindowsApps\python3.exe`（Microsoft Store 空壳别名）劫持，
报 `Python was not found...`。必须用 `.venv-cli\Scripts\python.exe`。

也可先激活再跑：

```powershell
.\.venv-cli\Scripts\Activate.ps1
python -m ATS.main --scenario stress --no-interactive-wifi
```

## 3. 运行前检查

1. **串口**：EVB 上电并插 USB；`serial.port: auto` 自动探测 COMx（run.log 会打印候选端口与命中结果）。
2. **电源控制器（可选）**：未插控制器时 `power_switch_init` 打 WARN 跳过，不影响 photo/video 测试。
3. **RTMP 服务端**：跑含 rtmp 的场景前需 nginx-rtmp 监听 1935，否则 `preview_start` 报
   `1935 端口未监听` 并跳过画面观察（判据仍由 ffprobe + heartbeat 给出，不影响结果）。
   TODO-CONFIRM：nginx-rtmp-win32 的安装路径与启动命令需人工确认（磁盘 `C:\`/`D:\` 未检索到 nginx 目录）。
4. **防火墙**：确认规则 `Gravity ATS CLI FTP - Board101` 的 `RemoteAddress = 192.168.1.0/24`（网段，非单 IP）。

## 4. 常见问题

| 现象 | 根因 | 处理 |
|------|------|------|
| `python3` 报 `Python was not found` | Store 别名劫持 | 用 `.venv-cli\Scripts\python.exe` |
| photo 每项 ~68s、`FTP list 失败: timed out`、`未列出 jpg 辅助验证`、`photos/` 空 | 防火墙规则 `RemoteAddress` 锁死旧 EVB IP，而板子 IP 由 DHCP 漂移 | 改规则 `RemoteAddress` 为网段 `192.168.1.0/24`（需管理员 PowerShell，普通 shell 报 `System Error 5`），详见 [排查报告](../03_development/archive/Windows_CLI_FTP主动模式超时_排查与解决报告.md) |
| `power_switch_init: 无候选串口，跳过` | 未插电源控制器 | 正常降级，忽略 |

## 5. 关联文档

- 分支状态：[windows_cli_status.md](windows_cli_status.md)
- 分支待办：[windows_cli_next_step.md](windows_cli_next_step.md)
- 移植设计：[../02_design/windows_cli_port_plan.md](../02_design/windows_cli_port_plan.md)
- FTP 超时排查：[../03_development/archive/Windows_CLI_FTP主动模式超时_排查与解决报告.md](../03_development/archive/Windows_CLI_FTP主动模式超时_排查与解决报告.md)
