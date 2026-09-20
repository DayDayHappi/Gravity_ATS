# BUG-005：exec_sync 环形缓冲滚满后快照定位失效致 cam_set 误判

## Problem

stress 压测约第 26 轮起，photo/video 的 `cam_set photo|video <mode>` 全判 FAIL（真机 2026-09-18），
photo 提前 return 不再发 `dfs_capture_start`；固件回显成功 + 哨兵及时出现，与判 FAIL 矛盾。

## Root Cause

`exec_sync`/`_wait_pattern` 用字符串前缀切片定位命令后新输出，`deque(maxlen=65536)` 滚满后
`full.startswith(snapshot)` 恒为 False → `new=full` 混入历史残留；无 expect 时 `_ERROR_RE`（含
`invalid`）命中 RTMP 阶段相机正常 fallback 日志 `preset capCfg ... invalid, use default`（780 条）
→ 误判 FAIL。两层叠加缺一不可。

## Solution

方案 A：快照定位从「字符串前缀」改「单调递增序号游标」（`deque(str)` → `deque(tuple[int,str])`，
`_snapshot_seq`/`_buffer_text_since`）；并收窄 `_ERROR_RE` 排除 `invalid[, ]use default`。

## Verification

离线模拟 deque 滚满（65536 旧数据 + 780 invalid 残留）后游标定位精确取到命令后增量、哨兵正常匹配、
`_judge` 判 PASS；`py_compile` + 消费方 import 通过。待真机 stress 26 轮验证。

## 关联

- devlog：`20260920_1053_修复环形缓冲滚满致cam_set误判_方案A序号游标定位.md`
- 排查报告：`../archive/串口环形缓冲满导致cam_set误判_排查报告.md`
- 待办：`../../05_handoff/next_step.md`（P0）
