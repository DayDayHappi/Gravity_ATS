# 接口规格（Interface Spec）

> 配置格式、CLI、文件格式的约定。只描述规格，不写实现代码。

## 1. 配置三层体系

| 层 | 文件 | 放什么 |
|----|------|--------|
| system | `config/system.yaml` | 串口、WiFi 网络环境（ssid/password 属这里）、pc.ip、runner、report |
| modules | `config/modules/*.yaml` | 模块业务参数（photo_modes、video_duration、stream_duration、heartbeat_timeout、preview 播放器参数…） |
| scenarios | `config/scenarios/*.yaml` | 流程 / 组合 / 循环（prepare/tasks/loop/cleanup/preview.enabled） |

**场景结构**：

```yaml
scenario:
  name: stress
  prepare: [serial_init, wifi_connect, preclean, ftp_ready, preview_start]
  preview: {enabled: true}
  loop: {enable: true, count: 3}
  tasks:
    - {module: photo, repeat: 50}
    - {module: video, duration: 180}
    - {module: rtmp,  duration: 600}
  cleanup: [stop_stream, close_serial, preview_stop]
```

- `task.repeat`：单任务重复 N 次（Runner 循环，模块内不写 for）。
- `task.duration`：经模块 `duration_key` 覆盖持续参数（video→video_duration、rtmp→stream_duration）。
- `loop`：整轮循环（count 次数 / duration 时长 / 都缺省=无限）。
- `preview.enabled`：是否启动 RTMP 画面观察窗口（ADR-010），生命周期跨整个 Scenario（含 loop 多轮），不随单次 rtmp task 重启。
- `prepare`/`cleanup` 内置动作：serial_init、wifi_connect、preclean、ftp_ready、preview_start、stop_stream、close_serial、preview_stop。

## 2. CLI

```bash
python3 -m ATS.main --scenario <name>      # 主入口（默认 normal）
python3 -m ATS.main --list-scenarios       # 列场景
python3 -m ATS.main --list-modules         # 列模块
python3 -m ATS.main --dry-run              # 校验配置依赖（不连板子）
python3 -m ATS.main --no-interactive-wifi  # 非交互连 WiFi
python3 -m ATS.main --port /dev/ttyUSB0    # 指定串口
python3 -m ATS.main --terminal             # 交互式串口终端
python3 -m ATS.main --format               # 强制格式化 eMMC
```

> 注意：`--modules` / `--skip` 已移除，`--scenario` 成为主入口。`test_config.yaml` 已删除。

## 3. 退出码

| 码 | 含义 |
|----|------|
| 0 | 全部通过 |
| 1 | 有失败用例 |
| 2 | 环境/配置错误 |

## 4. 文件格式

- **串口日志**：`logs/<ts>/serial.log`，每字节带毫秒时间戳，含 ANSI 原始字节。
- **报告**：`result.json`（机器可读）+ `junit.xml`（CI）+ `report.html`（人读）。
- **输出目录**：normal → `logs/<ts>/` + `reports/<ts>/`；stress/aging → `logs/<场景>/logs/<ts>/` + `logs/<场景>/report/<ts>/`。
- **板端产物**：`/emmc/PIC/<时间戳目录>/Image_*.jpg`、`/emmc/VIDEO/<时间戳目录>/Video_*.h265`（大写目录，与手册不同）。

## 5. 敏感信息

支持 `${ENV_VAR}` 从环境变量读取（如 WiFi 密码）。
