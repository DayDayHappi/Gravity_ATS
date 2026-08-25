# ADR-010：PreviewManager 单例播放器（RTMP 画面观察与 Task 解耦）

## Background

当前 `rtmp` 模块（`ATS/modules/rtmp.py`）在 `run()` 内直接管理 ffplay 画面确认：查找 ffplay → 起独立终端窗口或 subprocess 直启 → teardown 视启动方式决定是否 kill。stress 场景 `loop.count=20` 时每轮 cycle 都执行一次 rtmp task，即每轮都新起一个 ffplay 窗口/进程；终端窗口模式下 teardown 不 kill（历史决策，见 20260817 devlog：窗口生命周期独立于脚本），窗口逐轮累积不回收，长时间 stress 下窗口数与资源占用不可控。播放器生命周期与 rtmp 模块（Task 级）强耦合。

## Problem

1. ffplay 启动/关闭绑定在 rtmp 模块的 `run()`/`teardown()`（Task 生命周期），loop 多轮时窗口重复创建。
2. rtmp 模块承担「推流验证」+「画面展示」两个职责，边界不清，违反 ADR-007 模块红线的精神（模块应只做一次测试动作，画面展示与判据无关）。
3. 播放目标是 EVB 实时推的 RTMP 流（非文件回放），观察目的（延时/首帧/卡顿/推流恢复）与判据（ffprobe+heartbeat）是两件事，硬绑在一起不利于独立演进（如未来加 LatencyMonitor）。

## Decision

1. **新增 PreviewManager，落位 `ATS/drivers/preview_manager.py`**（驱动层，与 `RtmpReceiver`/`RtmpServer` 同级——三者都是「PC 端本地进程/服务管理器」，不新增 `core/` 或 `services/` 目录）。
   - 接口：`start()` / `stop()` / `restart()` / `is_running()`。
   - 沿用现有已验证的独立终端窗口启动方式（`_find_ffplay`/`_find_terminal`/终端窗口 + killpg 逻辑，从 rtmp.py 迁移过去），不重新发明。
   - **关键适配**：nginx-rtmp 在 EVB 停止推流（`rtmp_video_stop`）时会断开该 stream 的观看连接，ffplay 不会在下一轮 `rtmp_video_start` 时自动重连。`start()` 内部需用重连 wrapper（ffplay 退出后 sleep+重试，直到 `stop()` 终止 wrapper 及子进程），而非单次 ffplay 进程，以适配 stress 多轮 start/stop 推流的现实。这是对 restart() 场景的落地方式：由 PreviewManager 自动重连，不依赖外部显式调用。

2. **生命周期挂载点：复用现有 prepare/cleanup 动作注册表**（`scenario_manager.py` 的 `@prepare_action`/`@cleanup_action`），不新增框架机制：
   - 新增 `prepare_action("preview_start")`：读取 `ctx.evb_ip`（沿用 rtmp 模块现有 `_detect_pc_ip` 逻辑，一并迁移到 preview_manager.py 供两处复用）解出 pc_ip + `config/modules/rtmp.yaml` 的 `stream_url` 模板 + `config/modules/preview.yaml` 的播放器参数，组出观看地址，调用 `RtmpServer.check_ready()`（复用现有 driver）确认 nginx 就绪后 `PreviewManager.start()`。
   - 新增 `cleanup_action("preview_stop")`：调用 `PreviewManager.stop()`。
   - prepare 顺序：`[serial_init, wifi_connect, preclean, ftp_ready, preview_start]`（追加在末尾，此时 WiFi/网络已就绪）。
   - `ctx.preview_manager` 由 `preview_start` 写入 Context，供 `preview_stop` 及未来扩展复用；不由模块创建。

3. **配置归位（对齐 CLAUDE.md 红线「配置三层别放错」）**：
   - `preview.enabled`（flow 级开关）放 `config/scenarios/*.yaml`（与 `loop.enable` 同级），normal/stress 默认 `true`（保持现有行为不回退）。
   - 播放器路径/参数/是否强制（`preview_required`）等模块参数放新文件 `config/modules/preview.yaml`，不放 scenario 层。
   - **不在 scenario 层重复配置 RTMP url**：PreviewManager 的地址由 `ctx.pc_ip` + `rtmp.yaml` 的 `stream_url` 模板推导，与 rtmp 模块判据用的是同一 URL，避免两处各写一份造成漂移；仅在需要观察与推流不同目标时才允许 `preview.url` 显式覆盖。

4. **rtmp 模块收口**：`ATS/modules/rtmp.py` 移除 `_find_ffplay`/`_find_terminal`/`_launch_ffplay_terminal`/`_launch_ffplay_direct`/`self._ffplay_*` 全部字段与调用，`run()` 只保留推流下发 + ffprobe 探测 + heartbeat 保持 + 停止；`teardown()` 不再涉及 ffplay。（`video.py` 当前未启动 ffplay，属既成事实，不需要改动。）

5. **异常处理**：`is_running()==False` 时记录 warning「preview stopped unexpectedly」，仅当 `preview_required: true` 时才影响整体结果；默认不影响 video/rtmp/stress 判据。

## Alternative

- **维持现状（rtmp 模块内管理 ffplay）**：简单，但无法解决 loop 多轮窗口累积问题，职责耦合持续存在。
- **video/rtmp 模块共享一个模块级单例**：仍是 Task 层持有播放器状态，与「播放器生命周期属于 Scenario」矛盾，且违反模块红线（模块间不应隐式共享可变单例）。
- **落位 `ATS/core/`**：`core/` 是框架基础设施（context/scenario/runner/config/logger），PreviewManager 是「PC 端本地进程管理」，性质更接近 `drivers/` 已有的 `RtmpReceiver`/`RtmpServer`，故不采用。

## Impact

- 新文件：`ATS/drivers/preview_manager.py`、`config/modules/preview.yaml`。
- 修改：`ATS/modules/rtmp.py`（移除 ffplay 逻辑）、`ATS/core/scenario_manager.py`（新增 preview_start/preview_stop 动作）、`config/scenarios/normal.yaml` + `stress.yaml`（prepare 追加 `preview_start`，新增 `preview.enabled: true`）。
- `ATS/core/context.py` 无需改动（`ctx.preview_manager` 走既有属性存储机制，与 `evb_ip`/`ftp_client` 一致的「约定 key」模式）。
- 行为变化：终端窗口模式下，Scenario 结束（cleanup）时会主动关闭 ffplay 窗口，不再是「用户自己关」（旧决策见 20260817 devlog，此处显式覆盖：窗口生命周期从「独立于脚本」改为「归属 Scenario 生命周期」）。
- 不影响判据：ffprobe + heartbeat 仍是唯一 PASS/FAIL 依据，preview 只是观察能力。

## Status

Accepted（源码已实施，待真机验证，见 devlog `20260825_0111_PreviewManager单例播放器实施.md`）
