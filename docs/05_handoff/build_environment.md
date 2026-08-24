# 构建与运行环境（Build Environment）

## 1. 环境要求

- **OS**：Linux x86_64（Ubuntu 20.04+/22.04；Windows 不支持串口终端 termios/tty）
- **Python**：3.8+
- **第三方依赖**：`pyserial`、`pyyaml`（仅 2 个）；`jinja2`（HTML 报告）

## 2. 依赖安装

```bash
sudo apt install -y python3-serial ffmpeg
# pyserial 离线安装见 ../ATS/README.md 附录 A
```

## 3. 内置工具（离线可用）

- ffmpeg/ffprobe/ffplay 全在 `tools/ffmpeg/`（BtbN 静态构建，零依赖）。
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
