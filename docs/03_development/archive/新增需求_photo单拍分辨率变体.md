# 需求文档：photo 单拍模式新增 3 个分辨率变体

> 提出方：Document Agent（按用户口述整理，交由 Code Agent 实施）
> 状态：已实施（2026-09-17，devlog `20260917_1620_photo单拍新增3个分辨率变体.md`）

## 1. 背景

现有 photo 模块支持的模式为 `auto / single / mfnr / hdr_0~3`（见
`ATS/drivers/photo_commands.py` 的 `PHOTO_MODES` 枚举与 `ATS/config/modules/photo.yaml`
注释）。`single`（单拍）目前只有一种默认分辨率，用户要求新增 3 个带分辨率的
单拍变体：

| 序号 | 命令 |
|------|------|
| 1 | `cam_set photo single 1080p` |
| 2 | `cam_set photo single 720p` |
| 3 | `cam_set photo single 480p` |

## 2. 需求

1. 在 `ATS/drivers/photo_commands.py` 的 `PHOTO_MODES` 枚举中新增上述 3 个模式
   （遵守 ADR-011：协议集中化，`drivers/<module>_commands.py` 为唯一来源）。
2. 在**当前 `ATS/config/scenarios/stress.yaml`** 的 photo task `override.photo_modes`
   列表中追加这 3 个模式名。

## 3. 实现方式（预计不涉及业务代码改动）

已核查：`ATS/modules/photo.py` 用
`commands.PHOTO_SET_COMMAND.format(mode=mode)` 拼命令
（`photo.py` L77，`PHOTO_SET_COMMAND = "cam_set photo {mode}"`），
`format` 只是把 `{mode}` 替换为字符串，因此 `mode="single 1080p"` 会直接得到
`cam_set photo single 1080p`，**含空格的模式名天然支持，photo.py 无需改动**。

`PHOTO_MODES` 目前是"合法模式名唯一来源文档"（其 value 未被业务代码引用，
业务用模板拼命令），新增 3 条仅用于保持枚举完整、与 `photo_modes` 配置列表
一一对应：

```python
PHOTO_MODES: Mapping[str, str] = MappingProxyType({
    "auto": "cam_set photo auto",
    "single": "cam_set photo single",
    "single 1080p": "cam_set photo single 1080p",
    "single 720p": "cam_set photo single 720p",
    "single 480p": "cam_set photo single 480p",
    "mfnr": "cam_set photo mfnr",
    "hdr_0": "cam_set photo hdr_0",
    "hdr_1": "cam_set photo hdr_1",
    "hdr_2": "cam_set photo hdr_2",
    "hdr_3": "cam_set photo hdr_3",
})
```

`stress.yaml` 的 photo task 改为：

```yaml
    - module: photo
      repeat: 1            # Runner 每轮 repeat 都完整遍历一次 photo_modes
      override:
        # TODO-CONFIRM：single 1080p/720p/480p 三个模式名需真机核实是否为固件
        # 支持的合法 cam_set photo <mode> 参数形式（见第 6 节）。
        photo_modes: [auto, single, single 1080p, single 720p, single 480p, mfnr, hdr_0, hdr_1, hdr_2, hdr_3]
```

## 4. 只改 stress.yaml，不动其它场景

- 不改 `ATS/config/scenarios/stress_traverse_photo_mode.yaml`、
  `stress_traverse_photo_mode_3k.yaml`（用户仅指定当前 `stress.yaml`）。
- 不改 `ATS/config/modules/photo.yaml` 的全局默认 `photo_modes: ["auto"]`
  （保持 `normal` 等其它场景行为不变）。
- 若 `photo.yaml` 注释 `# 可扩为 [...]` 需要同步新枚举，属可选，由 Code Agent
  一并核对后决定。

## 5. 验收标准

- `python3 -m ATS.main --scenario stress` 能正常跑，无场景解析错误。
- 跑一轮（可先小 `loop.count` 冒烟）后，`logs/stress/.../photos/` 下应能看到
  `single 1080p`、`single 720p`、`single 480p` 三种模式各自的拍照结果，
  report 里出现 `photo[single 1080p]` / `photo[single 720p]` / `photo[single 480p]`
  条目。
- 其余 task（video/video_integrity/rtmp）行为与改动前一致（仅 photo 列表变化）。

## 6. 边界确认与待核实点（TODO-CONFIRM）

- **固件命令形式**：用户给的是 `cam_set photo single 1080p`（三个 token）。
  需真机核实固件实际接受的写法是「`single` 后跟分辨率参数」还是独立模式名
  （参考既有 `hdr_0~3` 是独立命名，与软件需求文档 `cam_set photo hdr <0-3>`
  参数形式不一致的同类疑问）。以真机实测/固件手册为准。
- **含空格模式名的副作用**：`photo.py` L72 `name = f"photo[{mode}]"` 会生成
  `photo[single 1080p]`，L129 本地文件名会生成
  `single 1080p_<ts>_<jpg>`。功能上无碍，但需确认 report 消费方、日志解析
  是否对含空格的 name 敏感（若敏感需在需求内约定映射到无空格标识，先停下
  产出 Document Agent Request，不要自行改判据名）。
- **不改动** `photo.py`、Runner、Scenario 数据结构 —— 现有 `PHOTO_SET_COMMAND`
  模板 + `override.photo_modes` 机制已够用。
- 按工程红线 1，改 `ATS/config` / `ATS/drivers` 后需在
  `docs/03_development/devlog/` 新建记录并更新其 README 索引。
