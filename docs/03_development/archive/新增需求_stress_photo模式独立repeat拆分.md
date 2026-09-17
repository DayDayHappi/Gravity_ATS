# 需求文档：stress.yaml photo task 按模式拆分（每模式独立 repeat）

> 提出方：Document Agent（按用户口述整理，交由 Code Agent 实施）
> 状态：已实施（2026-09-17，devlog `20260917_1634_stress_photo模式独立repeat拆分.md`）

## 1. 背景

`ATS/config/scenarios/stress.yaml` 的 photo task 目前是「单 task 内遍历 10 模式」：

```yaml
- module: photo
  repeat: 1
  override:
    photo_modes: [auto, single, single 1080p, single 720p, single 480p, mfnr, hdr_0, hdr_1, hdr_2, hdr_3]
```

此时 `repeat` 是所有模式**共享**一个次数（round-robin：每轮 `auto→single→…→480p`，共 repeat 轮）。用户希望**每个拍照模式能独立配置 repeat 次数**，本次先搭好骨架、所有模式 `repeat` 都先写 **1**，后续按需单独调整某一模式的 `repeat`。

## 2. 需求

将 `stress.yaml` 的这一个 photo task **拆成 10 个 photo task**，每个 task 持单元素 `photo_modes` + 独立 `repeat`（本次全部 = 1）。

- **只改 `ATS/config/scenarios/stress.yaml`**（photo task 段）。
- 其余 task（video / video_integrity / rtmp）与 `prepare`/`loop`/`cleanup` 完全不动。
- 不新增场景文件（延续用户此前「在 stress.yaml 里加」的意图）。

## 3. 实现方式（纯配置，无需改源码）

已核实机制：

1. `PhotoModule.run()` 遍历 `photo_modes` 列表，每个模式拍 1 次（`photo.py` L64 `for mode in modes`）；列表单元素 → 只测该模式。
2. Runner 的 `repeat` 由 task 驱动（`runner.py` L104-105 `for rep in range(repeat_total)`），把「该模式拍 1 次」重复 N 次。
3. `override.photo_modes` 整体替换 `photo.yaml` 默认值（`_merge` = `{**config, **params}`）。

因此「每模式一个 task + 单元素 `photo_modes` + 独立 `repeat`」即可表达每模式独立次数，符合红线 2（重复由 Scenario/Runner 驱动，模块内不写 for）。

## 4. 具体改动（stress.yaml photo task 段）

将现有 1 个 photo task 替换为 10 个：

```yaml
    - module: photo
      repeat: 1
      override:
        photo_modes: [auto]
    - module: photo
      repeat: 1
      override:
        photo_modes: [single]
    - module: photo
      repeat: 1
      override:
        photo_modes: [single 1080p]
    - module: photo
      repeat: 1
      override:
        photo_modes: [single 720p]
    - module: photo
      repeat: 1
      override:
        photo_modes: [single 480p]
    - module: photo
      repeat: 1
      override:
        photo_modes: [mfnr]
    - module: photo
      repeat: 1
      override:
        photo_modes: [hdr_0]
    - module: photo
      repeat: 1
      override:
        photo_modes: [hdr_1]
    - module: photo
      repeat: 1
      override:
        photo_modes: [hdr_2]
    - module: photo
      repeat: 1
      override:
        photo_modes: [hdr_3]
```

- 保留 `photo_modes` 处原有的 TODO-CONFIRM 注释（`single 1080p/720p/480p` 三 token、`hdr_0~3` 独立命名均待真机核实），并补一句「拆为 10 个 task 以支持每模式独立 repeat」。
- 后续要调某模式次数，只改对应 task 的 `repeat`，无需再动其它。

## 5. 验收标准

- `python3 -m ATS.main --scenario stress` 正常跑，无场景解析错误（10 个 photo task 均被识别）。
- `repeat` 全 1 时，本轮 10 个 photo task 的执行顺序与结果集合，与拆分前（1 个 task 遍历 10 模式）**等价**：均产出 `photo[auto]`/`photo[single]`/`photo[single 1080p]`/…/`photo[hdr_3]` 各 1 条，且顺序 `auto→single→single 1080p→…→hdr_3`（repeat=1 时 round-robin 与 mode-major 顺序相同）。
- 其余 task（video / video_integrity / rtmp）行为与拆分前一致（配置未变）。

## 6. 边界确认

- **不改动** `photo.py`、Runner、Scenario 数据结构、`photo_commands.py`（`PHOTO_MODES` 已含 10 模式）、`photo.yaml` 默认值。
- **本次 repeat 全 1，拆分的意义在于搭骨架**：后续每模式独立调 `repeat` 时无需再改结构；若未来仍只需要「全部模式统一次数」，保留原 1-task 写法亦可，两者等价。
- **FTP 行为提示（非阻断）**：拆成 10 个 task 后，每个 task 都会走一遍 `PhotoModule.run()` 开头的 `ensure_ftp`（非 force，幂等，`ftp_server` 全程只发一次，符合红线 3）；相较原 1-task 写法多 9 次 `ensure_ftp` 调用，属无害冗余开销，Code Agent 无需处理。
- 含空格模式名 `single 1080p` 等作为单元素列表值已实测 YAML 解析无误。
- 按工程红线 1，改 `ATS/config` 后需在 `docs/03_development/devlog/` 新建记录并更新其 README 索引。
