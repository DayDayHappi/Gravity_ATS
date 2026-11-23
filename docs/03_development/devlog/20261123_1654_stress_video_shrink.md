# stress video 场景收缩（43 → 16 条 active，其余注释保留）

- **日期**：2026-11-23
- **任务**：按用户 2026-11-23 交接请求，把 `stress.yaml` 中 15 条 video task 整块加 `#` 注释（不删除），收缩 active video 到 16 条。
- **作用分支**：`feat/windows_rebuild_app_arch`
- **变更级别**：**Level 1**（纯场景配置，复用既有 `video` 模块能力，无接口/数据流/生命周期变更）。

## 1. 改了什么

把 `stress.yaml` 中用户指定的 **15 条** video task 整块加 `#` 注释（保持原缩进，不删除，便于恢复）。被注释项（按 res/fps/eis/codec 定位）：

| # | res | fps | eis | codec |
|---|-----|-----|-----|-------|
| 1 | 720p | 30 | 1 | h264 |
| 2 | 720p | 30 | 2 | h264 |
| 3 | 720p | 60 | 0 | h264 |
| 4 | 720p | 60 | 0 | h265 |
| 5 | 720p | 60 | 1 | h264 |
| 6 | 720p | 60 | 2 | h264 |
| 7 | 720p | 60 | 2 | h265 |
| 8 | 480p | 30 | 0 | h264 |
| 9 | 480p | 30 | 1 | h264 |
| 10 | 480p | 30 | 2 | h264 |
| 11 | 480p | 60 | 0 | h264 |
| 12 | 480p | 60 | 0 | h265 |
| 13 | 480p | 60 | 1 | h264 |
| 14 | 480p | 60 | 2 | h264 |
| 15 | 480p | 60 | 2 | h265 |

- 行 19（720p/30/0/h264）此前已由用户注释，本轮沿用。
- 同步更新文件头 video 注释：由「43 条可用集」改为「43 条收缩为 16 条 active，其余整块注释保留便于恢复」。

## 2. 收缩后 active video（16 条）

每档保留 h265 为主，另按用户指定保留部分 h264 变体：

- **3k**（1）：30/eis2/h265
- **1080p**（3）：30/eis1/h264、30/eis1/h265、30/eis2/h265
- **sd1080p**（4）：30/eis0/h265、30/eis1/h265、30/eis2/h265、60/eis1/h265
- **720p**（4）：30/eis0/h265、30/eis1/h265、30/eis2/h265、60/eis1/h265
- **480p**（4）：30/eis0/h265、30/eis1/h265、30/eis2/h265、60/eis1/h265

合计 **16**。全部 `ftp_download: false` / `duration: 20` / bitrate 18000000 / gop 30 / vui 709，无 4k。

## 3. 文件

- `ATS/config/scenarios/stress.yaml`（唯一改动文件，纯配置：15 条 video task 加 `#` + 头注释同步）。
- 本 devlog + `docs/03_development/devlog/README.md` 索引。

## 4. 验证（离线）

1. `python -m ATS.main --dry-run --scenario stress` → **exit 0**（契约校验通过）。
2. `grep -c '^    - module: video$'` = **16**（active）；YAML 解析 `tasks` 总数 = **25**（photo 8 + video 16 + rtmp 1）。
3. 脚本逐条打印 active 组合：per-res = `{3k:1, 1080p:3, sd1080p:4, 720p:4, 480p:4}`，total 16，与预期一致。
4. 720p 段由 8 条 → 4 条 active、480p 段由 8 条 → 4 条 active（各注释 7 条，加上此前已注释的 720p/30/0/h264 共 8 条）。
5. 全 active video 均 `ftp_download == False`、`duration == 20`、无 `4k`。
6. 全量单测 **130 tests OK**。

**真机验收**：未执行。

## 5. 已知限制

- 注释块保留占位，文件行数增长；恢复时逐条去掉行首 `#` 即可。
- 未真机验证 16 条 × 20s 在 stress 循环下的稳定性。

## 6. 验证结论

PASS（离线）。
