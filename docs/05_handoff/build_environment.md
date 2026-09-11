# 构建与运行环境（Build Environment）

> 本文档是**环境/移植的权威说明**。迁移到新 Ubuntu PC 时，配合仓库根目录 `migrate.sh` 使用（幂等，一键检查依赖）。
> 详细迁移流程见 `archive/迁移指南.md`。版本：2026-09-11，分支 `new_arch`。

## 1. 环境要求

- **OS**：Linux x86_64（Ubuntu 20.04+ / 22.04；Windows 不支持串口终端 termios/tty）
- **Python**：3.8+
- **第三方依赖（必需）**：`pyserial`、`pyyaml`（仅 2 个）
- **第三方依赖（可选）**：`jinja2`（HTML 报告模板；缺失则 HTML 退化为基础表格，不影响测试结果）
- **运行时工具（RTMP/preview 需要）**：`ffmpeg`/`ffprobe`/`ffplay`

## 2. 依赖安装

```bash
# 方式 A（推荐，规避 PEP 668 限制）
python3 -m venv .venv && source .venv/bin/activate
pip install pyserial pyyaml

# 方式 B（系统级）
sudo apt install -y python3-serial python3-yaml
```

`migrate.sh` 会自动尝试 `pip3 install --user pyserial pyyaml`，失败时提示 venv / `--break-system-packages`。

## 3. 内置工具（离线可用，但**不受 git 跟踪**）

- `tools/ffmpeg/{ffmpeg,ffprobe,ffplay}` 为 BtbN 静态构建（零依赖，约 440MB），属**运行依赖**：
  - RTMP 推流验证用 `ffprobe` 实时探测（主判据）
  - preview 画面观察用 `ffplay`
- **`.gitignore` 忽略 `tools/`**，因此 clone/新机器上不会自动出现，必须从旧机器**单独拷贝 `tools/` 目录**（tar 打包或整目录复制都要带上）。
- 缺失后果：RTMP 场景判据缺失、preview 跳过（`preview.yaml` 的 `ffplay_path` 指向 `tools/ffmpeg/ffplay`，缺失则跳过画面观察）。
- 补齐方式：① 从旧机器拷 `tools/`；② 或 `sudo apt install ffmpeg` 后，改 `config/modules/*.yaml` 里 `ffmpeg_path`/`ffprobe_path`/`ffplay_path` 指向系统路径。

## 4. 运行

```bash
cd /path/to/AutoTestScripts_JX009
python3 -m ATS.main --scenario normal          # 完整测试
python3 -m ATS.main --list-scenarios           # 列出可用场景
python3 -m ATS.main --dry-run                  # 校验配置（不连板子）
python3 -m ATS.main --terminal                 # 串口终端调试
```

纯 Python 脚本，无需编译。CLI 主入口为 `--scenario <name>`（旧的 `--skip`/`--modules` 已移除）。

## 5. 新机器环境准备

```bash
./migrate.sh        # 一键检查/装依赖/校验（幂等，详见 archive/迁移指南.md）
```

- **串口权限**：用户加入 dialout 组（`sudo usermod -aG dialout $USER` 后重新登录）。
- **防火墙**：放行 1024-65535/tcp 高端口（FTP 主动模式 + RTMP 1935）。
- **RTMP 服务端**：系统 nginx-rtmp（`sudo apt install nginx libnginx-mod-rtmp`），脚本只查就绪不启停。
- **网络**：EVB 能路由到 PC 的 IP；多网卡时把 `config/system.yaml` 的 `pc.ip` 从 `"auto"` 写死为 EVB 同网段 IP，避免自动探测选错。
- **配置三层**：环境 → `config/system.yaml`；模块参数 → `config/modules/*.yaml`；流程 → `config/scenarios/*.yaml`（旧的 `test_config.yaml` 已拆分废弃）。

## 6. 迁移要点（区别于旧版本）

| 旧说法 | 当前实际 |
|--------|---------|
| `ATS/config/test_config.yaml` | 已拆为 `system.yaml` + `modules/*.yaml` + `scenarios/*.yaml` |
| `--skip rtmp` / `--modules` | 已移除，主入口 `--scenario <name>` |
| 报告路径 `reports/<ts>/` | 按场景/日期分层：normal→`reports/<日期>/`，非 normal→`logs/<场景>/report/<日期>/` |
| video 分辨率裸档位（`1080p`/`3k`） | 已改为组合 ID（`sd1080p_0`/`3k_2` 等，定义在 `drivers/video_commands.py`） |

完整迁移步骤、FAQ、验证清单见 `archive/迁移指南.md`。
