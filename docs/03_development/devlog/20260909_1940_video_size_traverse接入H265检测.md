# video_size_traverse 场景接入 H265 完整性检测 + 附带修正

## 日期
2026-09-09

## 变更来源
需求文档 [req_video_size_traverse_add_integrity.md](../03_development/archive/req_video_size_traverse_add_integrity.md)（Document Agent，P1 待实施）。基于工作区含用户未提交手动改动的版本继续改，未 revert。

## 做了什么
1. 在 11 个 video task 之后、photo 之前插入**一个** `video_integrity` task：
   ```yaml
   - module: video_integrity
     override:
       input:
         source: "current_run"
         selection: "all_unchecked"   # 一轮 29 个文件，latest_unchecked 只检 1 个会漏检
         empty_input_policy: "skip"   # 某 size 录像失败/未下载时不判 FAIL，跳过而非双重惩罚
   ```
2. 头注释第 9 行修正：「本场景不自动做 H265 检测、RTMP 或格式化」→「保留每次录像后的 FTP 辅助下载；录像完成后统一做 H265 检测，末尾接 photo 遍历 + RTMP 推流」。
3. cleanup 补 `- stop_stream` 兜底（用户新增 rtmp task，异常中断路径靠此兜底；幂等，未推流则忽略）。`preview.enabled: false`，无需 `preview_stop`。

## 关键事实（需求文档已核实，不重复调研）
- `all_unchecked` 已存在（devlog `20260908_1847`）：过滤已检 + 取全部，专为「video repeat 多文件 + 跨 loop 不重复检」。
- 不同 size 不会因 fps/gop 误判：主判据是 Stage 1 全文件 decode，`expected_fps/gop` 只用于近似时间戳。
- 本地文件名带 size 前缀仍是 `.h265`，被 `*.h265` pattern 命中。
- override 深合并：`input` 不整段替换，patterns/recursive/current_run_subdir 保留。
- 默认 `empty_input_policy=fail`，必须显式改 skip。

## 改了哪些文件
- `ATS/config/scenarios/video_size_traverse.yaml`（插入 video_integrity task + 头注释修正 + cleanup 补 stop_stream）

## 验证结果
1. yaml 校验：`video_size_traverse` 名称正确、task 顺序 `[video×11, video_integrity, photo, rtmp]`、video_integrity 仅 1 个且在 photo 前、override `selection=all_unchecked`/`empty_input_policy=skip`、cleanup 含 `stop_stream` → 全 PASS。
2. 用户手动改动保留：`loop.count=10`、`sd1080p_0/1` repeat=10、photo+rtmp task → 全保留。
3. `python3 -m ATS.main --list-scenarios` → 识别 `video_size_traverse` PASS。
4. 未跑真机（待 P0 批次统一真机验证）。

## 边界确认（需求文档 §7）
- 纯配置，不改源码（video.py/video_integrity.py/h265_validator.py/video_commands.py/core 全未碰）。
- 若后续发现需要「每个 size 单独出结果」而非单个 aggregate，属模块能力缺口，按需求文档要求停下产 Document Agent Request，不自行改模块。本次未触发（当前一个 aggregate 符合需求）。

## 文档影响（报告给 Document Agent，Code Agent 不改）
- `next_step.md` 新增的 P1「video_size_traverse 接入 H265 检测」条目 → 已实施，状态改为「待真机」。
