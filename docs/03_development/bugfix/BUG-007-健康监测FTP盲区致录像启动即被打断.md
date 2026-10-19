# BUG-007：健康监测 FTP 盲区 + 恢复标志未清，致录像启动约 0.5s 即被打断

## Problem

recovery_validation 真机（2026-10-08，日志 `logs/recovery_validation/20261008/20261008_164543`）cycle 37，
video[hd1080p_2]（配置 `duration: 20`）在 `dfs_video_start` 后录像只持续约 **54ms**（拍 0 帧，
`Record Stop Success: total frames = -1`），随后被补发 `dfs_video_stop` 终止，产物 0KB，
被判 `文件过小 0KB < 100KB` FAIL。板子本身健康——任务返回后的安全点自检
`串口自检通过 / 健康确认通过，继续测试`，且上一个视频 hd1080p_1 在 09:25:34 刚正常录满 22.5s / 40950KB。

## 完整时间线（serial.log + run.log 交叉）

| 时刻 | 事件 | 证据 |
|------|------|------|
| 09:25:53.635 | video[hd1080p_2] 开始，日志「录像 size 设置命令: cam_set video hd1080p 2」 | run.log L14259-14260 |
| 09:25:53 → 09:26:43 | `_list_video_dirs(ftp)` 走 WiFi/TCP 做 FTP LIST `/emmc/VIDEO`（cycle 37 已积累约 440 目录），**阻塞约 50s，期间串口零 RX** | video.py L99 |
| 09:26:34.623 | watchdog 判定 **SUSPECTED**：`超过 60s 无串口活动（last_rx=09:25:34）` → `runtime_control.request_recovery()` | run.log L14261 |
| 09:26:43.936 | FTP LIST 结束，才真正 TX `cam_set video hd1080p 2` | serial.log L353973 |
| 09:26:44.476 | TX `dfs_video_start`，启动成功（`Gravity_XR Record Start`） | serial.log L353980/354149 |
| 09:26:44.954 | `runtime_control.wait(20)` **立即返回**（恢复标志早已在 09:26:34 置位）→「录像等待期间收到板卡恢复请求，提前结束录像等待」 | run.log L14263 |
| 09:26:44.954 | TX `dfs_video_stop` | serial.log L354151 |
| 09:26:45.001 | `Record Stop Success: total frames = -1`（0 帧） | serial.log L354156 |
| 09:26:47.839 | FAIL `文件过小 0KB < 100KB` | run.log L14267 |
| 09:26:49.056 | 安全点自检 `串口自检通过` → `健康确认通过，继续测试`（证明板子一直健康） | run.log L14269-14270 |

## Root Cause（两个缺陷叠加）

### 缺陷 A：健康监测存在「FTP 盲区」

`BoardHealthMonitor` 只订阅 UART 串口 RX（`console.add_listener(mon.on_rx)`，见
`ATS/application/board_health_monitor.py`），`last_rx` 只在收到串口字节时更新。
而 `video._run_once` 在发 `cam_set` **之前**先做 `before = self._list_video_dirs(ftp)`
（video.py L99），这是纯 WiFi/TCP 路径（`FtpClient._list_entries`），**不产生任何串口活动**。

当 `/emmc/VIDEO` 目录累积变多（cycle 37 已有约 440 个目录），单次 FTP LIST 阻塞可达 ~50s，
超过 `inactivity_timeout: 60s` 与「上一个视频结束（last_rx=09:25:34）」之间的剩余窗口，
于是 **watchdog 在板子正常 serve FTP 时误判「无串口活动 → 无响应」**。

> 本质：`inactivity_timeout` 用「串口静默」作为「整板无响应」的代理，但 FTP LIST /
> 下载等 WiFi 路径操作同样会占用板子 CPU 且不产生串口输出，属于监测盲区。

### 缺陷 B：恢复标志生命周期过长，跨 Task 残留

`runtime_control.request_recovery()` 置位后，`clear_recovery()` **只在**以下时机触发：
`monitor.probe() 成功`、`monitor.mark_healthy()`、`monitor.start()/stop()` —— 全部发生在
**安全点**（即 `_recovery_checkpoint`，任务返回后由 Runner 调用，见 `ATS/core/runner.py` L229-268）。

时间线里，SUSPECTED 在 09:26:34 置位，但此刻 video 模块还在 `_list_video_dirs` 阻塞中，
**没有任何清除机会**。等模块真正发出 `cam_set`（能回显即证明板子活着）、`dfs_video_start`
成功后进入 `runtime_control.wait(duration)` 时，旧标志仍在 → `wait()` 第一轮循环就
`if self.is_recovery_requested(): return True`（`ATS/application/runtime_control.py` L52），
录像被立即打断。

> 注意：板子能回显 `cam_set video hd1080p 2` / `dfs_video_start` 本身已事实推翻「无响应」，
> 但代码没有在命令成功回显处清标志，标志一直「污染」到 wait。

### 为什么是「0.5s」而不是 20s

`wait()` 不是 `time.sleep`，它先查恢复标志；标志在等待前已误置，故 `Record Start`
(09:26:44.947) → `Record Stop`(09:26:45.001) 仅约 54ms。观感上的「3s」来自
`dfs_video_start` 回显到 stop 的跨行时间跨度，实际录像窗口远小于 3s。

## 定性

- **不是固件 bug、不是板卡死机**：后续主动健康 probe 一次通过；hd1080p_1 上一轮正常录满。
- **是 ATS 侧的监测盲区 + 恢复标志生命周期问题**，属脚本侧，需 Code Agent 修复。

## Solution（方案 A + B 已定稿，Code Agent 待执行；C 可选）

### 决定性发现：那段 50s 阻塞的 FTP LIST 是死代码

复核 `ATS/modules/video.py` 后确认，触发盲区的 `_list_video_dirs` 调用点（L99）的
返回值 `before` **在整个模块内没有任何后续使用**：

```python
99:  before = set(self._list_video_dirs(ftp))   # 结果从未被读取
139: m2 = re.search(r".../Video_...\.h265", r.clean)  # 真正视频路径从串口缓冲扫
223: m2 = re.search(r".../Video_...\.h265", r.clean)  # no_ftp 分支同样扫串口缓冲
```

- `before` 只传给 `_wait_new_dir(ftp, before, timeout)`（L237），而 `_wait_new_dir` **全模块零调用**。
- 真正 `video_path` 来自串口累积缓冲 `r.clean` 的正则匹配（L139/L223），与目录 diff 无关。

即：这是早期「FTP 目录 diff 找新视频目录」的实现残留，后被「直接扫串口缓冲完整路径」取代，
但 L99 的 LIST 未删净。**每次录像前白白 LIST 一次 `/emmc/VIDEO`，目录一多阻塞 50s，
且恰好落在 watchdog 串口盲区内。**

### 方案 A（根治，必做）：删除无用 FTP 前置 LIST + 死代码

`ATS/modules/video.py`：

1. 删 L99：`before = set(self._list_video_dirs(ftp))`。
2. 删死方法 `_list_video_dirs`（L230-235）与 `_wait_new_dir`（L237-245），删除 L99 后二者零引用。
3. 保留 `_VIDEO_DIR` 常量（L139/L223 仍用）。

效果：`_run_once` 中 FTP 首次出现推迟到录像**完成之后**的 `ensure_ftp(force=True)`（L145），
录像窗口内不再有 WiFi/TCP 静默段，直接消除盲区触发源。这是唯一真正对症的改法。

### 方案 B（兜底防御，建议做）：`dfs_video_start` 成功回显后清一次已失效标志

即便 A 落地，仍可能出现「某种静默操作 + 残留恢复标志」组合，加一行防御堵住。

`ATS/modules/video.py` 两个分支（有下载 L113-115、无下载 L199-201），在
`exec_async(VIDEO_START_COMMAND)` 成功 `r.success` 之后、进入 `runtime_control.wait()`
**之前**，加：

```python
if r.success:
    # dfs_video_start 已成功回显，说明控制链路事实健康；
    # 清掉可能残留的 SUSPECTED 恢复标志（如录像前 FTP/网络静默误触发的）。
    # 安全性：wait() 期间 watchdog 仍按 1s 步长实时检测，真死机会重新置位。
    from ..application import runtime_control
    runtime_control.clear_recovery()
```

安全性论证：`clear_recovery()` 只清「进入等待前」的残留标志，不影响 `wait()` 内部实时检测
（watchdog 1s 步长，真死机重新置位 → `wait(step=1)` 照样提前返回），故**不会掩盖真恢复**。

### 方案 C（可选，改动面大）：让 Monitor 感知 FTP 事务

给 `BoardHealthMonitor` 加轻量 `touch()`，在 `ensure_ftp` / `FtpClient.download` 开始/结束时
刷新 `last_rx`。彻底消除「WiFi/TCP 事务 = 串口静默 = 疑似无响应」这一误判类别，但**触及
ADR-016 能力边界**（原文明确定义「只识别串口静默型无响应」），属设计变更，需补 ADR 修订 + 单测。

**建议顺序**：先做 A（+B 兜底），真机复现确认消失；C 视后续是否仍观测到「FTP 下载静默导致
无害 SUSPECTED」（`next_step.md` L62 已有历史记录）再评估。

### 约束（架构红线，改动时必守）

- 业务模块（video）不得直接执行 recovery；只能「提前结束等待」或「清除已事实失效的标志」，
  恢复决策与执行仍归 Runner / RecoveryCoordinator。
- 不在 listener 回调里做 IO / sleep / exec。
- 不改固件、不改固件命令协议（ADR-011）。

## Verification（方案 A+B 落地后由 Code Agent 执行并回填）

- [ ] 复现：清空后重跑 `recovery_validation`，让 `/emmc/VIDEO` 重新累积数百目录，确认 cycle 37 之后不再出现 `文件过小 0KB` / `Record Stop Success: total frames = -1`。（**待真机**）
- [ ] 回归：正常录像（20s/180s）走满时长，`Video recording completed successfully.` 正常出现，下载校验正常。（**待真机**）
- [x] 离线单测 A：删除 L99/死方法后模块无残留引用（`before`/`_list_video_dirs`/`_wait_new_dir` 零调用），既有 mock 用例通过。（`tests/test_video_bug007.py::test_A_dead_methods_removed`，2026-10-09）
- [x] 离线单测 B：mock「`dfs_video_start` 成功但 wait 前残留恢复标志」→ 断言录像不再被打断（验证 B 生效）。（`test_B_stale_recovery_flag_cleared_before_wait`，2026-10-09）
- [x] 离线单测 B 反例：mock「wait 期间新置位恢复请求」→ 断言仍提前返回（验证 B 不掩盖真恢复）。（`test_B_fresh_flag_still_breaks_wait`，2026-10-09）

> 落地：devlog `20261009_1051_BUG007_录像前FTP死代码删除与恢复标志清理.md`；全量 51 测试全过（48 旧 + 3 新）。

## 关联

- 设计：`../02_design/decision_record/ADR-016-板卡健康监测与可插拔恢复机制.md`
  （cooperative cancellation §5；Monitor 能力边界「只识别串口静默型无响应」）
- 真机日志：`logs/recovery_validation/20261008/20261008_164543/`（serial.log L353973-354156、run.log L14255-14271）
- 已知问题：`../../05_handoff/known_issue.md`「脚本侧已知问题」表
- 待办：`../../05_handoff/next_step.md`
- 相关实现：`ATS/application/board_health_monitor.py`、`ATS/application/runtime_control.py`、
  `ATS/core/runner.py`、`ATS/modules/video.py`、`ATS/drivers/ftp_client.py`
