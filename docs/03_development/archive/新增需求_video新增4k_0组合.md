# 需求文档：新增录像组合 4k_0（只加定义，待真机校准，暂不接场景）

> 提出方：Document Agent（按用户口述整理，交由 Code Agent 实施）
> 状态：待实施（2026-09-18）

## 1. 背景

录像 size 命令表 `ATS/drivers/video_commands.py` 现有 12 个组合（`VIDEO_PROFILES`）。
用户新增需求：录像新增 size 组合 **`cam_set video 4k 0`**。

- 历史背景：软件需求文档 archive `VX100_EVB_自动化测试_软件需求文档.md` L166 曾记
  「v1p2 已删除 4K 分辨率，仅测试 1080p」——4k 是**历史上被删除过的档位**，现固件
  **新增功能**重新支持，用户确认 `cam_set video 4k 0` 合法。
- 预期分辨率（width/height/orientation）**未知**，用户拍板「待真机校准」。

## 2. 需求（只做一件事，用户已确认）

1. 在 `ATS/drivers/video_commands.py` 的 `VIDEO_PROFILES` 新增 `4k_0` 的 profile 定义。
2. **暂不接入任何 scenario**（`stress.yaml` / `video_size_traverse.yaml` 均不动）。
3. 不动 `BLOCKED_VIDEO_PROFILES`、不动 `video.py`、不动 Runner/Scenario。

## 3. 具体改动

### 3.1 `ATS/drivers/video_commands.py`

在 `VIDEO_PROFILES` 映射**最前**（`"sd1080p_0"` 之前，4k 为最大档位）新增：

```python
VIDEO_PROFILES: Mapping[str, VideoProfile] = MappingProxyType({
    # 4k 档位（固件新增功能，重新支持）；预期 size 未知，占位值 0x0 仅表示未校准，
    # 非真实分辨率。TODO-CONFIRM：待真机 ffprobe 校准后回填 width/height/orientation。
    "4k_0": VideoProfile("4k_0", "cam_set video 4k 0", 0, 0, "待校准"),
    "sd1080p_0": VideoProfile("sd1080p_0", "cam_set video sd1080p 0", 1920, 1080, "横屏"),
    ...
})
```

要点：

- **key 命名**：`4k_0`，与现有 `3k_2`（`cam_set video 3k 2`）、`480p_1`（`cam_set video 480p 1`）
  同构——`4k` 后跟下标参数 `0`。
- **占位值**：`width=0, height=0, orientation="待校准"`。
  `VideoProfile` 是 frozen dataclass，三字段必填；`video.py` 的 `_mk` 只用 width/height
  做 report 展示（`预期 size: {width}x{height} ({orientation})`），**不参与判据计算**，
  故 0 占位安全、且不会误导成某个猜测值。
- **TODO-CONFIRM 注释**：明确「0x0 为占位，非真实 size」，真机 ffprobe 校准后回填。

## 4. 验收标准

```bash
python3 -c "from ATS.drivers.video_commands import resolve_video_profile; p=resolve_video_profile('4k_0'); print(p)"
# 期望输出（占位值）：
# VideoProfile(key='4k_0', command='cam_set video 4k 0', width=0, height=0, orientation='待校准')
```

- `resolve_video_profile('4k_0')` 不抛 `VideoProfileError`。
- `python3 -m ATS.main --list-modules` / `--list-scenarios` 无 import 破坏。
- 现有 12 个组合的 `resolve_video_profile` 行为不变（纯增量）。

## 5. 边界确认

- **只改 1 处源码**：`video_commands.py`（+1 条 profile）。不改 `video.py`、不改场景、
  不改 Runner/Scenario、不改 `BLOCKED_VIDEO_PROFILES`。
- **不接场景**：`4k_0` 定义后无任何 scenario task 引用，不会被自动执行；待真机校准
  回填预期 size 后，再按需接入（届时另开需求）。
- **video_size_traverse.yaml 头注释「11 个组合」暂不改**：该场景 tasks 仍列 11 项
  （4k_0 未接入），注释仍准确。
- **文档影响（实施后由 Document Agent 收尾）**：`current_status.md` 多处「11 种 size
  组合」在 4k_0 加入 `VIDEO_PROFILES` 后总数由 12 变 13（480p_1 已于 2026-09-17
  解除禁用并加回，故加入 4k_0 前是 12 条），需同步为「13 种」（待收尾）。
- 按工程红线 1，改 `ATS/` 代码后需在 `docs/03_development/devlog/` 新建记录并更新其
  README 索引。

## 6. 待真机

- 真机 `cam_set video 4k 0` 后，板端回显 `w(...) * h(...)` 及落盘 ffprobe 实测分辨率，
  回填 `video_commands.py` 的 `4k_0` width/height/orientation，关闭 TODO-CONFIRM。
