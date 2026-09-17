# stress.yaml photo task 按模式拆分（每模式独立 repeat）

## 1. 问题描述 / 需求

`stress.yaml` 的 photo task 原为「单 task 内遍历 10 模式」，`repeat` 是所有模式共享
一个次数。用户希望每个拍照模式能独立配置 repeat 次数，本次先搭骨架、全部模式
`repeat=1`，后续按需单独调整某一模式。

需求归档：`docs/03_development/archive/新增需求_stress_photo模式独立repeat拆分.md`。

## 2. 根因分析（为何无需改源码）

- `PhotoModule.run()` 遍历 `photo_modes` 列表（`photo.py` L64 `for mode in modes`），
  列表单元素 → 只测该模式一次。
- Runner 的 `repeat` 由 task 驱动（`runner.py` 对每个 task 按 repeat 循环）。
- `override.photo_modes` 整体替换 `photo.yaml` 默认值（`_merge` = `{**config, **params}`）。

因此「每模式一个 task + 单元素 `photo_modes` + 独立 `repeat`」即可表达每模式独立次数，
纯配置改动，符合红线 2（重复由 Scenario/Runner 驱动，模块内不写 for）。

## 3. 修复内容

`ATS/config/scenarios/stress.yaml` photo task 段：1 个 task（遍历 10 模式）→ 10 个 task，
每个 task 单元素 `photo_modes` + `repeat: 1`：

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
    # ...（single 720p / single 480p / mfnr / hdr_0~3，共 10 个）
```

- 保留并前移原 TODO-CONFIRM 注释（含空格三 token、hdr_0~3 独立命名待真机核实），
  并补一句「拆为 10 个 task 以支持每模式独立 repeat」。
- 其余 task（video / video_integrity / rtmp）与 prepare/loop/cleanup 完全未动。
- 未新增场景文件，未改 photo.py / Runner / Scenario 数据结构 / photo_commands.py / photo.yaml。

## 4. 验证结果

- `stress.yaml` YAML 解析：photo task 数量 = 10，模式顺序
  `auto→single→single 1080p→single 720p→single 480p→mfnr→hdr_0~3` 与拆分前一致，
  且每个 task `repeat == 1`。
- 非 photo task 数量 = 13（与拆分前一致），video / video_integrity / rtmp 配置未变。

## 5. 还会再有吗

- 本次 repeat 全 1，与拆分前行为等价；拆分意义在搭骨架。后续调某模式次数只需改对应
  task 的 repeat。
- **FTP 行为提示（无害）**：拆成 10 个 task 后每个 task 都会走一遍 `PhotoModule.run()`
  开头的 `ensure_ftp`（非 force，幂等，`ftp_server` 全程只发一次，符合红线 3），
  较原 1-task 写法多 9 次 `ensure_ftp` 调用，属无害冗余开销，无需处理。
- 10 个模式名（尤其含空格三 token、hdr_0~3 独立命名）是否固件合法，仍待真机核实。

## 6. 经验沉淀

- 「单 task 遍历 N 模式」与「N 个 task 各单模式」在 repeat=1 时等价；后者把「每模式
  独立次数」的粒度交给 Scenario/Runner 表达，是红线 2（循环/重复由 Scenario 驱动）的
  自然延伸。
- 配置层拆分前先确认模块遍历的是列表、Runner 按 repeat 驱动、override 整体替换默认值，
  三者成立即可纯配置拆，无需动源码。
