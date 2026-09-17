# 需求文档：新增录像组合 480p_1（解除禁用 + 定义 profile + stress.yaml 接入）

> 提出方：Document Agent（按用户口述整理，交由 Code Agent 实施）
> 状态：已实施（2026-09-17，devlog `20260917_1659_video新增480p_1组合.md`）

## 1. 背景

录像 size 命令表 `ATS/drivers/video_commands.py` 现有 11 个可用组合，另有 1 个
`480p_1` 被列入 `BLOCKED_VIDEO_PROFILES`（禁用原因：`用户手测报错刷屏，本轮明确不测试`），
且 **`VIDEO_PROFILES` 里没有 `480p_1` 的 profile 定义**（历史手测表只给了 480p_0=640×480、
480p_2=800×600，480p_1 因报错无可信映射）。

用户反馈：**固件已修复** 480p_1 报错刷屏问题，现要求把 480p_1 重新纳入测试。

## 2. 需求（三件事一起做，用户已确认）

1. 在 `ATS/drivers/video_commands.py` 的 `VIDEO_PROFILES` 新增 `480p_1` 的 profile 定义。
2. 从 `BLOCKED_VIDEO_PROFILES` 解除对 `480p_1` 的禁用。
3. 在 `ATS/config/scenarios/stress.yaml` 的 video task 中新增 `480p_1` 一项。

## 3. 具体改动

### 3.1 `ATS/drivers/video_commands.py`

**① 新增 profile**（插在 `480p_0` 之后、`480p_2` 之前，保持 size 顺序）：

```python
    "480p_0": VideoProfile("480p_0", "cam_set video 480p 0", 640, 480, "横屏"),
    "480p_1": VideoProfile("480p_1", "cam_set video 480p 1", 640, 480, "横屏"),  # 固件已修复，重新纳入；预期值 TODO-CONFIRM 待真机实测
    "480p_2": VideoProfile("480p_2", "cam_set video 480p 2", 800, 600, "横屏"),
```

- 命令形式 `cam_set video 480p 1` 与 480p_0/480p_2 同构（`480p` 后跟下标参数）。
- `width/height/orientation` 是**预期值，非脚本实测值**（沿用文件 docstring 语义）。
  用户给定预期 `640×480 横屏`，但这是用户口述估计值，**建议真机 ffprobe 实测后校准**，
  标记 TODO-CONFIRM（与 480p_0 同为 640×480，需真机区分确认）。

**② 解除禁用**：从 `BLOCKED_VIDEO_PROFILES` 移除 `480p_1` 条目。

移除后该映射为空，保留空 `MappingProxyType({})` 并加一行注释说明即可（不要删掉
`BLOCKED_VIDEO_PROFILES` 常量本身 —— `video.py` 的 `resolve_video_profile` 仍引用它做
校验，删常量会导致 NameError）：

```python
BLOCKED_VIDEO_PROFILES: Mapping[str, str] = MappingProxyType({
    # 历史禁用项 480p_1（报错刷屏）已于 2026-09-17 解除：固件已修复，重新纳入 VIDEO_PROFILES。
})
```

### 3.2 `ATS/config/scenarios/stress.yaml`

在现有 `480p_0` 与 `480p_2` 两个 video task **之间**插入 `480p_1`，参数与相邻两项对齐：

```yaml
    # 480p_0: 预期 640x480 横屏（用户手测映射，非本次测量）
    - module: video
      repeat: 1
      duration: 10
      override:
        video_resolution: "480p_0"

    # 480p_1: 预期 640x480 横屏（用户口述估计，TODO-CONFIRM 待真机 ffprobe 校准）
    - module: video
      repeat: 1
      duration: 10
      override:
        video_resolution: "480p_1"

    # 480p_2: 预期 800x600 横屏（用户手测映射，非本次测量）
    - module: video
      repeat: 1
      duration: 10
      override:
        video_resolution: "480p_2"
```

### 3.3 同步过时注释（`ATS/config/scenarios/video_size_traverse.yaml`）

该文件 L7 注释 `# 480p_1 已知报错刷屏，不列入 tasks，命令解析器也会拒绝该组合。`
已过时（固件已修复、不再禁用）。**是否把 480p_1 也加入 `video_size_traverse` 不在本需求
范围内**，但需同步该行注释为事实（480p_1 现可用，本场景暂未列入 tasks 系策略选择，
而非禁用）。由 Code Agent 一并修正注释措辞，避免留下错误断言。

## 4. 验收标准

- `python3 -c "from ATS.drivers.video_commands import resolve_video_profile; p=resolve_video_profile('480p_1'); print(p)"`
  能成功返回 `VideoProfile(key='480p_1', command='cam_set video 480p 1', width=640, height=480, orientation='横屏')`，不再抛 `VideoProfileError`。
- `480p_1` 不在 `BLOCKED_VIDEO_PROFILES` 中。
- `python3 -m ATS.main --scenario stress` 正常解析，480p_1 video task 被识别（无 ERROR）。
- 真机跑 `stress` 后，`logs/stress/.../videos/` 下出现 `480p_1_<ts>_Video_*.h265`，
  report 出现 `video[480p_1]`，且落盘分辨率经 ffprobe 实测应与 640×480 一致（若不符，
  回填校准 `video_commands.py` 的 width/height，TODO-CONFIRM 关闭）。

## 5. 边界确认

- **只改 3 处**：`video_commands.py`（+profile、-禁用）、`stress.yaml`（+480p_1 task）、
  `video_size_traverse.yaml`（仅注释修正）。不改 `video.py` 业务逻辑、不改 Runner/Scenario。
- 解除禁用后 `resolve_video_profile` 对 `480p_1` 的拒绝逻辑自动消失（因为它只在
  `BLOCKED_VIDEO_PROFILES` 命中时报错，定义好 profile + 移出禁用即可，无需改 `video.py`）。
- **预期宽高 TODO-CONFIRM**：`640×480` 为用户口述估计，与 `480p_0` 相同；真机需 ffprobe
  实测确认两者是否真的同为 640×480（若不同以实测为准回填）。
- **用户手改（留痕，非本需求正文）**：实施期间用户自行把 `stress.yaml` 全部 video task
  参数调整为 `repeat:1` + `duration:20`（原 `sd1080p_0/1` 为 repeat=10、其余 duration=10）。
  属手动参数调整，随本需求一并留痕，Code Agent 无需处理、不得回退。
- 按工程红线 1，改 `ATS/` 代码后需在 `docs/03_development/devlog/` 新建记录并更新其
  README 索引。
