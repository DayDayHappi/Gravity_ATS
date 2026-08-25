# photo 判据改 Capture completed successfully. + 路径改从累积缓冲扫描

## 日期
2026-08-25

## 变更来源
Document Agent Request（含实测日志证据）。判据字符串缺陷已由实测日志坐实，属模块内部改动（Level 1），仅改 `ATS/modules/photo.py`。

## 根因（实测日志证实）
- 成功时序固定三行：`jpeg deinit success` → `Save Photo Successful: <dir>` → `Capture completed successfully.`，之后脚本才发下一条命令。
- 旧判据 `Save Photo Successful:\s*(\S+)` 在 `Save Photo Successful:` 行即匹配成功，但此时相机日志未打印完、且该行路径可能被串口分块截断
  （实测 `Save Photo Successful: /e` 截断），导致：
  1. 脚本提前发 `cam_set photo auto`，打断相机流程，剩余路径与 `Capture completed successfully.` 错位到命令之后；
  2. 捕获组拿到截断路径 `/e`，目录错误 → 误判。

## 做了什么
1. 主判据：`exec_async("dfs_capture_start", expect=...)` 由 `r"Save Photo Successful:\s*(\S+)"`
   改为 `r"Capture completed successfully."` —— 它是相机日志全部打印完的完成标志，等它再判定，期间不打断。
2. 路径提取：删除 `Save Photo Successful` 行的捕获组依赖（`r.matched`），改为从 `r.clean`（exec_async
   累积的完整缓冲）按目录结构扫描：
   `re.search(rf"{re.escape(_PIC_DIR)}/[^\s/]+/", r.clean)` → `m2.group(0).rstrip("/")`。
   等 `Capture completed successfully.` 时整条路径已在缓冲中拼接完整，扫描可靠。

## 改了哪些文件
- `ATS/modules/photo.py`（仅此一个源文件；`_PIC_DIR = "/emmc/PIC"` 既有常量未动；`exec_async`/`Response` 接口不动）

## 如何验证
1. `python3 -m py_compile ATS/modules/photo.py` → PASS。
2. 模拟成功案例缓冲：`Save Photo Successful: /emmc/PIC/20260101_000055_5712/` + `Capture completed successfully.`
   → 扫描出 `/emmc/PIC/20260101_000055_5712` → PASS。
3. 无路径边界：仅 `Capture completed successfully.` → `save_dir=""`，走「FTP 验证跳过」分支，不崩溃 → PASS。
4. `grep` 确认 photo.py 无旧判据 `Save Photo Successful:`（仅注释）与 `r.matched` 残留 → PASS。

## 已知遗留（待真机验证）
- 分块截断（`Save Photo Successful: /e`）是旧判据提前发命令打断的**错位产物**；新判据下不会再提前打断，
  路径应在完成标志前完整打印。真机需确认拍照连续多模式（auto 等）不再出现提前发命令/目录错误。
- `serial_console.py` 经核实无需改（`_wait_regex` 返回的 `r.clean` 是命令发出后完整累积输出）。

## 文档影响（报告给 Document Agent，Code Agent 不改）
判据字符串 `Save Photo Successful` 写死在下述文档中，随本次改动而过时，待 Document Agent 同步：
- docs/01_architecture/module_design.md（L18、L81）
- docs/01_architecture/data_flow.md（L28）
- docs/04_testing/test_case.md（L12）
- docs/04_testing/test_strategy.md（L14）
- ATS/README.md（L195、L202）
