# 修复 --no-interactive-wifi 下 wifi_connect 直接 return 导致 FTP/photo/video 全 SKIP

## 日期
2026-08-24

## 问题描述
`--no-interactive-wifi + stress` 时，`prepare.wifi_connect` 动作在 `ctx.no_interactive_wifi` 为真时直接 `return`，
不执行 `wifi join`，导致 `ctx.evb_ip` 拿不到。后续 `ftp_ready` 的 `start_ftp` 因无 evb_ip 返回 None，
photo/video 的 `ensure_ftp` 也拿不到 IP，最终 photo/video 全 SKIP。

这与 CLI 语义不符：`--no-interactive-wifi` 的 help 是「跳过 WiFi 交互，直接用配置的 SSID/密码」，
原实现的 return 是偷懒写法，本质是 bug。对应 `docs/05_handoff/next_step.md` 的 P0-1。

## 根因分析
`_action_wifi_connect` 把「非交互」实现为「不做任何事」，断掉了自动模式的 WiFi 连接路径。
system.yaml 的 `wifi.interactive` 字段本应控制行为，但未被充分利用。

## 修复内容
修改 `ATS/core/scenario_manager.py` 的 `_action_wifi_connect`：

- 非交互（`--no-interactive-wifi`）时不再 `return`，改走自动连接：读 `wifi.default_ssid/default_password` 执行 `wifi join`。
- 交互与非交互两条路径收敛到同一个 join 出口，连上后统一设 `ctx.evb_ip` + `ctx.skip_wifi=True`。
- 保留原有「交互-默认 / 交互-扫描选 AP」行为不变。

```diff
-    if getattr(ctx, "no_interactive_wifi", False):
-        logger.info("--no-interactive-wifi：跳过交互 WiFi 连接，交由 wifi_join 模块处理")
-        return
     console = getattr(ctx, "console", None)
+    ...
+    no_interactive = getattr(ctx, "no_interactive_wifi", False)
+    if not no_interactive and wifi_cfg.get("interactive", True):
+        ans = input(...)
+        use_default = ans != "n"
+    if no_interactive:
+        ssid, pwd = default_ssid, default_pwd
+        logger.info(f"--no-interactive-wifi：使用默认 WiFi [{ssid}] 自动连接")
+    elif use_default:
+        ...
```

## 验证结果
1. 离线单测自动分支：`no_interactive=True` → 不扫描、发 `wifi join SW-test-2.4G tuf@3600`、`ctx.evb_ip=10.1.90.71`、`ctx.skip_wifi=True` → PASS。
2. 离线单测 SSID 为空：不 join、evb_ip 保持 None → PASS。
3. 离线单测交互分支不回归：input 回车 → 默认 join；input n → 扫描分支 → PASS。
4. 三场景配置解析正常（normal/stress/aging load 通过）→ PASS。

## 还会再有吗
无残留风险。此改动为 prepare action 内部实现（Level 1），不改接口/配置格式/模块依赖。

## 待办（Level 3，已交 Document Agent）
normal tasks 中 wifi_check/wifi_scan/wifi_join 是否移除（系统测试边界 + 模块职责变更）属 Level 3，
不在本次改动范围，需 Document Agent 评估。
