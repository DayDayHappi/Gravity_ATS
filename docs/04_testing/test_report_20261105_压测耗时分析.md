# 测试报告：stress 压测耗时分析（2026-11-05 run）

**日期**：2026-11-06
**分析对象**：`logs/stress/20261105/20261105_133805`（2026-11-05 13:38 → 11-06 09:19，58 cycle）
**数据来源**：`run.log`（模块耗时/阶段日志）+ `serial.log`（命令往返）+ 本地下载产物
**结论性质**：脚本侧可优化点分析（**非 bug**，不影响判据正确性）

---

## 一、总览：19.7 小时花在哪

| 模块 | 总耗时 | 占比 | 次数 | 单次均值 |
|------|--------|------|------|----------|
| rtmp | 32310s | **45.6%** | 57 | 567s |
| video | 25831s | **36.5%** | 690 | 37.4s |
| photo | 11623s | 16.4% | 696 | 16.7s |
| video_integrity | 1067s | 1.5% | 57 | 18.7s |
| **合计** | **70831s（19.7h）** | 100% | — | — |

rtmp 单次 567s 中约 600s 是配置的推流保持时长（`stress.yaml` `rtmp.duration: 600`），属业务必要，不视为浪费。

---

## 二、photo 耗时拆解（单次均值 16.7s）

| 阶段 | 实测 | 说明 |
|------|------|------|
| 模式切换 → 首次 FTP 连接 | avg 7.98s / median 5.93s | 含 `photo_settle_delay: 1.0` + `cam_set` 往返（实测 0.99s）+ `dfs_capture_start` 到 `Capture completed successfully.`（实测 avg 3.56s） |
| 下载段（首连 → PASS） | avg 9.4s | 636 次合计约 100 分钟 |
| 单文件循环（connect → 下次 connect） | **median 1.83s / mean 2.30s** | n=3922 |

单文件循环 1.83s 的构成估算：

| 分项 | 估算 | 依据 |
|------|------|------|
| 纯文件传输 | ~0.55s | 单文件中位 1.49MB ÷ video 实测吞吐 2.73MB/s |
| connect 建连 | ~0.12s | video `开始下载 → FTP 已连接` avg 0.12s |
| **`size()` 的 LIST 往返** | **~1.1s** | 余量；与目录 LIST 实测中位 0.84s 同量级 |

---

## 三、可优化项（按收益排序）

### 🔴 O1 — 每个文件下载都重复 LIST 整个目录

**位置**：`ATS/drivers/ftp_client.py`
- L255 `total = self.size(remote_path)`
- L209-221 `size()`：注释明写「该FTP不支持SIZE命令，用LIST父目录解析」，即每取一个文件大小就 CWD + LIST 一次父目录

**实测证据**：photo 每目录连接数严格等于「文件数 + 2」

| (文件数, connect 数) | 出现次数 |
|---|---|
| (1, 3) | 212 |
| (2, 4) | 106 |
| (7, 9) | 53 |
| (9, 11) | 159 |
| (10, 12) | 106 |

**收益**：`_list_jpgs()` 已经 LIST 过该目录一次，结果中已含 size。把该 LIST 结果传给 download，每文件可省一次 LIST。
3922 次 × 0.84s ≈ **55 分钟**（保守，按目录 LIST 中位）；若按 mean 2.43s 上限约 2.6h（长尾受目录累积影响）。

**现成条件**：`FtpClient.list_files_detail()` 已存在且**当前无任何调用方**，正是此用途。

**风险**：低（Level 1，模块内部 + driver 用法调整）。

---

### 🔴 O2 — 缩略图单独走完整下载循环（需产品侧拍板）

**实测**：缩略图总量 **5MB，占 photo 产物 0.1%**，但每张仍需一次 connect + LIST + RETR ≈1.8s。
636 张 × 1.8s ≈ **19 分钟**。

**建议**：缩略图只下载留证、不纳入校验集合；或干脆不下。
**阻塞**：`*_thum.jpg` 是否属交付产物未确认（BUG-008 TODO-CONFIRM）。属**判据决策**，需人工拍板后才可实施。

---

### 🟡 O3 — photo 每次多一次无用 `ensure_ftp`

**位置**：`ATS/modules/photo.py`
- L96 `ftp = ensure_ftp(ctx, console)`（run 内预连）
- L110 `_test_one(..., ftp, ...)` 接收后**函数体从未使用**（只用内部 L154 的 `ftp2`）

**收益**：696 × 0.11s ≈ 79s（小）。
**主要价值**：消除误导性死参数；若预连承担「提前暴露 FTP 不可用」语义，应改为显式检查或删除。

---

### 🟡 O4 — rtmp 固定 `time.sleep(3.0)` 与 ffprobe 重试重复

**位置**：`ATS/modules/rtmp.py` L132：推流命令下发后固定睡 3s，再调 `_receiver.probe(attempts=5, interval=3.0)`。
**收益**：57 × 3s ≈ 2.9 分钟（小）。逻辑上首探可立即发，失败再按 interval 重试。

---

### 🟢 O5 — 死代码 / 死配置（不影响耗时，影响可维护性）

| 位置 | 问题 |
|------|------|
| `photo.py` L110 `ftp` 形参 | 从未使用（见 O3） |
| `photo.py` L82 `cap_timeout` | 传入后从未使用 |
| `photo.py` L206 `_list_pic_dirs()` / L231 `_wait_new_dir()` | 无调用点（死方法） |
| `photo.py` L11 docstring | 仍写「轮询 FTP 等新目录（超时 photo_capture_timeout）」，与实际 `exec_async` 等 `Capture completed` 不符 |
| `photo.yaml` `photo_capture_timeout: 10` | 代码不读取，改之无效 |
| `modules/ftp.py` L69 双日志 | 每次 connect 打两行（`FTP 已连接` + `FTP 已重新连接`），本 run 6569 行中约半数为冗余 |

---

## 四、不建议优化（看似浪费但必要）

| 项 | 原因 |
|----|------|
| 每文件 `connect()` | BUG-003 已确认板端 FTP **3s 空闲断会话**，复用连接必失败 |
| video 下载 14.1s / 38.3MB | 吞吐 2.73MB/s，为板端 FTP 实际上限 |
| rtmp 600s 保持 | 业务配置，压测目的本身 |
| photo 等 `Capture completed successfully.` | 实测 3.56s，是相机真实出图时间 |
| video 比配置多 2.36s | 实测「拍摄开始→结束」22.36s vs `duration: 20`；差额为固件编码收尾等待（`dfs_video_stop` → `Video recording completed successfully.`），**不可压缩**。但**时间预算应按 22.4s/轮估算，不是 20s** |

---

## 五、优先级建议

| 优先级 | 项 | 预计收益 | 风险 | 备注 |
|--------|----|----------|------|------|
| P1 | O1 复用 LIST 结果消除每文件 LIST | 实测 **~1.2h**（photo 60 分钟 + video 9 分钟） | 低 | **已实施，见 §八** |
| P2 | O2 缩略图不下载/不校验 | ~19 分钟 | 中 | **需产品侧拍板** |
| P3 | O5 清理 photo 死参数/死方法/文档 | 0 | 极低 | 可维护性 |
| P4 | O4 rtmp 3s 等待与探测重试合并 | ~3 分钟 | 低 | 收益小 |

**建议顺序**：O5（清零成本）→ ~~O1（最大收益）~~ **已完成** → O4 → O2（待拍板）。

---

## 八、O1 实施结果（2026-11-06，devlog `20261106_1129`）

Code Agent 按 `size_hint` 方案实施，Document Agent 复核**通过**。

### 代码
- `ftp_client.download()` 新增 `size_hint: int = None`；合法 hint 时不调 `size()`，
  `None/0/负数` 回退原行为（向后兼容）。
- 追加保底复核：传输结束但 `local_sz < total` 且本次用了 hint → 先 `size()` 复核真实大小再判续传。
- `photo._list_jpgs()` 改返回 `[(name, size), ...]`（底层 `list_files_detail()`，此前无人调用）。
- `video` 复用已取到的 `sz` 传入 `size_hint`。

### 验证（Document Agent 独立复算，不采信 devlog 数字）

| 指标 | 改前 | 改后 | 结论 |
|---|---|---|---|
| `_list_entries()` 真实 LIST（10 图目录） | 11 | **1** | ✓ 与设计一致 |
| `size()` 调用（10 图目录） | 10 | **0** | ✓ |
| 单文件下载间隔 中位 | 1.83s（n=3922） | **0.74s**（n=22） | ✓ −60% |
| `photo[auto]` 10 图块耗时 中位 | 26.37s（n=53） | **12.94s**（n=2） | ✓ −51% |
| 单测 | 71 | **80** | ✓ 全绿 |
| `--dry-run` | — | exit 0 | ✓ |

独立复验 `size_hint` 语义：`hint=5000` → `size()` 调用 0 次、下载成功；`hint=None` → 调用 1 次；
真截断（声称 5000 / 实传 3000 / 真实 size 也 5000）→ **仍判 False**，判据未被削弱。

### 对本报告 §三 O1 收益估算的修正

原估「55 分钟 ~ 2.6h」偏乐观，**实测修正为 ~1.2h**：

- photo：3286 个文件 × 1.09s ≈ **60 分钟**
- video：630 次 × 0.84s ≈ **9 分钟**
- 合计约占 19.7h 的 **6%**（原估 5~13%）

原因：原估算用「目录 LIST 均值 2.43s」外推，实测单文件页内 LIST 更接近中位 0.84s；
且 `_list_jpgs` 本身的 1 次 LIST 无法消除。

### 任务单验收指标的更正（重要）

任务单原写「connect 次数 3/11/12 → 恒为 2」**是错的**。`download()` 每次必须 `connect()`
（板端 FTP 3s 空闲断会话，BUG-003 红线），N 个文件必然 N 次 connect，与本次优化无关。
改后实测 10 图目录仍为 12 次 connect。**正确指标是 `_list_entries()` 真实 LIST 次数 11→1**。
任务单已同步更正。

---

## 六、数据口径与不确定性

1. **模块耗时**取自 `run.log` 的 `<<< 模块 [...] 结束，耗时 X s`，含采集开销，与模块自报 `(Nms)` 略有出入。
2. **单文件循环耗时**以相邻两次 `FTP 已连接` 日志间隔近似，包含 connect + size(LIST) + RETR 全过程，无法在线分离三者；传输时间按 video 实测吞吐（2.73MB/s）折算，若 FTP 大文件吞吐优于小文件，则 LIST 占比会更高（即便结论方向不变）。
3. **LIST 耗时**取自 `FTP 已重新连接` → 下一次 `FTP 已连接` 的间隔（即 `_list_jpgs` 那次 LIST），n=1902，median 0.84s / mean 2.43s / P90 6.39s。用于估算每文件 LIST 收益属**同量级外推**，非直接测量。
4. **收益估算为量级参考**，实际受目录累积（`/emmc/PIC` 目录数增长导致 LIST 变慢）与网络状况影响。
5. 本报告**不含** eMMC 写满导致的失败样本（cycle 53 之后 photo/video/rtmp 连锁 FAIL），那部分耗时无参考价值。
   eMMC 容量属**范围外**（用户 2026-11-06 决策，脚本不处理），详见 `05_handoff/known_issue.md`。

---

## 七、关联

- 运行日志：`logs/stress/20261105/20261105_133805/`
- FTP 连接策略来源：`../03_development/bugfix/BUG-003-FTP复用连接下载失败.md`
- 缩略图判据来源：`../03_development/bugfix/BUG-008-photo缩略图套用主图大小阈值致误判FAIL.md`
- 待办：`../05_handoff/next_step.md`（P2 性能优化）
