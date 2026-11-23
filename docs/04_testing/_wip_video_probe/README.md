# WIP：`cam_set video` 参数组合实测（**已由 2026-11-23 正式报告取代**）

> **状态：已完结。** 2026-11-23 Code Agent 按关键字式语法重跑全 60 组合并落正式报告
> [test_report_20261123](../test_report_20261123_video关键字式60组合实测.md)（devlog `20261123_1315`）。
> 本目录保留为历史存档（2026-11-20 位置式旧语法探针），**结论以正式报告为准**。
> ⚠️ 本文档下方「最多 3 个选项对」等规则基于旧固件/旧写法，**已被实测推翻**（6 对可用、关键字式才被接受），勿再引用。
> 数据文件（同目录）：`video_setgrid.json` / `video_rec_A.jsonl` / `probe_video_rec.py`（旧位置式）、`video_rec_kw60.jsonl` / `probe_video_kw.py`（新关键字式，正式报告源头）。

## 任务

逐条改变 `cam_set video` 参数尝试，区分「能执行/录像不出错」vs「录像有问题」。
用户给定取值（2026-11-20）：
- res：`3k / 1080p / sd1080p / 720p / 480p`（**4k 暂不支持，不测**）
- fps：`30 / 60`
- eis：`0 / 1 / 2`
- format：`h264 / h265`
- vui：`709 / 6010 / 6011`
- bitrate / gop：**不测、不显式配置**

## 🔴 已确认的固件规则（关键，决定测试设计）

1. **参数上限 = 最多 3 个「选项对」**（token 数封顶；`cam_set video <res>` 之后最多 3 个 `key value`）。
   - 4 个选项对（如 `fps 30 eis 2 format h264 vui 709`）→ `Too many args ! We only Use: …`
   - **⇒ `format` 与 `vui` 不能同一条命令下发**；bitrate/gop/vui/format 四者最多共存 3 个。
   - 是 **token 数**限制、不是行长限制（49 字符的 7-token OK；43 字符的 9-token 被拒）。
2. **`fps 60` 只在 `sd1080p / 720p / 480p`**；`3k`、`1080p` 用 60 报：
   `fps 60 not supported on <res>, use 30 or pick sd1080p|720p|480p for 60`
3. **`3k` 强制 `eis=2`**（请求 eis 0/1/2，固件一律回 `eis=2`）。
4. **`vui` 单独下发会重置其它字段**（第二条 `cam_set` 不保留上一条未写字段）→ 组合无法跨命令拼。
5. SET 成功回显：`video: size=<res> fps=<fps> eis=<eis> format=<fmt> bitrate=18000000 gop=30 vui=<vui>`（未写的字段回默认：bitrate 18000000 / gop 30 / vui 709）。

## SET 阶段全网格结果（`video_setgrid.json`，60 条 = 5 res × 2 fps × 3 eis × 2 fmt）

- **OK 48 条 / ERR 12 条**。ERR 全部是 `fps 60` 打在 `3k`(6) + `1080p`(6)。
- 其余 res × fps30 全 OK（含 eis 0/1/2）；`sd1080p/720p/480p` × fps 30/60 全 OK。
- **注**：SET 只反映"命令是否被接受"，不代表录像一定成功 → 还需录制验证（见下）。

## 录制测试进度（`probe_video_rec.py`）

脚本按两个家族跑（因 format/vui 不能共存）：
- **家族 A**：`cam_set video <res> fps <fps> eis <eis> format <h264|h265>`（22 组 valid × 2 = **44 条**）
- **家族 B**：`cam_set video <res> fps <fps> eis <eis> vui <709|6010|6011>`（22 × 3 = **66 条**）

每条：SET → `cam_run video start` → 录 ~3s → `cam_run video stop` → 判据 `Video recording completed successfully.` + 存活检测。

### 家族 A：已完成 **13 / 44**，**全部 OK（0 失败）**

| # | 命令 | 结果 | 落盘文件 |
|---|---|---|---|
| 1 | 3k fps30 eis2 format h264 | ✅ OK | Video_*.h264 |
| 2 | 3k fps30 eis2 format h265 | ✅ OK | Video_*.h265 |
| 3-4 | 1080p fps30 eis0 h264/h265 | ✅ OK | |
| 5-6 | 1080p fps30 eis1 h264/h265 | ✅ OK | |
| 7-8 | 1080p fps30 eis2 h264/h265 | ✅ OK | |
| 9-10 | sd1080p fps30 eis0 h264/h265 | ✅ OK | |
| 11-12 | sd1080p fps30 eis1 h264/h265 | ✅ OK | |
| 13 | sd1080p fps30 eis2 h264 | ✅ OK | |
| 14 | sd1080p fps30 eis2 h265 | ⏳ **断点（未跑完）** | |

**续跑起点**：家族 A 第 14 条（`sd1080p fps 30 eis 2 format h265`）。
剩余：家族 A 第 14–44（31 条）+ 家族 B 全部 66 条 = **约 97 条待跑**（~15s/条 ≈ 24 分钟）。

## 恢复方法

```bash
# 板子须先确认存活+idle：
#   echo PING / cam_run status（应为 state: idle）
cd C:/Users/x-jwwang/AppData/Local/Temp
python probe_video_rec.py --family=A --limit=44    # 或先跳过已跑的前 13 条
python probe_video_rec.py --family=B               # 家族 B 全 66 条
```

> `probe_video_rec.py` 会写 `video_rec_A.jsonl` / `video_rec_B.jsonl`；全程带存活检测，HANG 即停。
> 建议恢复前先给脚本加"跳过已完成"逻辑（读 jsonl 已有 res/fps/eis/fmt 组合跳过）。

## 板子状态（暂停时）

- **已停录，干净 idle**（`cam_run video stop` 已补发，`state: idle`，串口无持续输出）。
- 无需断电。

## 待办（恢复后）

1. 续跑家族 A 第 14–44、跑完家族 B 66 条；
2. 汇总「录像可用 / 录像有问题」两张表；
3. 若发现录像 FAIL，记录固件原文（`E/…`/`fail`/`context` 等）；
4. 落正式报告到 `docs/04_testing/`，并更新 `known_issue.md` / `ADR` 相关条目。

## TODO-CONFIRM（恢复前请确认）

- 家族 B 是否必要？（`vui` 是编码色彩标签，可能不影响"录像是否成功"；若要省时间可只抽测几条）
- 是否要在正式测试里纳入 `bitrate`/`gop`（用户当前说不需要）？
