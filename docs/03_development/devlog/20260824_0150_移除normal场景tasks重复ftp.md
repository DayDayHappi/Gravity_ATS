# 移除 normal 场景 tasks 中重复的 ftp 模块

## 日期
2026-08-24

## 问题描述
`normal` 场景中 FTP 准备被做了两遍：

- `prepare.ftp_ready`：幂等发一次 `ftp_server` + 建立 PC 端 FTP 连接（`start_ftp`）。
- `tasks.ftp`：再次调 `start_ftp`（`ftp_server` 因 `ctx.ftp_server_started` 已置位不重发，仅重建连接）+ 列 `/emmc` 目录。

属于重复操作。`stress` / `aging` 场景的 prepare 有 `ftp_ready` 但 tasks 均无 ftp，normal 与之不一致。

## 修复内容
- 修改 `ATS/config/scenarios/normal.yaml`：删除 tasks 中的 `- module: ftp` 一行。
- **保留** `ATS/modules/ftp.py` 与 `ATS/config/modules/ftp.yaml`（模块代码不动，可复用）。

```diff
   tasks:
     - module: wifi_check
     - module: wifi_scan
     - module: wifi_join
     - module: emmc
-    - module: ftp
     - module: photo
     - module: video
     - module: rtmp
```

## 影响说明
- `photo` / `video` 声明 `depends = ["ftp"]`，但 ftp 不再作为 task 执行后，Runner 的 fail-fast 检查 `module_status.get("ftp")` 返回 None，不阻断，photo/video 不会被误 SKIP。
- photo/video 实际通过 `ensure_ftp()` 自行重建 FTP 连接，不依赖 ftp 模块留下的 `ctx.ftp_client`。
- normal 报告结果项由 8 项变 7 项（少一条 ftp PASS）；FTP 连通性仍由 `prepare.ftp_ready` 的连接建立/登录保证。

## 验证结果
1. `ScenarioManager.load("normal")` 解析：tasks 不含 ftp、prepare 含 ftp_ready、tasks 非空 → PASS。
2. 模拟 fail-fast：photo/video 依赖 ftp 在 ftp 无 task 时 blocked 为空 → 不 SKIP。
3. `git diff --stat` 仅 `normal.yaml` 1 文件改动，ftp 模块与配置未变。

## 还会再有吗
无残留风险。此改动仅流程编排层（Level 0），不涉及模块代码/接口/架构。
