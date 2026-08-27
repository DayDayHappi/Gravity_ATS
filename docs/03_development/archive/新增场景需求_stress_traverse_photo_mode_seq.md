# 需求文档：新增场景 stress_traverse_photo_mode_seq（模式优先顺序）

> 提出方：Document Agent（按用户口述整理，交由 Code Agent 实施）
> 状态：待实施

## 1. 背景

现有 `stress_traverse_photo_mode.yaml` 的 photo task 是「repeat 在外层、模式在内层」：

```yaml
- module: photo
  repeat: 50                                   # 外层：repeat 50 轮
  override:
    photo_modes: [auto, single, mfnr, hdr_0, hdr_1, hdr_2, hdr_3]   # 内层：每轮遍历 7 模式
```

执行顺序（**repeat-major，round-robin**）：

```
第 1 轮：auto → single → mfnr → hdr_0 → hdr_1 → hdr_2 → hdr_3
第 2 轮：auto → single → mfnr → hdr_0 → hdr_1 → hdr_2 → hdr_3
...
第 50 轮：auto → single → ... → hdr_3
```

用户还期望另一种执行顺序（**mode-major，sequential**）：一个模式拍满 repeat 次后再切下一个模式：

```
auto  × 50
single × 50
mfnr   × 50
hdr_0  × 50
hdr_1  × 50
hdr_2  × 50
hdr_3  × 50
```

## 2. 需求

新增场景，实现 mode-major（sequential）顺序：每个模式连续拍满 `repeat` 次，再切下一个模式。除 photo task 编排方式外，其余（preview/prepare/loop/video/rtmp/cleanup）与 `stress_traverse_photo_mode.yaml` 保持一致。

## 3. 实现方式（纯配置，无需改源码）

已核查现有机制可完全满足，**不需要改 `photo.py` / Runner / Scenario 数据结构**：

1. `PhotoModule.run()` 遍历 `photo_modes` 配置列表（`photo.py` L48/L56），列表只有一个元素时即只测该模式。
2. `override.photo_modes` 会**整体替换** `config/modules/photo.yaml` 的默认值（`_merge` = `{**config, **params}`，override 优先）。
3. Runner 的 `repeat` 由 task 驱动（`runner.py` L104-107），把单次 `run()`（即单模式拍 1 张）重复 N 次。

因此「每模式一个 task + 单元素 `photo_modes` + `repeat`」即可表达 mode-major 顺序，与红线 2（重复由 Scenario/Runner 驱动，模块内不写 for）一致。

## 4. 场景文件内容

新建 `ATS/config/scenarios/stress_traverse_photo_mode_seq.yaml`：

```yaml
# 压测场景：遍历全部拍照模式，模式优先顺序（一个模式拍满 repeat 次再切下一个）。
# 与 stress_traverse_photo_mode.yaml 的区别：photo 由「1 个 task 内遍历 7 模式」
# 改为「7 个 task 各持单模式 + repeat」，从而顺序从 round-robin 变为 sequential。
# 其余（preview/prepare/loop/video/rtmp/cleanup）与 stress_traverse_photo_mode.yaml 一致。
scenario:
  name: stress_traverse_photo_mode_seq
  preview:
    enabled: true
  prepare:
    - serial_init
    - wifi_connect
    - preclean
    - ftp_ready
    - preview_start
  loop:
    enable: true
    count: 20
  tasks:
    - module: photo
      repeat: 50            # 每个模式拍 50 次（可配置）
      override:
        photo_modes: [auto]
    - module: photo
      repeat: 50
      override:
        photo_modes: [single]
    - module: photo
      repeat: 50
      override:
        photo_modes: [mfnr]
    - module: photo
      repeat: 50
      override:
        photo_modes: [hdr_0]
    - module: photo
      repeat: 50
      override:
        photo_modes: [hdr_1]
    - module: photo
      repeat: 50
      override:
        photo_modes: [hdr_2]
    - module: photo
      repeat: 50
      override:
        photo_modes: [hdr_3]
    - module: video
      duration: 180
    - module: rtmp
      duration: 600
  cleanup:
    - stop_stream
    - preview_stop
    - close_serial
```

> 模式名沿用 `stress_traverse_photo_mode.yaml` 已使用的 7 个
> （`auto/single/mfnr/hdr_0~3`）。`hdr_0~3` 是否为固件合法模式名仍带
> `TODO-CONFIRM`（与上个场景同源，见 `stress_traverse_photo_mode.yaml` 注释），
> 需真机一并核实，本场景不引入新模式名。

## 5. 验收标准

- `--list-scenarios` 能看到 `stress_traverse_photo_mode_seq`。
- 跑一轮（建议先用小 `repeat`（如 2）+ `loop.count: 1` 冒烟）后，从
  `logs/stress_traverse_photo_mode_seq/.../run.log` 的 `photo[...]` 结果顺序应为：
  `photo[auto] ×N` → `photo[single] ×N` → … → `photo[hdr_3] ×N`，**同一模式连续出现 N 次**，
  而非 `auto/single/.../hdr_3` 循环 N 轮。
- `photo_modes` 各 task 的 `repeat` 次数可独立配置（改对应 task 的 `repeat` 即可）。
- 其余 task（video/rtmp）行为与 `stress_traverse_photo_mode.yaml` 一致。

## 6. 边界确认

- 本需求**不改动任何源码**（`photo.py`/Runner/Scenario 均不动），纯新增场景配置文件。
- 两种顺序的对应关系，本质是「repeat 与模式遍历的嵌套顺序」交换，由 Scenario 层
  「单 task 多模式」vs「多 task 单模式」两种写法表达，无需给模块加新参数。
- 与 `docs/05_handoff/next_step.md` P4「loop 语义局限」同源（都是「参数维度 × repeat」
  的表达能力），本方案用「多 task」绕开，不依赖 loop 增强；若未来需要更通用的
  「参数列表 × repeat」自动展开，再单独评估（Level 3，需 ADR）。
- 按工程红线 1，新增配置文件后仍需在 `docs/03_development/devlog/` 新建记录并更新
  README 索引。
