# ADR-008：WiFi 职责重划（状态检测器 vs 状态收敛器）

## Background

normal 场景的 prepare.`wifi_connect` 已连 WiFi 并设 `ctx.skip_wifi=True`，导致 tasks 里的 `wifi_check`/`wifi_scan`/`wifi_join` 冗余。且 `wifi_check` 当前定位是「独立测试项」，与 prepare 的「环境准备」定位边界模糊。

## Problem

1. wifi_check/scan/join 作为 normal 独立测试项，与 prepare.wifi_connect 职责重叠。
2. 掉电记忆 WiFi 时，「检测已联网」与「主动连接」的边界不清。

## Decision

1. **移除 normal tasks 的 wifi_check / wifi_scan / wifi_join**（WiFi 不再作为 normal 独立测试项）。
2. **wifi_check 重新定位为「状态检测器」**：只检测（`ifconfig` → 有无非 0.0.0.0 IP），产出 `ctx.evb_ip` + `ctx.wifi_ready`（True/False），**不 scan / join / 改配置**。
3. **prepare.wifi_connect 重新定位为「状态收敛器」**：先检测（调用 wifi_check 逻辑），已联网 → 保留状态；未联网 → 执行 join，最终保证 WiFi 达到可用状态。
4. **wifi_scan / wifi_join 模块代码保留**，退出 normal 默认流程（可复用于手动调试 / 未来场景）。

## Alternative

- **保留 wifi_check/scan/join 作为独立测试项**（原状）：职责重叠，报告冗余。
- **仅移除 ftp、保留 wifi**（中间态）：边界仍不清。

## Impact

- normal 场景 tasks 7 项 → 4 项（emmc / photo / video / rtmp）。
- 模块职责：wifi_check 变 prepare 内部检测器；wifi_scan/wifi_join 退出默认流程。
- prepare.wifi_connect 实现需加「先检测已联网则保留」逻辑。

## Status

Accepted（源码实施待 Code Agent）
