# 需求文档：新增场景 stress_traverse_photo_mode

> 提出方：Document Agent（按用户口述整理，交由 Code Agent 实施）
> 状态：待实施

## 1. 背景

现有 `stress` 场景（`ATS/config/scenarios/stress.yaml`）的 photo task 只配置了
`photo_modes: ["auto"]`（见 `ATS/config/modules/photo.yaml`），压测时实际只覆盖了
`auto` 一种拍照模式，`repeat: 50` 只是把 `auto` 模式拍了 50 次。

现要新增一个"遍历全部拍照模式"的压测场景，用于覆盖 `photo` 模块支持的全部模式，
且每个模式的拍照次数需可配置。

## 2. 需求

新增场景配置文件 `ATS/config/scenarios/stress_traverse_photo_mode.yaml`：

- **除 photo task 外，其余内容与 `stress.yaml` 完全一致**（preview/prepare/loop/video/rtmp/cleanup 都不变）。
- **photo task 需遍历全部拍照模式**，不再只测 `auto`。

## 3. 实现方式（架构已支持，预计不涉及代码改动）

已核查现有机制可以直接满足需求，**无需改 `ATS/modules/photo.py` 或 Runner/Scenario 逻辑**：

1. `PhotoModule.run()` 本身就是"遍历 `photo_modes` 配置列表，每个模式测一次"
   （`photo.py` L48/L56：`modes = self.config.get("photo_modes", [...])` → `for mode in modes`）。
2. `repeat` 由 Runner 驱动（`runner.py` L104-107），每次 `repeat` 都完整调用一次
   `photo.run()`，即把"全部模式各测一次"重复 N 遍 → **`repeat` 次数 = 每个模式的拍照次数**。
3. Task 支持 `override` 字段（`scenario.py` Task.override），可以在 scenario 级别
   覆盖 `photo_modes`，不用碰 `config/modules/photo.yaml` 的全局默认值（默认值仍保持
   `["auto"]`，不影响 `normal`/`stress` 等其他场景）。

综上，新场景 photo task 建议写成：

```yaml
tasks:
  - module: photo
    repeat: 50            # 与 stress.yaml 保持一致；即每个模式各拍 50 次
    override:
      photo_modes: [auto, single, mfnr, hdr_0, hdr_1, hdr_2, hdr_3]
  - module: video
    duration: 180
  - module: rtmp
    duration: 600
```

`photo_modes` 具体枚举值以 `ATS/config/modules/photo.yaml` 注释
`# 可扩为 [auto, single, mfnr, hdr_0, hdr_1, hdr_2, hdr_3]` 为准 ——
**请 Code Agent 核实这 7 个模式名是否均为固件当前支持的合法 `cam_set photo <mode>`
参数**（本文档基于现有代码注释推断，未做真机核对，标记
`TODO-CONFIRM`）。若实际支持的模式集合不同，以固件手册/真机实测为准。

## 4. 场景内 name 字段

按 `stress.yaml` 惯例，`scenario.name` 需与文件名一致，便于日志区分：

```yaml
scenario:
  name: stress_traverse_photo_mode
```

CLI 调用方式（场景名 = 文件名去掉 `.yaml`，`list_scenarios` 自动发现，无需额外注册）：

```bash
python3 -m ATS.main --scenario stress_traverse_photo_mode
```

## 5. 验收标准

- `--list-scenarios` 能看到 `stress_traverse_photo_mode`。
- 跑一轮（可先用较小 `repeat`，如 2，做冒烟验证）后，`logs/stress_traverse_photo_mode/.../photos/`
  下应能看到 7 种模式各自的拍照结果（文件名含 mode 前缀，见 `photo.py` L112
  `f"{mode}_{new_dir}_{jpg0}"`），且 report 里 `photo[auto]`/`photo[single]`/…
  等每个模式各出现 `repeat` 次结果。
- 其余 task（video/rtmp）行为与 `stress.yaml` 跑出来的结果一致（因为配置未变）。

## 6. 边界确认

- 本需求**不改动** `photo.py`、Runner、Scenario 数据结构 —— 现有 `override` +
  `repeat` 机制已够用。若 Code Agent 实施时发现实际不够用（比如需要"每个模式
  次数不同"这种更细粒度需求），请先停下产出 `Document Agent Request`，不要
  直接改模块红线（模块内禁止 for 循环嵌套业务逻辑之外的循环控制）。
- 按工程红线 1，新增/修改配置文件后仍需在
  `docs/03_development/devlog/` 新建记录并更新 README 索引。
