# 需求文档：video_loop 场景录像分辨率设为 3K

> 提出方：Document Agent（根据用户口述「video_loop 设置分辨率为 3K」整理，交由 Code Agent 实施）
> 状态：待实施（含 TODO-CONFIRM 待真机核实，见 §4）
> 关联：`docs/03_development/archive/恢复需求_video录像前恢复cam_set.md`（已实施，devlog `20260907_1652`，录像前恢复 `cam_set` 发送）

## 1. 背景

录像前 `cam_set video <resolution>` 已于 2026-09-07 恢复（devlog `20260907_1652`）。恢复后，`video.py` 读取：

```python
resolution = self.config.get("video_resolution", "1080p")
```

参数合并链（`runner.py` L97-102）：`config/modules/video.yaml` 默认值 + `task.override` + `task.duration`。

当前 `ATS/config/scenarios/video_loop.yaml` 的 video task **未写** `video_resolution`，落到模块默认 `1080p`。现用户要求该场景录像分辨率设为 **3K**。

## 2. 现状（Document Agent 已核对）

`ATS/config/scenarios/video_loop.yaml`：

```yaml
  tasks:
    - module: video
      duration: 66      # 单次录像时长（秒），自行按需配置
      override:
        video_ftp_download: true
```

`ATS/config/modules/video.yaml`（模块默认）：

```yaml
video_resolution: "1080p"
```

## 3. 改动要求（纯配置，不改源码）

在 `video_loop.yaml` 的 video task `override` 下新增 `video_resolution`，显式声明分辨率：

```yaml
  tasks:
    - module: video
      duration: 66
      override:
        video_ftp_download: true
        video_resolution: "3k"
```

- **只改 `ATS/config/scenarios/video_loop.yaml`**，不碰 `video.py` / `config/modules/video.yaml` / 其它场景。
- 该值最终拼为串口命令 `cam_set video 3k`（`video.py` 内 `f"cam_set video {resolution}"`）。

## 4. TODO-CONFIRM（必须真机核实，实施前不可视为已定）

> TODO-CONFIRM
>
> 目标档位 `3k` 与现有文档记录**冲突**，需要真机/工程师确认，不能凭口述直接当成固件已支持。

1. **档位是否合法**：devlog `20260817_0203_RTMP探测失败_板子编码慢关键帧稀疏加大超时.md` L37 明确记录「板子分辨率只支持 `4k`/`1080p` 两档，1080p 已是最低」。**`3k` 不在已知档位内**。若固件当前版本新增了 `3k`，需更新该历史认知（新 devlog 留痕），否则 `cam_set video 3k` 可能报错导致录像 FAIL。
2. **档位精确拼写**：`cam_set` 档位字符串由 `resolution` 值直接拼接，大小写/格式必须与固件命令完全一致。本文按项目内 `4k` 的小写风格暂写 `"3k"`，但**待确认**固件实际接受的是 `3k` / `3K` / `3k@30` 或其它形式。
3. **需求层面**：`VX100_EVB_自动化测试_软件需求文档.md` L166 记「v1p2 已删除 4K 分辨率，仅测试 1080p」。本次「3K」与「仅测 1080p」的既有结论不一致，需明确 3K 是新增测试档位还是临时验证。

## 5. 验收标准

1. `video_loop.yaml` 的 video task `override.video_resolution` 为确认后的正确档位字符串。
2. `python3 -m ATS.main --scenario video_loop --no-interactive-wifi`（或就绪环境的等价跑法）真机执行时，录像前串口可见 `cam_set video <档位>` 发送且返回成功（`exec_sync` 不 FAIL），随后 `Record Start|f_index=` 触发、`Video recording completed successfully.` 判 PASS。
3. 若真机确认 `3k` 非法，Code Agent 应报告实际支持的档位集合（`cam_set` 帮助输出或工程师答复），并据此回写本节 TODO-CONFIRM 结论。

## 6. 边界确认

- **纯配置改动**（Level 1），不改源码，不新增 ADR，不动 `01_architecture/` / `02_design/`。
- **改配置必留痕**（工程红线 1）：改动后新建 `docs/03_development/devlog/<YYYYMMDD>_<HHMM>_<描述>.md` 并更新其 README 索引。
- **TODO-CONFIRM 处置**：实施前真机/工程师核实档位合法性；结论与依据写入 devlog。若确认固件不支持 `3k`，Code Agent 停在「报告档位集合」这一步，不要臆造近似值（如擅自退回 `4k`）——由用户/工程师拍板后另立需求。
- **handoff 由 Document Agent 负责**：Code Agent 不要改 `docs/05_handoff/`。实施完成后由 Document Agent 复核，并同步 known_issue 中「分辨率两档」相关表述（若固件确已新增 3K 档）。
