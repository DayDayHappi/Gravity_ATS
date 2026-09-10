# 需求文档：video_size_traverse 场景接入 H265 视频完整性检测

> 提出方：Document Agent（按用户口述整理，交由 Code Agent 实施）
> 状态：已实施（devlog `20260909_1940`，待真机）

## 1. 背景

`video_size_traverse` 场景（commit `d7cee21`「增加 11 种录像 size 遍历」）设计之初
刻意**不接 H265 检测**，头注释第 12 行写明：

> `本场景不自动做 H265 检测、RTMP 或格式化`

现用户要求给该场景加上视频完整性检测（`video_integrity`），形成「录像 → 检测」闭环。

## 2. 现状（含用户未提交的手动改动）

`ATS/config/scenarios/video_size_traverse.yaml` 当前工作区存在**未提交**的手动改动：

| 位置 | 改动 |
|------|------|
| `loop.count` | 1 → 10 |
| `sd1080p_0` task | `repeat` 1 → 10 |
| `sd1080p_1` task | `repeat` 1 → 10 |
| 末尾新增 | `photo` task（遍历 7 模式）+ `rtmp` task（66s） |

本轮需求**基于这个已改动的版本**继续改，不要 revert 用户的手动改动。

一轮实际录像文件数 = `sd1080p_0`×10 + `sd1080p_1`×10 + 其余 9 个 size 各 1 = **29 个**。

## 3. 需求

在所有 11 个 `video` task 之后（`photo` 之前）插入**一个** `video_integrity` task，
检本轮全部录像文件。推荐配置：

```yaml
    - module: video_integrity
      override:
        input:
          source: "current_run"
          selection: "all_unchecked"   # 检本轮全部未检文件；跨 loop 靠 manifest 去重不重复检
          empty_input_policy: "skip"   # 某 size 录像失败/未下载时不判 FAIL，跳过而非双重惩罚
```

> 注意：**不能用** `latest_unchecked`（`stress_traverse_photo_mode` 场景用的是它，因为
> 那里 video 每轮只录 1 个文件）。本场景 video task 有 `repeat: 10`，`latest_unchecked`
> 只检最新 1 个会漏掉其余 9 个。

## 4. 关键技术事实（已核实，避免 Code Agent 重复调研）

- **`all_unchecked` 已存在**（devlog `20260908_1847`）：过滤已检 + 取全部，与
  `latest_unchecked` 对称，专为「video repeat 多文件 + 跨 loop 不重复检」设计。无需改代码。
- **不同 size 不会因 fps/gop 误判 FAIL**：`h265_validator.py` 主判据是 Stage 1 全文件
  decode（rc==0 且 error stderr 为空 → PASS）；`expected_fps`/`expected_gop_size`（现 30/30）
  只在计算缺失 POC 的**近似时间戳**时用（`_detect_missing_poc` → `approx_timestamp`），
  不参与 PASS/FAIL 判定。
- **本地文件名带 size 前缀不影响检测**：video.py（`d7cee21`）下载时改名为
  `{profile.key}_{板端目录}_{原文件名}`（如 `sd1080p_0_..._Video_1_0.h265`），仍是
  `.h265` 后缀，会被 `video_integrity` 的 `*.h265` pattern 命中。
- **override 深合并**：`video_integrity` 模块已实现 `_merge` 深合并（§7），override 的
  `input` 不会整段替换默认 input，`patterns`/`recursive`/`current_run_subdir` 等默认值保留。
- **默认 `empty_input_policy` 是 `fail`**（`video_integrity.yaml` L15）：本场景必须显式
  override 为 `skip`，否则某个 size 录像失败导致目录无文件时会判 FAIL（双重惩罚）。

## 5. 附带修正项（一并处理，属于本需求范围）

1. **头注释第 12 行矛盾**：`本场景不自动做 H265 检测、RTMP 或格式化` 与新增的
   `video_integrity` task、以及用户已加的 `rtmp` task 冲突。需改为准确描述（如
   `本场景保留每次录像后的 FTP 辅助下载；录像完成后统一做 H265 检测`，RTMP 是否保留
   以用户实际意图为准，Code Agent 若不确定请 TODO-CONFIRM）。
2. **cleanup 缺 `stop_stream` 兜底**：用户新增了 `rtmp` task，但 cleanup 只有
   `close_serial`（没有 `stop_stream`/`preview_stop`）。`rtmp` 模块自身在 run 末尾会
   `rtmp_video_stop`，但异常中断路径依赖 cleanup 兜底。建议 Code Agent 评估是否补
   `- stop_stream`（`preview.enabled=false`，`preview_stop` 可不必加）。

## 6. 验收标准

- `python3 -m ATS.main --list-scenarios` 仍能看到 `video_size_traverse`。
- 跑一轮后，report 中出现**一个** aggregate `video_integrity` 结果，`PASS=N` 其中 N 为本轮
  成功下载的录像文件数（约 29 个）。
- 某 size 录像失败/未下载时，`video_integrity` 为 SKIP（`empty_input_policy=skip`），不判 FAIL。
- 跨 loop 多轮：第二轮起已检文件不重复检（manifest 去重），无重复检测记录。

## 7. 边界确认

- 本需求**纯配置，不改源码**：只改 `video_size_traverse.yaml`，不动
  `video.py`/`video_integrity.py`/`h265_validator.py`/`video_commands.py`/core。
- 若 Code Agent 实施时发现需要「每个 size 单独出检测结果」而非一个 aggregate（当前
  `video_integrity` 聚合所有文件为单个 TestResult），属模块能力缺口，**停下产出
  `Document Agent Request`**，不要改模块（模块红线）。
- 按工程红线 1，改配置文件后需在 `docs/03_development/devlog/` 新建记录并更新 README 索引。
