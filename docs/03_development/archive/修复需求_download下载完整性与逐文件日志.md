# 需求文档：download 场景下载完整性与逐文件日志修复

> 提出方：Document Agent（根据用户首轮真机运行暴露的问题分析整理，交由 Code Agent 实施）
> 状态：待实施
> 关联：`docs/03_development/archive/新增需求_download场景仅下载不测试.md`（download 场景原始需求）

## 1. 背景

download 场景（`--scenario download`，仅从板端 FTP 下载、不做测试）首轮真机运行后，用户报告两个现象：

1. 脚本运行时**没有打印单个文件下载是否成功**，只能看到一条条「下载 X -> Y」，无法逐文件确认。
2. 打开下载的视频，发现**个别视频时长不到 40s**（纯视频脚本录像 40s 一轮），怀疑 FTP 没下完整。

Document Agent 核对源码、run.log 与已下载文件，定位到两处代码缺陷（见 §3），现整理为需求交 Code Agent 修复。

## 2. 现场证据（供 Code Agent 复现参考，无需重新推导）

- 本次运行日志：`logs/download/20260831/20260831_142443/run.log`。
- `ffprobe`（`tools/ffmpeg/ffprobe`）对已下载 h265 的实测：
  - 18 个 `20260101_*` 视频：约 87.7MB / 1152 帧 ≈ 46s（40s 录像 + 起停开销，**完整**）。
  - 1 个 `20260824_094316_2663/Video_2663_0.h265`：仅 6.6MB / 89 帧 ≈ 3.5s（**明显短**）。
- 该短文件是本次**第一个**下载的文件（run.log 14:25:12 → 14:25:16，仅耗时约 3.6s），
  后续每个文件耗时 40s+；且 run.log 全程**无任何「提前结束/续传/异常」告警**。
- `latest_n: 20` 实际只下载了 **19** 个视频目录（汇总行 `video: 下载 19 个文件`）。
- 19 个视频目录里 18 个目录名是 `20260101_*`（RTC 未校时、默认停在 2026-01-01），
  仅 1 个 `20260824_*` —— 印证「目录名字典序 = 时间序」假设在 RTC 未校时不可靠
  （原始需求 TODO-CONFIRM #1 已复现）。

## 3. 缺陷与修复要求

### 缺陷 ①：`download.py` 缺少逐文件下载成功日志

`ATS/modules/download.py` 下载循环（约第 99~108 行）：

```python
logger.info(f"下载 {remote_path} -> {local_path}")   # 仅下载前打印
if ftp.download(remote_path, local_path, timeout=timeout, retries=retries):
    ok += 1
    total_bytes += os.path.getsize(local_path)        # 成功分支：零打印
else:
    fail += 1
    logger.warn(f"下载失败: {remote_path}")            # 仅失败打印
```

**要求**：成功分支补打印，逐文件输出 `成功`，并带关键信息：
- remote size（若可得）/ local size（字节、KB）
- 是否走断点续传（本次 `ftp.download()` 返回值无法区分，建议由 `FtpClient.download()`
  返回更丰富结果，或模块内下载前后对比 `os.path.getsize(local_path)` 判断有无续传）。
- 失败分支同样带 remote size / local size，便于对比判断是否截断。

### 缺陷 ②：`ftp_client.py::download()` 完整性校验漏洞（核心）

`ATS/drivers/ftp_client.py::download()`：

```python
total = self.size(remote_path)                 # size() 解析不到时返回 -1（第 219 行）
for attempt in range(1, retries + 1):
    ...
    self._ftp.retrbinary(f"RETR {remote_path}", f.write, rest=offset if offset > 0 else None)
    local_sz = os.path.getsize(local_path)
    if total <= 0 or local_sz >= total:        # ← 漏洞：total<=0 时不做校验直接 return True
        return True
    ...
```

而 `size()`（第 209~221 行）在 LIST 解析不到目标文件名时返回 `-1`；且 `_parse_list_line`
对「仅名称」等无法解析大小的行返回 `size=0`。因此：

- `total <= 0`（远端大小未知/为 0）时，**第一次 retrbinary 结束即静默 `return True`**，
  中途断流/截断的残缺文件被当成「下载成功」，且不打印任何告警（与现场「run.log 无告警」吻合）。
- `download.py` 又无条件信任这个 bool 返回值，不独立比对本地/远端大小。

**要求**：`total <= 0` 时**不得静默 return True**。至少：
1. 下载结束后**重查一次 `size(remote_path)` 兜底**比对；仍拿不到时，
2. 明确降级：打印 `warn`（「远端大小未知，无法校验完整性，按可疑处理」），并按
   **失败/可疑**（而非成功）返回，避免残缺文件静默入库；
3. 或者由 Code Agent 提出更稳妥的等价方案，但必须保证「无法校验完整性」不会静默判成功。

> 说明：`total > 0` 的正常路径（比较 local_sz >= total、不足则续传）已正确，无需改动。

### 缺陷 ③：汇总缺「目录总数 / 实际取数」明细

`download.py::_download_source` 的 `detail` 字段虽有「共 X 个目录，取最新 Y 个」，
但未进 run.log；`latest_n=20` 只下 19 个的原因（video 下仅 19 个目录？还是某目录无 `*.h265`？）
从日志无法判断。

**要求**：汇总/明细日志补「来源目录总数、实际取目录数、逐文件成功/失败数与大小」，
让「19 而非 20」一眼可见，便于排查漏下。

## 4. 验收标准

1. 逐文件成功日志可见（`成功` + 两端大小），失败日志带两端大小。
2. 人为制造「远端大小未知」场景（或复现 `20260824_*` 短文件）时，脚本**不会**把残缺文件
   静默判成功：要么重查兜底成功，要么打印「无法校验完整性」并按失败/可疑处理。
3. 真机复跑 `--scenario download`，每个文件下载后本地大小与板端一致；
   重点核实 `20260824_094316_2663/Video_2663_0.h265` 是否本身即为一次短录像（板端文件仍在，
   可直接列板端 `/emmc/VIDEO/20260824_094316_2663/` 比大小）。
4. 汇总行能看到「目录总数 / 实际取数 / 成功 / 失败 / 总大小」。

## 5. 边界确认

- **不新增 ADR**：bug 修复 + 日志增强，属模块内部变更（Code Agent 分级 Level 1），
  只需 devlog 留痕，不动 `01_architecture/` / `02_design/` / `05_handoff/`。
- **不删板端文件**：维持现有「下载后板端保留」行为。
- **不改纯视频场景**：`stress_traverse_photo_mode.yaml` 保持原样。
- 按工程红线 1：改动后新建 `docs/03_development/devlog/<YYYYMMDD>_<HHMM>_<描述>.md`
  并更新其 README 索引。
- `size()` 返回 -1 的根因（板端 LIST 格式解析不到该文件名）若属可修，Code Agent 可一并
  提升 `size()`/`_parse_list_line` 的解析健壮性；若属固件输出格式限制，则只需保证
  「未知大小不静默成功」的兜底即可。
