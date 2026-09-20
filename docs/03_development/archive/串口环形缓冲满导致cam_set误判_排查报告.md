# 串口环形缓冲满导致 cam_set 误判 排查报告

**日期**: 2026-09-20
**分析对象**: `logs/stress/20260918/20260918_163736/`（run.log + serial.log，14h 长时压测）
**结论性质**: 脚本侧缺陷（Code Agent 修复），非固件 bug
**修复方案**: 已拍板 —— 方案 A（游标/序号定位，根治）

---

## 一、现象

stress 压测（loop 200）跑到约第 26 轮（06:48，RTMP 推流 10 分钟结束后回到 photo）起：

- photo 全部 `[FAIL] 设置模式 失败`
- video 全部 `[FAIL] 设置录像组合 失败`
- 此后每轮（07:02、08:22 … 10:47）持续 FAIL，不可自愈。

用户观察到的直接表象：`serial.log` 里 `dfs_capture_start` 最后一次出现在 06:09:52，
之后每次只发 `cam_set photo []` 不再发 capture —— 因为 photo 第一步 `cam_set` 判 FAIL
就提前 return，根本走不到第二步 capture。

## 二、时间线证据

| 时刻 | run.log | serial.log（固件回显） |
|------|---------|----------------------|
| 06:07（cycle 25） | photo 全 PASS | `I/App Dfs: auto mode` 等，哨兵 1.6s 内完整出现 |
| 06:48（cycle 26，RTMP 10min 结束回到 photo） | photo+video 全 FAIL | 06:48:39 `cam_set photo auto` 后固件打印 `I/App Dfs: auto mode`（**成功语义**）；06:49:15 `cam_set video sd1080p 0` 后打印 `product_w(1920)*product_h(1080) is 1080p`；哨兵 `__EVBTEST_END_xxx__` 均在 ~1.6s 内完整出现（**非超时**） |
| 07:02、08:22 … 10:47 | 持续全 FAIL | 同上，固件回显始终成功 |

关键矛盾：**固件回显成功 + 哨兵及时出现，但脚本判 FAIL**。

## 三、根因分析（两层叠加，缺一不可）

### 第 1 层：快照定位机制在环形缓冲滚满后失效

`ATS/core/serial_console.py` 的 `exec_sync` 用**字符串前缀匹配**定位「命令发出后的新输出」：

```python
# exec_sync：发命令前
snapshot = self._buffer_text()      # 整个 deque 拼成的字符串

# _wait_pattern：等哨兵时
full = self._buffer_text()
new = full[len(start_snapshot):] if full.startswith(start_snapshot) else full
```

缓冲是 `deque(maxlen=65536)`。长时间压测后缓冲滚满，命令执行期间（snapshot → 哨兵）
任何新数据都会顶掉头部，`full` 开头不再等于 `snapshot` 开头 → `full.startswith(snapshot)`
恒为 False → `new = full`（**把整个历史缓冲当成这一次命令的响应**）。

### 第 2 层：`_ERROR_RE` 把相机正常日志当成失败关键字

`exec_sync` 无 expect 时，`_judge` 用：

```python
_ERROR_RE = re.compile(
    r"\b(error|failed|fail|cannot|no such|not found|invalid|exception)\b",
    re.IGNORECASE,
)
```

RTMP 阶段固件持续刷相机正常调试日志 `preset capCfg 200 0 0 invalid, use default`
（全 log 共 **780 条**，是相机调试 `[fallback]` 信息，非真错误）。第 1 层把整个历史
缓冲喂给 `_judge`，命中 `invalid` → 误判 `success=False`。

### 完整因果链

```
deque 收满 → startswith 快照定位失效 → new 混入历史残留
                                        ↓
                      _ERROR_RE 含 "invalid"（相机正常日志）→ 误判 FAIL
```

> 两层缺一不可：光缓冲满、判据不碰 `invalid` 不会误判；光 `invalid` 宽松、定位正常也扫不到历史。

### 为什么 cycle 26 才触发

photo 永远紧跟 RTMP 结束执行，RTMP 10 分钟持续把 `invalid` 刷进缓冲，使误判一旦
开始就自我维持（下一轮 photo 又踩同一缓冲残留）。

## 四、影响范围

| 位置 | 命令 | 影响 |
|------|------|------|
| `ATS/modules/photo.py` L77 | `exec_sync(PHOTO_SET_COMMAND, timeout=...)` | cam_set photo 误判 FAIL → 提前 return，不发 capture |
| `ATS/modules/video.py` L102 / L185 | `exec_sync(profile.command, timeout=...)` | cam_set video 误判 FAIL → 录像流程中断 |

底层缺陷在 `ATS/core/serial_console.py`：
- `exec_sync` → `_wait_pattern`（快照定位）
- `exec_async` → `_wait_regex`（同样的 `full[start_snapshot:]` 定位，异步命令同样会中招）

## 五、修复方案（已拍板：方案 A）

方案 A：**快照定位从「字符串前缀」改为「单调递增序号游标」**。

### 设计要点

1. 读线程 `_reader_loop` 每次 `append` 缓冲时，同时打上全局自增序号：
   `self._buffer_seq += 1`，append `(seq, text)`；`deque` 从 `deque(str)` 改为
   `deque(tuple[int, str])`。

2. 发命令前不记「文本快照」，改记「序号游标」：`start_seq = self._buffer_seq`。

3. `_wait_pattern` / `_wait_regex` 改为：遍历 deque 中 `seq > start_seq` 的 chunk，
   join 成 new 文本。deque 淘汰旧 chunk（FIFO）时，被淘汰的必然是 `seq <= start_seq`
   的旧 chunk，不影响增量定位。

4. `_buffer_text()` 仍保留「返回全部」语义，供 `wait_for_ready` 等「检查整个缓冲」
   的场景使用（不需要增量定位）。

### 边界说明（Code Agent 需注意）

- deque `maxlen=65536`，若某次命令执行期间（snapshot → 哨兵）产生的 chunk 数超过
  65536（约 16MB 串口数据），`seq > start_seq` 的新 chunk 也会被 FIFO 淘汰，造成丢失。
  实测单命令 1.6s 内数据量远达不到，可不处理；若要彻底，可把 `maxlen` 改为按字节预算
  或 `deque(maxlen=None)` + 定时清理（本次不建议扩大改动面）。

### 备选（本次不采用，留档）

- 方案 B：`cam_set` 类命令改传显式成功 expect（photo 的 `auto mode` / `single shot mode`
  / `mfnr mode`、video 的 `product_w(...) is ...`），不再裸用 `_ERROR_RE` 反判。治标，
  仍有假阳性风险。
- 方案 C：`_ERROR_RE` 排除 `invalid` / `fallback` 等相机正常日志。治标，单独用不彻底。

## 六、验证方法（修复后）

1. **单元/离线**：构造「缓冲滚满后快照失效」场景，验证 `_wait_pattern` 能正确取到
   命令后增量（不依赖字符串前缀）。
2. **真机 stress**：跑 `python3 -m ATS.main --scenario stress --no-interactive-wifi`
   至 26 轮以上（越过 RTMP 10min），确认 photo/video 不再出现「设置模式/设置录像组合
   失败」，且 `serial.log` 中 capture/录像流程完整。

## 七、关联文档

- 待办：`docs/05_handoff/next_step.md`（🔴 P0）
- 已知问题：`docs/05_handoff/known_issue.md`（脚本侧已知问题表）
- 架构层数据流：`docs/01_architecture/data_flow.md`（常驻读线程喂环形缓冲描述，方案 A
  改动缓冲结构后需同步）
- 修复后留痕：`docs/03_development/bugfix/BUG-005-*.md` + `docs/03_development/devlog/`
