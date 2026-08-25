# PreviewManager 单例播放器实施（ADR-010）

## 日期
2026-08-25

## 变更来源
ADR-010「PreviewManager 单例播放器」已 Accepted，本记录为 Code Agent 按 Decision 部分的源码实施。

## 做了什么
将 ffplay 画面观察从 rtmp 模块（Task 生命周期）抽离为 Scenario 生命周期的 `PreviewManager` 单例，
解决 stress 多轮 loop 下播放窗口逐轮累积、资源不可控的问题。画面观察定位为「观察能力」，不参与判据。

1. **新增 `ATS/drivers/preview_manager.py`**（驱动层，与 `RtmpReceiver`/`RtmpServer` 同级）：
   - `PreviewManager`：`start(url)` / `stop()` / `restart(url)` / `is_running()`。
   - 迁移 `_detect_pc_ip` / `_find_ffplay` / `_find_terminal`（从 rtmp.py 迁来，`_detect_pc_ip` 供两处复用）。
   - 关键适配：`start()` 用**重连 wrapper**（bash while 循环：ffplay 退出后 sleep+重连，直到 `stop()` 终止
     wrapper 及子进程），适配 nginx-rtmp 在 `rtmp_video_stop` 时断开 stream、ffplay 不自动重连的现实。
   - 独立终端窗口模式 + 直启 bash wrapper 模式（`setsid` 便于 `killpg` 整组回收），沿用既有验证过的逻辑。
2. **新增 `config/modules/preview.yaml`**：`ffplay_path` / `retry_interval` / `preview_required` / `url`。
3. **精简 `ATS/modules/rtmp.py`**：移除 `_find_ffplay` / `_find_terminal` / `_launch_ffplay_terminal` /
   `_launch_ffplay_direct` / 全部 `self._ffplay_*` 字段与调用；`run()` 只保留推流下发 + ffprobe 探测 +
   heartbeat 保持 + 停止；`teardown()` 不再涉及 ffplay；`_detect_pc_ip` 改为从 preview_manager 导入。
4. **`ATS/core/scenario_manager.py`** 挂生命周期动作：
   - `prepare_action("preview_start")`：读 `ctx.preview_enabled` 开关 → 解 pc_ip（`system.pc.ip` 或
     `_detect_pc_ip`）→ 组观看地址（`preview.url` 覆盖优先，否则 `rtmp.yaml` 的 `stream_url` 模板 + pc_ip）
     → `RtmpServer.check_ready()` 确认 nginx 就绪 → `PreviewManager.start()` → 写入 `ctx.preview_manager`。
   - `cleanup_action("preview_stop")`：`PreviewManager.stop()` 回收。
   - `ScenarioManager` 增加 `preview_cfg` 解析 + `run()` 时写 `ctx.preview_enabled`。
5. **`config/scenarios/normal.yaml` / `stress.yaml`** 补配置：新增 `preview.enabled: true`，prepare 追加
   `preview_start`，cleanup 追加 `preview_stop`。`aging.yaml` 不启用 preview（无人值守老化，保持原样）。

## 改了哪些文件
- `ATS/drivers/preview_manager.py`（新增）
- `ATS/config/modules/preview.yaml`（新增）
- `ATS/modules/rtmp.py`（精简 ffplay 逻辑）
- `ATS/core/scenario_manager.py`（新增 preview_start / preview_stop 动作 + preview 开关解析）
- `ATS/config/scenarios/normal.yaml`（prepare/cleanup 追加 + preview.enabled）
- `ATS/config/scenarios/stress.yaml`（prepare/cleanup 追加 + preview.enabled）

## 如何验证
1. `python3 -m py_compile` 三个改动源文件 → PASS。
2. `from ATS.drivers.preview_manager import PreviewManager` / `from ATS.modules import rtmp` /
   `from ATS.core import scenario_manager` → 全部 import OK。
3. 动作注册：`preview_start` ∈ PREPARE_ACTIONS、`preview_stop` ∈ CLEANUP_ACTIONS → PASS。
4. 场景解析：normal/stress prepare 含 `preview_start`、cleanup 含 `preview_stop`、`preview_enabled=True`；
   aging 保持 `preview_enabled=False` 且不加 preview 动作 → PASS。
5. 离线行为测试（`env -u DISPLAY`）：`start()` 返回 False、`is_running()` False、`stop()`/`restart()` 幂等
   安全、`_wrapper_script()` 生成正确的 while 重连脚本 → PASS。
6. `grep` 确认 rtmp.py 无 `_ffplay` / `subprocess` / `os.` / `signal` 残留 → PASS。

## 已知遗留（待真机验证）
- 独立终端窗口模式下，gnome-terminal 传 `-- bash -c` 可能启动后立即返回，`is_running()` 以 `_active`
  兜底判断、`stop()` 对已 fork 到后台的终端进程的 `killpg` 属 best-effort；直启模式（bash wrapper + setsid）
  可可靠整组回收。真机需确认窗口确实只开一个且 cleanup 正常关闭。
- `preview_required: true` 当前只做到「意外退出时 `logger.error`」级别，「影响整体结果（退出码/报告）」
  的闭环未实现（ADR Impact 未列入 runner/main 改动），待真机验证后按需补。
- 全部改动**尚未真机验证**（与 current_status 的 P0 一致）。
