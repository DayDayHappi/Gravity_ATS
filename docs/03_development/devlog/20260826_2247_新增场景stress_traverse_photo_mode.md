# 新增场景 stress_traverse_photo_mode（遍历全部拍照模式压测）

## 日期
2026-08-26

## 变更来源
需求文档：[新增场景需求_stress_traverse_photo_mode.md](../archive/新增场景需求_stress_traverse_photo_mode.md)（Document Agent 整理，指向 commit 11245e5）。

## 做了什么
新增纯配置文件 `ATS/config/scenarios/stress_traverse_photo_mode.yaml`：

- 与 `stress.yaml` 唯一差异：photo task 用 `override.photo_modes` 遍历全部拍照模式
  `[auto, single, mfnr, hdr_0, hdr_1, hdr_2, hdr_3]`，而非默认只测 `auto`。
- 其余（preview/prepare/loop/video/rtmp/cleanup）与 `stress.yaml` 完全一致：
  `preview.enabled: true`、`loop.count: 20`、`video.duration: 180`、`rtmp.duration: 600`。
- `repeat: 50` 保持与 stress 一致：Runner 每轮 repeat 都完整遍历一次 photo_modes，
  即每个模式各拍 50 次。

**未改任何源码**：现有 `override` + `repeat` 机制已足够（`PhotoModule.run()` 遍历
`photo_modes` 配置列表，`task.override` 在 scenario 级覆盖、不污染
`config/modules/photo.yaml` 的全局默认 `["auto"]`）。

## 改了哪些文件
- `ATS/config/scenarios/stress_traverse_photo_mode.yaml`（新增，纯配置）

## 如何验证
1. `list_scenarios()` 返回包含 `stress_traverse_photo_mode` → PASS。
2. 场景解析：name/loop/prepare/cleanup 与 stress 一致；photo task `override.photo_modes`
   为 7 模式、`repeat=50`；video/rtmp duration 正确 → PASS。
3. override 覆盖链路：`load_module_config('photo')` 全局默认仍 `["auto"]`（未被污染），
   `TestModule._merge(override)` 后 photo_modes 正确替换为 7 模式 → PASS。

## 已知遗留（TODO-CONFIRM，需真机核实）
- **7 个模式名未真机核实**。依据 `photo.yaml` 注释 + 需求文档推断，但存在命名不确定性：
  archive `VX100_EVB_自动化测试_软件需求文档.md` L483 记为 `cam_set photo hdr <0-3>`
  （hdr 带参数），与本配置的 `hdr_0~3` 独立命名可能不一致。真机核实时需确认 hdr 到底用
  独立模式名（`hdr_0`）还是参数形式（`hdr 0`），并据实修正 `photo_modes` 列表。
- 尚未真机跑（与 current_status P0 一致）。冒烟建议先临时改 `repeat: 2` 快速验证，
  再恢复 50。

## 文档影响（报告给 Document Agent，Code Agent 不改）
`docs/05_handoff/next_step.md` P2（新增场景 stress_traverse_photo_mode）已实施完成，
应由 Document Agent 将状态从「待实施」更新为「已实施、待真机核实模式名」。
