# 需求文档：testvideo 分支仅录像（开始/停止），关闭 FTP 下载

> 提出方：Document Agent（按用户口述整理，交由 Code Agent 实施）
> 状态：待实施
> 分支：`testvideo`

## 1. 背景

`testvideo` 分支只做录像测试：每次只需 `dfs_video_start` → 等录像时长 → `dfs_video_stop`，
不需要录像结束后的 FTP 校验/下载。当前 `video.py` 的录像流程**硬编码**了 FTP：

1. 开头强制依赖 FTP（`if ftp is None: return self._skip(...)`）；
2. 录像前 `ensure_ftp` 前置重建连接；
3. 录像前 `_list_video_dirs` 记录旧目录；
4. 停止后 FTP 校验文件大小 + 下载到本地。

因此需要给 `video` 模块加「关闭 FTP」的参数开关，让纯录像场景完全不碰 FTP。

## 2. 需求

- **关闭录像结束后的 FTP 下载**：`dfs_video_stop` 成功后直接判 PASS，不再校验大小、不再下载。
- **完全不依赖 FTP**：录像前不 `ensure_ftp`、不列目录；`video` 模块不应再因「FTP 客户端不可用」而 SKIP。
- PASS 判据不变：`dfs_video_stop` 等到 `Video recording completed successfully.`。

## 3. 实现方式（模块红线：加参数接口，不硬删代码）

现有机制已有 `task.duration` / `task.override` 两级覆盖（见 `scenario.py` Task、`base.py` `_merge`），
因此建议**不改 Runner/Scenario 数据结构**，只在 `video.py` 增加一个布尔参数开关：

- 建议参数名：`video_ftp_download`（或 `video_enable_ftp`，二选一，以 Code Agent 最终命名并落注释为准）。
- `ATS/config/modules/video.yaml` 设默认 `true`（保持 `normal`/`stress` 等既有场景行为不变）。
- 纯录像场景在 scenario 层用 `override` 覆盖为 `false`。

`video.py` 需要改的行为（开关为 false 时）：

1. **开头**：不再 `if ftp is None: return self._skip(...)`——纯录像不需要 FTP 客户端；
2. 跳过 `ensure_ftp` 前置（L38-41）与 `_list_video_dirs` 旧目录记录（L54）；
3. `dfs_video_stop` 成功（`Video recording completed successfully.`）后**直接返回 PASS**，
   跳过大小校验 + 下载整段（L101-141）。

开关为 `true` 时行为与现状完全一致（正常路径不动）。

> 说明：`ensure_ftp` 逻辑与 `_list_video_dirs`/`_wait_new_dir` 方法保留不删（历史能力），仅按开关旁路。

## 4. 场景配置（沿用已改文件）

用户已手动把 `ATS/config/scenarios/stress_traverse_photo_mode.yaml` 改为只留 video task
（`loop.count=20`、`video.duration=40`、删除 photo/rtmp task）。**沿用该文件**，并在其上做如下调整：

```yaml
  prepare:
    - serial_init
    - wifi_connect
    - preclean
    # - ftp_ready          # 纯录像，移除（完全不依赖 FTP）
    - preview_start
  tasks:
    - module: video
      duration: 40
      override:
        video_ftp_download: false
```

- `prepare.ftp_ready` 应移除（场景不依赖 FTP）。
- `preview.enabled` / `preview_start`：纯录像无 RTMP 流可看，画面观察无意义；
  建议改 `preview.enabled: false`（或保留，nginx 未就绪会自动跳过，不报错）——Code Agent 按默认关掉更干净。
- `cleanup.stop_stream`（`rtmp_video_stop`）对纯录像无意义但无害，可保留。

> 已知取舍（用户已确认）：场景文件名/`name` 仍为 `stress_traverse_photo_mode`，
> 日志与报告会落在 `logs/stress_traverse_photo_mode/`。后续若需要独立命名再重命名为
> `testvideo.yaml`（届时 `scenario.name` 同步改，`--list-scenarios` 自动发现，无需注册）。

## 5. 验收标准

- 跑一轮 `python3 -m ATS.main --scenario stress_traverse_photo_mode --no-interactive-wifi`
  （可先小 `loop.count` 冒烟）。
- 日志里应看到：`dfs_video_start` → 等待录像时长 → `dfs_video_stop` →
  `Video recording completed successfully.` → PASS。
- 日志里**不应出现** FTP 相关动作：无 `ensure_ftp`、无 `FTP 开始下载视频`、无 `ftp_server` 启动
  （`prepare.ftp_ready` 已移除）。
- 不因「FTP 客户端不可用」出现 `SKIP`。

## 6. 边界确认

- 不改 `normal`/`stress` 场景：`video_ftp_download` 默认 `true`，它们行为不变。
- 按工程红线 1，改动后需在 `docs/03_development/devlog/` 新建记录并更新其 README 索引。
- 本需求只加一个参数开关 + 旁路 FTP 逻辑，不引入新模块、不改模块职责（仍属 video 模块能力）。
