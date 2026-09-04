# Phase 0 基线冻结记录

- Date: 2026-09-04
- Target branch: `new_arch`
- Source basis: 2026-09-04 最新 `all_source.txt` 源码快照
- Git commit: **PENDING_REAL_REPOSITORY_CAPTURE**
- Baseline tag: **PENDING_REAL_REPOSITORY_CAPTURE**

> 本文件区分“源码静态可确认事实”和“必须在真实仓库/EVB 环境执行的运行证据”。不得用静态阅读结果冒充真机 PASS。

## 1. 当前分层基线

```text
config/system.yaml + config/modules/*.yaml + config/scenarios/*.yaml
                              ↓
                       ScenarioManager
                prepare → tasks(loop) → cleanup
                              ↓
                            Runner
                 cycle / repeat / retry / depends
                              ↓
                            Module
                              ↓
                       Driver / Context
```

Phase 0 不改变该链路。

## 2. CLI 基线

当前 `ATS.main` 对外入口包括：

- `--scenario`
- `--config-dir`
- `--port`
- `--baudrate`
- `--format`
- `--wifi-ssid`
- `--wifi-password`
- `--no-interactive-wifi`
- `--output-dir`
- `-v/--verbose`
- `--list-modules`
- `--list-scenarios`
- `--dry-run`
- `--terminal`
- `--raw`

Phase 0 要冻结的关键命令：

```bash
python3 -m ATS.main --scenario normal
python3 -m ATS.main --scenario stress
python3 -m ATS.main --scenario video_integrity
python3 -m ATS.main --dry-run
python3 -m ATS.main --list-scenarios
python3 -m ATS.main --list-modules
```

### 2.1 退出码语义

源码静态基线：

| Exit code | 语义 |
|---:|---|
| 0 | 正常完成，且不存在 FAIL/ERROR；list/dry-run 成功也返回 0 |
| 1 | 测试流程完成，但结果中存在 FAIL 或 ERROR |
| 2 | 配置、依赖、Scenario 加载/执行入口等环境级错误；串口终端打开失败等也使用 2 |

该映射在 Phase 1 必须保持可兼容。

## 3. Scenario / task / cycle / repeat 基线

### 3.1 normal

```text
prepare:
  serial_init
  wifi_connect
  preclean
  ftp_ready
  preview_start

tasks:
  emmc
  photo
  video
  rtmp

cleanup:
  stop_stream
  preview_stop
  close_serial
```

- 无显式 loop 时按单 cycle 执行。
- task 顺序严格按 YAML 声明顺序。

### 3.2 stress

当前源码配置静态基线：

- `loop.enabled: true`
- `loop.count: 20`
- photo `repeat: 50`
- video `duration: 180`
- rtmp `duration: 600`

prepare / cleanup 与 normal 同类；tasks 顺序为：

```text
photo(repeat=50) → video(180s) → rtmp(600s)
```

> 注意：冻结的是 YAML 实际数据值，不以旧注释或历史文档里的次数替代。

### 3.3 video_integrity

- `prepare: []`
- task: `video_integrity`
- `cleanup: []`
- standalone 场景可不连接 EVB；具体输入目录/selection 由 scenario override 与 module config 合并。

### 3.4 Runner 语义

静态基线：

- cycle 从 1 开始。
- loop disabled：只执行一轮 tasks。
- count loop：达到 count 后结束。
- duration loop：达到时长边界后结束。
- task `repeat` 最小按 1 处理，每次 repeat 都走 module `setup → run(retry) → teardown` 生命周期。
- `task.duration` 只通过 Module 声明的 `duration_key` 映射到模块参数。
- ScenarioManager 在 `finally` 中执行 cleanup / context cleanup，属于必须保留的资源回收基线。

## 4. 日志 / 报告目录基线

当前目录语义：

```text
logs/<scenario>/<YYYY-MM-DD>/<run_ts>/
    ├── run.log
    └── serial.log
```

报告：

```text
normal:
  reports/<YYYY-MM-DD>/<run_ts>/

non-normal:
  logs/<scenario>/report/<YYYY-MM-DD>/<run_ts>/
```

问题记录：

```text
logs/<scenario>/problem/<run_ts>.log
```

显式 `--output-dir` 时，报告落到指定根目录下按日期/run_ts 分层。

报告格式继续包括：

- `result.json`
- `junit.xml`
- `report.html`

## 5. 业务判据冻结

Phase 0 **不修改**以下生产源码和判据：

| 模块 | 冻结内容 |
|---|---|
| photo | 继续使用当前拍照完成判据；FTP JPEG/大小校验保持现状，不因 UI 重写 |
| video | 继续使用当前录像启动/结束与辅助 FTP 大小校验逻辑 |
| rtmp | 主判据仍由 ffprobe 视频流探测 + RTMP heartbeat/monitor 共同提供；Preview 不作为主判据 |
| video_integrity | 继续复用 `VideoIntegrityModule` + `H265Validator` 的 decode/showinfo/trace_headers 诊断链，不复制算法 |

## 6. Linux 特定依赖清单与处理策略

| 当前依赖 | 当前位置/表现 | Phase 0 处理 | 后续策略 |
|---|---|---|---|
| `/dev/ttyUSB*`, `/dev/ttyACM*` | SerialConsole 自动候选口 | 保留并冻结 | **抽象**：Phase 4 `SerialPortProvider`，Windows 枚举 COM |
| `termios` / `tty` | `ATS/tools/serial_terminal.py` cbreak/恢复终端 | 保留并登记 | **替换/适配**：Phase 6 跨平台 Terminal UI/adapter；Windows 不直接使用 termios |
| `DISPLAY` | PreviewManager 判断是否可显示 | 保留并登记 | **替换/抽象**：桌面 GUI 下不把 DISPLAY 作为业务前提 |
| `bash while true` | PreviewManager ffplay 断流重连 wrapper | 保留并登记 | **替换**：Phase 4 Python 重连 worker |
| `os.setsid` / `os.killpg` | Preview/ffplay POSIX 进程组回收 | 保留并登记 | **抽象**：Phase 4 `ProcessController`，按平台回收进程树 |
| Linux terminal emulator | gnome-terminal/xterm/konsole/... | 保留并登记 | **替换/隔离**：GUI/平台层，不进入业务模块 |
| nginx-rtmp + systemd/apt | `RtmpServer` 只检查 1935；部署文档依赖 Ubuntu | 保留“1935 ready”语义 | **抽象**：Phase 7 RTMP Server Backend；RtmpModule 不感知 nginx.exe/systemd |
| `tools/ffmpeg/...` 相对 cwd | rtmp/preview/video_integrity 配置 | 保留并登记 | **抽象**：Phase 4 `ResourceLocator`，任意 cwd 可定位 runtime |
| `/usr/bin/ffplay` 等 Linux 常见路径 | PreviewManager fallback | 保留并登记 | **抽象**：ResourceLocator / runtime bundle |
| 主动模式 FTP + 防火墙 | RT-Thread FTP `pasv:false` | 协议保持 | **保留协议，平台化环境检查**：Windows Defender Firewall 在 Phase 7/8 验证 |

## 7. 新架构契约冻结位置

权威设计：

`docs/02_design/decision_record/ADR-011-UI与Windows演进架构契约.md`

冻结对象：

- TestService
- RunRequest / RunResult
- EventSink / EventBus
- CancellationToken
- InteractionProvider
- ResourceLocator
- Platform Services

## 8. 真实仓库必须执行的 Git 基线操作

### 8.1 先确认工作树

```bash
git switch new_arch
git branch --show-current
git status --short
git rev-parse HEAD
```

如果 `git status --short` 非空，**不要直接给旧 HEAD 打 tag**。先用：

```bash
git diff
git diff --cached
```

确认哪些修改属于当前应冻结版本，并按你的仓库规范提交后，再执行 tag。

### 8.2 建议 baseline tag

在目标工作树已经干净、且 HEAD 就是本次要冻结的版本后：

```bash
git tag -a gravity-ats-ui-win-phase0-baseline-20260904 \
  -m "Gravity ATS pre-UI/Windows Phase 0 baseline"

git show --no-patch --decorate gravity-ats-ui-win-phase0-baseline-20260904
```

如果需要共享远端：

```bash
git push origin gravity-ats-ui-win-phase0-baseline-20260904
```

> 是否 push 由你的仓库策略决定；Phase 0 至少要求本地 tag 与 commit 可追溯。

## 9. 真实运行基线记录

建议建立目录：

```bash
mkdir -p docs/04_testing/evidence/phase0_20260904
```

先记录无板命令：

```bash
python3 -m ATS.main --list-scenarios \
  > docs/04_testing/evidence/phase0_20260904/list-scenarios.txt 2>&1
echo $? >> docs/04_testing/evidence/phase0_20260904/list-scenarios.txt

python3 -m ATS.main --list-modules \
  > docs/04_testing/evidence/phase0_20260904/list-modules.txt 2>&1
echo $? >> docs/04_testing/evidence/phase0_20260904/list-modules.txt

python3 -m ATS.main --dry-run \
  > docs/04_testing/evidence/phase0_20260904/dry-run.txt 2>&1
echo $? >> docs/04_testing/evidence/phase0_20260904/dry-run.txt
```

再在对应环境运行并保留输出/日志：

```bash
python3 -m ATS.main --scenario video_integrity
python3 -m ATS.main --scenario normal
python3 -m ATS.main --scenario stress
```

每次运行后记录：

- 命令
- 开始/结束时间
- exit code
- run.log 路径
- serial.log 路径（适用时）
- result.json / junit.xml / report.html 路径
- 实际 task 顺序、cycle/repeat
- 是否存在残留进程/串口占用

## 10. Runtime Evidence Status

| 验证项 | 静态源码确认 | 真实运行证据 |
|---|---|---|
| `--list-scenarios` | PASS | PENDING |
| `--list-modules` | PASS | PENDING |
| `--dry-run` | PASS | PENDING |
| `video_integrity` | PASS（入口/场景存在） | PENDING |
| `normal` | PASS（编排可确认） | PENDING |
| `stress` | PASS（编排可确认） | PENDING |
| Git baseline commit/tag | N/A | PENDING |

只有 PENDING 全部关闭后，Phase 0 才能整体判定 PASS。
