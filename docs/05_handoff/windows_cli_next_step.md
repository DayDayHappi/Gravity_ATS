# Windows CLI 分支待办（feature/windows-cli）

> 本文件是**分支专属**待办，短期不会合入 `new_arch`。
> 合主线时由 Document Agent 一次性整合进主 `next_step.md`，不在分支上碰主文件。

## 决策状态（已定案）

1. **实现方式**：**方案 A**（抽 `ATS/platform/` 平台抽象层）。
2. **RTMP 服务端**：本机已启动 nginx-rtmp-win32-dev（监听 1935），`rtmp_server.py` 零改动可用。
3. **preview**：仍用 ffplay，改造 `preview_manager.py` 进程管理为 Windows 方式。
4. **cancellation**：裁剪，不引入 `core/cancellation.py`。
5. **工具查找**：引入 `resources.py`（`ResourceLocator.find_tool()`）统一 ffprobe/ffmpeg/ffplay。
6. **ANSI 颜色**：`ctypes` + `SetConsoleMode` 启用 VT（零依赖）。
7. **preview 注入**：构造注入。

## ✅ P0 已实施（devlog `20260920_1502`）

新增 `ATS/platform/` + 六处业务文件接入，全部按方案 A 落地。真机验证（2026-09-20 stress）串口枚举/WiFi/ffplay 拉起均正常。

## ✅ 环境问题已解决（devlog `20260920_1600`，真机复验通过）

Windows 防火墙规则错配导致的 FTP 主动模式超时已定位并修复：规则 `Gravity ATS CLI FTP - Board101` 的 RemoteAddress/LocalAddress/Program 三字段全错，重配为 `RemoteAddress=.100`/`LocalAddress=Any`/`Program=Any`/`LocalPort=1024-65535` 后，真实 FTP LIST 恢复 0.21s，完整 stress 真机复验通过。

- 排查报告：[archive/Windows_CLI_FTP主动模式超时_排查与解决报告.md](../03_development/archive/Windows_CLI_FTP主动模式超时_排查与解决报告.md)。

## 🟡 P1 — 离线测试（未落地）

- 解除 `/tests/` 忽略（`.gitignore` 放行 `tests/windows_cli/`；合主线时需复核）。
- `tests/windows_cli/`：`test_platform.py` / `test_lifecycle.py` / `test_cli.py` / `test_regression.py`（参照 ui-windows 取舍）。

## 🟡 P1 — preview 窗口尺寸可配置（方案 A，待 Code Agent 实施）

**现象**：Windows 下 ffplay 画面窗口过大（跟随视频原始分辨率，如 3k/4k），且无法 resize / 移动。

**方案 A（已拍板）**：`preview_manager.py` 的 `_argv()` 增加 `-x <宽> -y <高>`，值从 `preview.yaml` 读取。

- `preview.yaml` 新增 `window_width` / `window_height`（默认 `960` / `540`，留空/0 表示跟随原始分辨率、不传 `-x/-y`）。
- `__init__` 读取这两个配置项；`_argv()` 条件拼入 `-x`/`-y`。
- 边界：`-x/-y` 是窗口初始尺寸（非视频缩放），可解决「框太大」；「无法移动/缩放」是 ffplay SDL 窗口固有行为，`-x/-y` 后至少不再超屏，需在文档标注此限制。

## 🟡 P1 — 文档

- 设计文档已产出：[02_design/windows_cli_port_plan.md](../02_design/windows_cli_port_plan.md)（分支专属，合主线时升正式 ADR）。
- 分支 devlog 命名 `<YYYYMMDD>_<HHMM>_<描述>.md`，**不更新**共享 `devlog/README.md` 索引（合主线时再补）。
- 修正 devlog `20260920_1502` 的「真实枚举返回 ['COM3','COM4']」→ 实为 `['COM10','COM9','COM3','COM4']`（当时 EVB 未插）。

## 参考

- `origin/feature/ats-ui-windows` 的 `ATS/platform/`（`serial_ports.py` / `console_input.py` / `processes.py`）。
  ⚠️ `processes.py` 依赖 `core.cancellation.CancellationToken`，当前分支没有，需裁剪或一并移植。
- `.ats_cli_backups/20260916_143611_3152bae7/install_record.json`（历史移植清单，正文已丢）。
