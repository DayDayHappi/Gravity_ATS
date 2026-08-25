# 构建与运行环境（Build Environment）

## 1. 环境要求

- **OS**：Linux x86_64（Ubuntu 20.04+/22.04；Windows 不支持串口终端 termios/tty）
- **Python**：3.8+
- **第三方依赖**：`pyserial`、`pyyaml`（仅 2 个）；`jinja2`（HTML 报告）
- **运行依赖 fliesshow**：RTMP 推流验证 + preview 画面观察需 `ffmpeg`/`ffprobe`/`ffplay`（见第 3 节）

## 2. 依赖安装

```bash
sudo apt install -y python3-serial ffmpeg
# pyserial 离线安装见 ../ATS/README.md 附录 A
```

## 3. 内置工具（离线可用）

- ffmpeg/ffprobe/ffplay 是可执行文件，属 **运行依赖**（RTMP 推流验证用 ffprobe 实时探测、preview 观察用 ffplay）。**仓库不再随附**（`tools/` 不在版本控制内），需自备：`sudo apt install ffmpeg`，或将已有的 `tools/ffmpeg/`（BtbN 静态构建，零依赖）拷贝到对应路径。
- `preview.yaml` 的 `ffplay_path` 指向 `tools/ffmpeg/ffplay`，若未安装则跳过画面观察（判据仍由 ffprobe + heartbeat 给出，不影响结果）。
- RTMP 服务端用系统 nginx-rtmp（`sudo apt install nginx libnginx-mod-rtmp`），脚本只查就绪不启停。

## 4. 运行

```bash
cd /home/gravity/AutoTestScripts_JX009
python3 -m ATS.main --scenario normal          # 完整测试
python3 -m ATS.main --dry-run                  # 校验配置（不连板子）
python3 -m ATS.main --terminal                 # 串口终端调试
```

纯 Python 脚本，无需编译。

## 5. 新机器环境准备

```bash
./migrate.sh        # 一键检查/装依赖/校验（幂等，详见 archive/迁移指南.md）
```

- **串口权限**：用户加入 dialout 组（`sudo usermod -aG dialout $USER` 后重新登录）。
- **防火墙**：放行 1024-65535 高端口（FTP 主动模式 + RTMP 1935）。
- **网络**：EVB 能路由到 PC 的 IP（多网卡注意 `pc.ip` 写死）。
