# recovery_validation 照搬 stress tasks / loop / preview / rtmp duration

## 问题描述

用户要求：把 stress.yaml 的 task 全部复制到 recovery_validation 下，且 loop / preview /
rtmp duration 全部照搬 stress 原文。使 recovery_validation 在完整 stress 负载下验证 ADR-016
恢复机制（而非单次短录像）。

## 修改内容（ATS/config/scenarios/recovery_validation.yaml，纯配置）

1. **loop**：新增，照搬 stress（`enable: true` / `count: 200`）。
2. **preview**：`enabled: false → true`（照搬 stress，开启画面观察）。
3. **tasks**：整段替换为 stress.yaml 的 24 个 task（原文照搬含注释）：
   - photo×10（auto/single/single 1080p/720p/480p/mfnr/hdr_0~3，各 repeat:1 + 单元素 photo_modes）
   - video×12（sd1080p_0/1/2、hd1080p_1/2、3k_2、720p_0/1/2、480p_0/1/2，各 repeat:1 duration:20）
   - video_integrity×1（all_unchecked + empty_input_policy: skip）
   - rtmp×1（duration: 600）
4. **prepare**：保持 recovery 冷启动顺序（power_switch_init → serial_init），仅插入
   `preview_start`（preview.enabled=true 需要挂 preview_start）。
5. **cleanup**：插入 `preview_stop`（preview 开启后关闭 ffplay 窗口）。

**保持不变**（recovery 场景核心）：
- name: recovery_validation
- health_monitor.enabled: true + recovery.*（backend/max_attempts/after_recovery/on_exhausted/restore）
- prepare 冷启动顺序（power_switch_init → serial_init，契约校验强制）
- cleanup 的 health_monitor_stop 位置（在 close_serial/power_switch_close 之前）

## 验证结果（离线）

- `py_compile`/`compileall` 通过。
- `ScenarioManager.load('recovery_validation')`：24 个 task，与 stress 逐项对比
  （module/repeat/duration/override）完全一致；loop.count=200、preview.enabled=true。
- 契约校验通过（`validate_scenario` + system.power_switch.enabled=true）：
  power_switch_init < serial_init < health_monitor_start 顺序合法；preview_start/preview_stop
  不在契约校验范围，按位插入不影响。
- 依赖齐备：video_integrity 依赖 FTP（ftp_ready ✓）、rtmp 依赖 WiFi+preview
  （wifi_connect/preview_start ✓）。

**待真机**：`python3 -m ATS.main --scenario recovery_validation --no-interactive-wifi`
（前置 system.power_switch.enabled=true）。单轮约 20+ 分钟，loop.count=200 会非常久——
用户已确认照搬 stress，默认按 200 落地。

## 还会再有吗

- 24 task 数（非用户描述的 23）是 stress 源码实际数量（photo10+video12+integrity1+rtmp1），
  照搬一致。
- 若真机只想先快速验证恢复链路，可临时把 loop.count 调小（如 1~3），默认保持 200 与 stress 一致。

## 经验沉淀

- 场景「照搬 task + 保留自身 prepare/cleanup 生命周期」是配置层组合：task 与 loop/preview 是
  测试策略（可整体复用），prepare/cleanup 顺序是环境接线（冷启动依赖/防误判），二者来源不同，
  不能整文件照抄（stress 的 serial_init→power_switch_init 旧顺序会被 recovery 契约校验拒绝）。
- 配置改动虽不改源码，仍需留痕 + 校验（契约校验 + 与复制源逐项比对），防「照搬时误改顺序」。
