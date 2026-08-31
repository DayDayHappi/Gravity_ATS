# 需求文档：新增 download 场景（仅从板端 FTP 下载文件，不做测试）

> 提出方：Document Agent（按用户口述整理，交由 Code Agent 实施）
> 状态：待实施

## 1. 背景

纯视频脚本（`testvideo` 分支，`stress_traverse_photo_mode` 场景）用 `video_ftp_download=false`
只录不下载，拍摄阶段**不启动 WiFi、不启动 ftp_server**（prepare 里 `wifi_connect`/`ftp_ready`
已移除）。拍摄完成后，需要**另一个独立的「只下载、不做测试」场景**，把刚拍的文件从板端
FTP 下载到电脑。

目标：纯视频脚本正常走完 → 用户手动启动下载场景 → 下载完成后单独结束。

## 2. 需求

新增场景 `download`，**只做 FTP 下载，不做任何业务测试**：

1. 场景 `ATS/config/scenarios/download.yaml`，CLI 用 `--scenario download`。
2. prepare 复用现成动作补齐下载所需环境：`serial_init` → `wifi_connect` → `ftp_ready`
   （这三步纯视频场景省掉了，下载前必须重建）。
3. tasks 只放一个新模块 `download`，完成「列板端目录 → 下载文件到本地」。
4. **下载目标可配置**：不限于视频，可扩展照片或其他文件，也可混合（照片+视频一起下）。
5. **数量按「最新 N 个」**：N 可配置（默认 20，对应纯视频 20 轮）。
6. **不删除板端文件**（下载后板端保持原样）。
7. 本地保存到 `downloads/<日期>/`（日期 `%Y%m%d`，与日志按天分层同风格）。

## 3. 实现方式

### 3.1 新增模块 `download`（`ATS/modules/download.py`）

模块红线：一个「从板端 FTP 下载文件」动作 + 参数接口，不写业务循环（循环由配置驱动）。

参数接口（`config/modules/download.yaml` + scenario override）：

```yaml
# 下载模块参数
sources:                 # 下载来源列表，可含多组（视频/照片/其他），按需配置
  - label: video         # 来源标签，用于本地子目录与日志区分
    dir: /emmc/VIDEO     # 板端远程根目录（其下是时间戳子目录）
    pattern: "*.h265"    # 文件匹配模式
  - label: photo
    dir: /emmc/PIC
    pattern: "*.jpg"
latest_n: 20             # 每个来源取最新的 N 个时间戳子目录
download_dest: downloads # 本地下载根目录（其下按 downloads/<日期>/<label>/<子目录>/<file>）
download_timeout: 30     # 单文件下载 socket 超时（秒）
download_retries: 5      # 单文件断点续传重试次数
```

**下载逻辑**（每个 source 一次）：

1. 用 `FtpClient._list_entries(source.dir)` 列该根目录下所有子目录（时间戳目录）。
2. 按目录名降序排序（时间戳目录名形如 `20260828_160219`，字典序=时间序），取前 `latest_n` 个。
3. 对每个子目录，列匹配 `pattern` 的文件，逐个 `FtpClient.download()` 下载到
   `downloads/<日期>/<label>/<子目录>/<文件名>`。
4. 每个文件复用现有 `download()` 的断点续传/重试/主动模式（不新造轮子）。
5. 返回 TestResult：按 source 汇总（成功数/失败数/总大小），单个文件失败不中断整体。

**复用点**（均已真机验证，不重写）：

- `FtpClient.list_files_detail()` / `_list_entries()`：列目录。
- `FtpClient.download(remote, local, timeout, retries)`：断点续传下载。
- `ftp_ready` prepare 动作（`scenario_manager.py`）：幂等启动 `ftp_server` + 建连接。
- `wifi_connect`：先检测已联网（掉电记忆）再决定 join。

### 3.2 注册模块

在 `ATS/modules/__init__.py` 追加一行 `from . import download  # noqa: F401`。

### 3.3 场景 `download.yaml`

```yaml
# 仅下载场景：从板端 FTP 下载文件到本地，不做任何业务测试
scenario:
  name: download
  preview:
    enabled: false
  prepare:
    - serial_init
    - wifi_connect
    - ftp_ready
  loop:
    enable: false
  tasks:
    - module: download
      override:
        latest_n: 20
  cleanup:
    - close_serial
```

- `loop.enable: false`：只跑一轮，不循环。
- `preview.enabled: false`：无 RTMP，不启 ffplay。
- cleanup 只 `close_serial`（ftp_client 由 `ctx.cleanup()` 统一关闭，无需额外动作）。

### 3.4 本地保存路径

`downloads/<日期>/<label>/<时间戳子目录>/<文件名>`。

- 日期目录不存在时自动创建（`os.makedirs(exist_ok=True)`）。
- `downloads/` 应加入 `.gitignore`（与 `logs/` 同为本地产物，不入库）。

## 4. 验收标准

1. `--list-scenarios` 能看到 `download`。
2. 纯视频脚本走完后，跑 `python3 -m ATS.main --scenario download --no-interactive-wifi`：
   - 自动串口探测 → WiFi 连接 → `ftp_server` 启动 → 列 `/emmc/VIDEO` 最新 20 个时间戳目录。
   - 每个 `Video_*.h265` 下载到 `downloads/<今天日期>/video/<时间戳目录>/`，大小与板端一致。
   - 报告里 `download` 模块 PASS，message 汇总「下载 N 个文件 / 总大小 X KB / 失败 M 个」。
3. 板端文件**仍在**（未被删除）。
4. 修改 `sources` 配置后，能下载照片（`/emmc/PIC/*.jpg`）或照片+视频混合，无需改代码。

## 5. 边界确认

- **不删除板端文件**：本次需求明确不删，代码不得做删除动作（`DELE` 不用）。
- **不改纯视频场景**：`stress_traverse_photo_mode.yaml` 保持原样（只录不下载）。
- **不新增 ADR**：这是新增一个模块 + 场景，复用现有架构（config 三层 + 模块注册 + prepare 动作），
  不涉及模块职责/数据流/生命周期变更，属 Implementation。
- 按工程红线 1，改动后需在 `docs/03_development/devlog/` 新建记录并更新其 README 索引。
- TODO-CONFIRM（Code Agent 实施时确认）：
  1. 时间戳目录按「目录名字典序」排序是否等价于时间序——实测目录名为 `YYYYMMDD_HHMMSS[_序号]`，
     字典序即时间序；若有反例（如序号不补零）再改用目录内文件的 mtime 或目录名解析排序。
  2. `ftp_ready` 启动 `ftp_server` 后，若板子 FTP 服务此前已被纯视频脚本之外的流程启动过，
     `start_ftp` 的 `ctx.ftp_server_started` 幂等标志是否跨进程失效（跨进程必然失效，
     每次启动脚本都会重发 `ftp_server`）——需确认重发不会触发固件「service go wrong」崩溃循环
     （现有 `ftp_ready` 语义为「本次进程内只发一次」，跨进程重发是预期行为，真机确认无崩溃）。
