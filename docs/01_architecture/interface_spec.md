# 接口规格（Interface Spec）

> 配置格式、CLI、文件格式的约定。只描述规格，不写实现代码。

## 1. 配置三层体系

| 层 | 文件 | 放什么 |
|----|------|--------|
| system | `config/system.yaml` | 串口、WiFi 网络环境（ssid/password 属这里）、pc.ip、runner、report、上下电控制（power_switch） |
| modules | `config/modules/*.yaml` | 模块业务参数（photo_modes、video_duration、stream_duration、heartbeat_timeout、bitrate、preview 播放器参数、detect_strings…） |
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
- `task.override`：经 Runner `params` 合并进模块 `self.config`，覆盖模块默认参数（如 `override: {bitrate: 18000000}`）。
- `loop`：整轮循环（count 次数 / duration 时长 / 都缺省=无限）。
- `preview.enabled`：是否启动 RTMP 画面观察窗口（ADR-010），生命周期跨整个 Scenario（含 loop 多轮），不随单次 rtmp task 重启。
- `prepare`/`cleanup` 内置动作：serial_init、wifi_connect、preclean、ftp_ready、preview_start、stop_stream、close_serial、preview_stop、power_switch_init、power_switch_close、health_monitor_start、health_monitor_stop。
- `detect_strings`（ADR-014）：video/rtmp 的 modules yaml 字段，值为 `drivers/detect_strings.py` 里 `DetectString.key` 的列表（如 `[tt_error]`）；未配置/空则不检测，正则本体不进 yaml。

**`power_switch` 段（ADR-015，system.yaml，与 `serial` 同级）**：

```yaml
power_switch:
  enabled: false        # 默认关，未启用零影响（可选能力增量语义）
  baudrate: 115200      # 控制器串口波特率（与 EVB 的 2000000 不同）
  reboot_delay: <值>    # 断电→上电间隔（秒），需满足板子电容放电；默认值待真机确定 TODO-CONFIRM
```

- 协议字节/判据/超时**不进 yaml**（ADR-011：协议属固件契约，留 `drivers/power_commands.py`），yaml 只存开关与硬件参数。
- 探测与串口长连接挂 `prepare`/`cleanup`：`power_switch_init`（enabled 时探测，候选端口排除 EVB 端口，成功存 `ctx.power_switch`）/ `power_switch_close`（幂等关闭）；启用时对候选串口发上电帧区分控制器与 EVB。

**`board_health` 段（ADR-016，`config/modules/board_health.yaml`，Scenario 生命周期级能力参数，沿用 PreviewManager 模式，已实施·待真机）**：

```yaml
# config/modules/board_health.yaml（Monitor 参数，非 Scenario Task）
check_interval: <值>        # 健康状态检查间隔（秒）
inactivity_timeout: <值>    # last_rx 超时进 SUSPECTED 阈值（秒），须用真实 stress 日志校准，不凭经验拍死
confirm_failures: <值>      # 主动 health_check 连续失败多少次进 UNRESPONSIVE
confirm_interval: <值>      # 主动确认间隔（秒）
```

**Scenario Recovery Policy（ADR-016，`config/scenarios/*.yaml`，测试策略，已实施·待真机）**：

```yaml
health_monitor:
  enabled: false            # 是否启用板卡健康监测（默认关）
recovery:
  enabled: false            # 是否启用自动恢复（默认关）
  backend: power_cycle      # 恢复后端（首实现 power_cycle）
  max_attempts: <值>        # 最大恢复次数，超限走 on_exhausted
  after_recovery: retry_current_task   # 恢复成功后对当前 task 的处理（第一阶段建议 retry_current_task）
  on_exhausted: abort_scenario         # 恢复次数耗尽（建议 abort_scenario）
  restore: [board_ready, wifi_connect, preclean, ftp_ready]  # 环境重新收敛 action 列表（no_network 只需 [board_ready, preclean]）
```

- `system.yaml` 只描述「当前机器有什么硬件能力」（`power_switch.enabled`/`baudrate`/`reboot_delay`）；**禁止**把「死机后是否重启、最大恢复次数、当前 Task 是否 retry」等策略放进 `system.yaml` 的 `power_switch` 段。
- **禁止静默 fallback**：`recovery.enabled=true` 且 `backend=power_cycle` 但 `power_switch.enabled=false` 或探测失败时，应在正式 tasks 前明确报 `RecoveryBackendUnavailable`。
- 旧 Scenario 未声明 `health_monitor`/`recovery` 时默认 disabled，行为与当前版本完全一致。

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
python3 -m ATS.main --power-stress         # 串口上下电控制模块独立压测(TC-PS-001，仅控制器不接EVB)
```

> 注意：`--modules` / `--skip` 已移除，`--scenario` 成为主入口。`test_config.yaml` 已删除。

## 3. 退出码

| 码 | 含义 |
|----|------|
| 0 | 全部通过 |
| 1 | 有失败用例 |
| 2 | 环境/配置错误 |

## 4. 文件格式

- **串口日志**：`serial.log`，每字节带毫秒时间戳，含 ANSI 原始字节（目录由 `logger.init_logger(log_root)` 决定，`log_root` 由 main.py 按「场景/日期」拼好）。
- **上下电控制器日志**：`power_switch.log`（ADR-015），控制器通信 4 字节二进制帧的独立留痕（`[HH:MM:SS.mmm] TX>/RX< A0 01 03 A4`，hex 大写），与 `serial.log` 分离；**懒加载**，`power_switch.enabled=false` 或未走 power 路径时不产生该文件。
- **报告**：`result.json`（机器可读）+ `junit.xml`（CI）+ `report.html`（人读）。
- **输出目录**（场景/日期/运行时间戳三级分层，date=`%Y%m%d`，run_ts=`%Y%m%d_%H%M%S`）：
  - 日志（所有场景）：`logs/<场景>/<date>/<run_ts>/`。
  - 报告：normal → `reports/<date>/<run_ts>/`；非 normal → `logs/<场景>/report/<date>/<run_ts>/`。
  - 问题记录（所有场景）：`logs/<场景>/problem/<run_ts>.log`（不按天打散）。
- **板端产物**：`/emmc/PIC/<时间戳目录>/Image_*.jpg`、`/emmc/VIDEO/<时间戳目录>/Video_*.h265`（大写目录，与手册不同）。

## 5. 敏感信息

支持 `${ENV_VAR}` 从环境变量读取（如 WiFi 密码）。
