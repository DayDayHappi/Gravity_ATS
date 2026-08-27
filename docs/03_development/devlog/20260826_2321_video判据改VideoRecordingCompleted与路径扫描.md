# video 判据改 Video recording completed successfully. + 路径改累积缓冲扫描

## 日期
2026-08-26

## 变更来源
`docs/05_handoff/next_step.md` 顶部 🔴 紧急待办。与 photo 判据修复（devlog `20260825_0514`）同类的对称 bug，实测日志
（`logs/stress/logs/20260826_030311/serial.log`）已坐实。

## 根因（实测日志证实）
- 正确完成标志：`Video recording completed successfully.`（录像全流程走完的最终标志）。
- 旧判据 `Save Video Successful:\s*(\S+)` 有两个问题：
  1. `Save Video Successful` 出现更早（实测约早 2s），此时录像收尾（编码 finalize/落盘）未完成；
  2. 其路径会被串口分块截断。日志大量实例：
     - L524 `Save Video Successful: /emmc/VI` + L525 `DEO/.../Video_7006_0.h265`
     - L12259 `Save Video Successful: /emmc` + L12260 `/VIDEO/.../Video_1511_0.h265`
     - L14210 `Save Video Succes` + L14211 `sful: /emmc/VIDEO/...`（连关键词都被切碎）
     旧代码从捕获组 `r.matched` 取到截断路径 `/emmc/VI`，导致 `ftp2.size()` 校验对象错误 →
     偶发 FAIL / 校验跳过（flaky）。

## 做了什么
1. 主判据：`expect=r"Save Video Successful:\s*(\S+)"` → `expect=r"Video recording completed successfully."`。
2. 路径提取：删除捕获组依赖（`r.matched`），改为从 `r.clean`（exec_async 累积的完整缓冲）扫描：
   `re.search(rf"{re.escape(_VIDEO_DIR)}/[^\s/]+/Video_[^\s]+\.h265", r.clean)` → `m2.group(0)`。
   分块只影响串口 read 时机，缓冲 `"".join` 后路径连续，等完成标志时整条路径已拼接完整，扫描可靠。

## 改了哪些文件
- `ATS/modules/video.py`（仅此一个源文件；`_VIDEO_DIR = "/emmc/VIDEO"` 既有常量未动；exec_async/Response 接口不动）

## 如何验证
1. `python3 -m py_compile ATS/modules/video.py` → PASS。
2. `from ATS.modules import video` → PASS。
3. `grep` 确认无旧判据 `Save Video Successful:\s*` 与 `r.matched` 残留 → PASS。
4. 用真实日志数据构造 r.clean（含完整路径 + Imu 干扰行 + 完成标志）：
   - 完整路径 `.../Video_7006_0.h265` 正确提取 → PASS；
   - `Imu_7006.bin` 不误匹配（正则限定 `Video_` 前缀）→ PASS；
   - 无路径边界（仅完成标志）→ `video_path=""`，走「未校验大小」分支，不崩溃 → PASS。

## 已知遗留（待真机验证）
- 全部改动尚未真机（与 current_status P0 一致）。真机需确认 video 连续多轮不再出现
  `Save Video Successful` 路径截断导致的 flaky FAIL / 校验跳过。
- `dfs_video_stop` 的 `result_timeout=25.0` 未改；若真机出现完成标志偶尔超过 25s，
  再单独评估是否放宽（本次不改，避免扩大范围）。

## 文档影响（报告给 Document Agent，Code Agent 不改）
next_step.md 顶部 🔴 已注明「文档已同步（test_case / test_strategy / data_flow / module_design /
README §7.4），源码待 Code Agent 改」——即文档已先行同步，本次仅源码落地，无新增文档影响。
