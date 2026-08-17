# MediaMTX 换 nginx-rtmp + RTMP 验证改 ffprobe 实时探测

**日期**: 2026-08-14
**改动范围**: `drivers/rtmp_server.py`(重写) + `drivers/rtmp_receiver.py`(重写) + `modules/rtmp.py`(重写) + `config/test_config.yaml` + `main.py`(依赖检查) + `migrate.sh` + 删除 `tools/mediamtx/` + 6 篇文档
**触发**: 用户已在本地装好 nginx-rtmp 并手动验证通过，要求把 MediaMTX 整套换成 nginx-rtmp

---

## 一、问题描述

此前 RTMP 服务端用项目内置的 MediaMTX（`tools/mediamtx/`，54MB 单二进制），脚本用 subprocess 自动启停。这是当时机器网络受限、装不了 nginx-rtmp 的权宜之计。

现在用户已在本地安装 nginx-rtmp（`libnginx-mod-rtmp` 模块，`/etc/nginx/rtmp.conf` 配 `application live { live on; record off; }` 监听 1935）并**手动推流验证通过**。需要：
1. 删除内置 MediaMTX，RTMP 服务端改用系统 nginx-rtmp；
2. 适配 nginx-rtmp 的接入方式（它是系统服务，不适合脚本 subprocess 启停）；
3. 验证方式从「ffmpeg 拉流存盘 + ffprobe 解析文件」改为更轻量的「ffprobe 实时探测 + 可选 ffplay 画面」。

## 二、根因/设计

### 2.1 为什么 nginx-rtmp 用「仅检查就绪」而非 subprocess 启停

MediaMTX 是单二进制，脚本 `subprocess.Popen` 启停干净利落。但 nginx-rtmp 通常作为系统服务运行（systemd 管理 / 用户手动 `nginx` 命令）：
- 若脚本也去 `subprocess.Popen(["nginx", ...])`，会与已运行的 systemd 实例冲突（端口占用、pid 文件冲突）；
- 启停 nginx 常需 root（绑 1935、写 pid/log），脚本不该持有 sudo。

故采用「仅检查就绪」：脚本只确认 1935 端口在 LISTEN 即认为服务端就绪，未就绪报错提示用户手动 `systemctl start nginx`。这符合用户「手动测试通过」的工作流，也不与 systemd/sudo 冲突。

### 2.2 为什么验证改 ffprobe 实时探测（去掉存盘）

MediaMTX 时代用 ffmpeg 拉流存盘 `.flv` + ffprobe 解析文件，是因为要产出「可回放样本」。nginx-rtmp 方案下，需求简化为「确认流到达即可」：
- ffprobe 可直接探测实时 RTMP url（实测 `ffprobe ... -i rtmp://127.0.0.1/live/cam` 返回 h264 640x480，exit 0），无需落盘；
- 省掉存盘文件管理（work_dir、`_outfile`、文件大小校验、`-c copy` 等），逻辑更简；
- ffplay 作为**可选**画面确认（人眼复核），判据仍由 ffprobe 给（机器可读，满足无人值守返回退出码的需求）。

### 2.3 关键时序修正

ffprobe 探测实时流必须在 `rtmp_video_stop` **之前**——探测的是当前在线的流，stop 后流断开探测必失败。这与 MediaMTX 时代「先 stop 再 verify 存盘文件」相反，是本改动最易写错的点。

## 三、修复内容

### A. `drivers/rtmp_server.py` —— 重写为「仅检查就绪」

- 删 `_find_mediamtx`、`mediamtx_path`/`config_path`、`_proc`、`stop()`、`available`。
- 构造 `__init__(self, port=1935)`。
- `start()` → `check_ready(timeout=8.0)`：轮询 1935 是否 LISTEN（复用 `_is_port_listening`/`_wait_port_ready`，但不再持有 `_proc`），未就绪抛 `RtmpServerError` 提示手动启动 nginx。
- 保留 `RtmpServerError`。

### B. `drivers/rtmp_receiver.py` —— 重写为 ffprobe 实时探测

- 删 ffmpeg 存盘：`work_dir`/`_outfile`/`_verify_with_ffmpeg`/ffmpeg `-i -t -c copy -f flv` 命令/`verify()` 读存盘逻辑。
- `start(url)` → `probe(url, timeout=15, attempts=4, interval=2.0)`：subprocess.run ffprobe 实时探测。**关键参数**（实测确认）：`-v error -rw_timeout 3000000 -analyzeduration 2000000 -probesize 1000000 -i <url> -select_streams v:0 -show_entries stream=codec_name,width,height -of json`，外层 `subprocess.run(..., timeout=15)` 双保险。带重试（推流上线缓冲 4-6s）。
  - `-rw_timeout` 必加：实测不带此参数、无流时 ffprobe 会挂死 12s+ 被 timeout 杀（exit 124）；带后 ~2.3s 退出。
- 判据：有视频流 + codec + 分辨率 = ok（min_duration 判据消失，实时流无 duration）。
- `check_tools` 签名改为只收 `ffprobe_path`，**ffprobe 升为必需**（无存盘文件可降级）。
- 保留 `_find_ffprobe`；`stop()` 空实现保留兼容。

### C. `modules/rtmp.py` —— 适配新流程 + 管 ffplay

- setup：`RtmpServer(port=1935)`（去 mediamtx 参数）；新增 `self._ffplay_proc`/`_find_ffplay`。
- run 时序：①`check_ready` → ②压制 FTP → ③`rtmp_video_start`(exec_async) → ④`sleep 3` 等上线 → ⑤可选 ffplay（查 `DISPLAY`，无则跳过；`preexec_fn=os.setsid` 启进程组）→ ⑥ffprobe 探测(带重试) → ⑦`rtmp_video_stop` → ⑧判据。
- teardown：`os.killpg` 停 ffplay（进程组 kill 兜底，防 SDL 子进程残留）；server 不再 stop。

### D. `config/test_config.yaml`

- 删 `mediamtx_path`/`mediamtx_config`；新增 `ffplay_path: tools/ffmpeg/ffplay`；`stream_duration` 注释改语义；保持 `stream_url: rtmp://{pc_ip}/live/cam`。

### E. `main.py` `check_dependencies`

- `RtmpReceiver.check_tools` 新签名只收 `ffprobe_path`；ffprobe 升必需（缺失进 missing 阻断），不再「可选降级」。

### F. `migrate.sh`

- 第3步：循环只查 `tools/ffmpeg/{ffmpeg,ffprobe,ffplay}`；新增 nginx-rtmp 就绪检查（`command -v nginx` + `nginx -t 2>&1 | grep "syntax is ok"` + `ss -tln | grep :1935`），未就绪 warn 提示 `systemctl start nginx`。不用 systemctl status（sudo 依赖）。
- 第8步末尾 RTMP 手动调试提示：`./tools/mediamtx/...` → `systemctl start nginx`。

### G. 删除 `tools/mediamtx/` 整个目录

`mediamtx`(54MB) + `mediamtx.yml`(37KB) + `mediamtx_min.yml` + `LICENSE`，`git rm -r`。

### H. 文档同步

改：`ATS/README.md`、`使用手册.md`(场景5/Q7)、`迁移指南.md`、`00_阅读导航.md`、`20260814_第二次交接.md`(末尾加第九节更新说明)、`devBugLog/README.md` 索引。历史 devBugLog 与需求/设计文档不改（记录当时事实）。

## 四、验证结果

### 4.1 实测 ffprobe 实时探测 nginx-rtmp（本机闭环）

nginx-rtmp 已在跑（`ss -tln` 显示 1935 LISTEN）。后台用 ffmpeg 推 testsrc 测试流到 `rtmp://127.0.0.1/live/cam`，推流进行中执行 ffprobe：

```
$ ./tools/ffmpeg/ffprobe -v error -rw_timeout 3000000 -analyzeduration 2000000 -probesize 1000000 \
    -i rtmp://127.0.0.1/live/cam -select_streams v:0 -show_entries stream=codec_name,width,height -of json
{
    "streams": [
        { "codec_name": "h264", "width": 640, "height": 480 }
    ]
}
退出码: 0
```

✓ ffprobe 实时探测成功，返回 h264 640x480。`_parse_probe` 能正确解析此 JSON（streams[0] 含 codec_name/width/height）。
✓ 推流结束后再探测 → I/O error（exit 1），验证了「探测必须在 stop 之前」的时序要求。

### 4.2 静态检查

- 三个 .py `ast.parse` 语法 OK；drivers import OK（RtmpServer/RtmpReceiver 正常加载）。
- `bash -n migrate.sh` 语法 OK。
- `grep -rni mediamtx` 工程内：代码/配置/脚本已无残留（仅剩 3 处解释性注释提到「MediaMTX 时代」作历史对照，以及历史 devBugLog 记录——均为保留上下文，非残留逻辑）。

### 4.3 待真机验证（需接 EVB）

- `python3 -m ATS.main --dry-run`：配置+依赖通过（ffprobe 必需检查）。
- `python3 -m ATS.main --no-interactive-wifi`：含 rtmp，rtmp 项 PASS（ffprobe 探到 h264 + 分辨率），ffplay 起/停正常无残留。
- `./migrate.sh`：第3步报 nginx-rtmp 就绪。

## 五、还会再有吗（残留风险）

1. **nginx-rtmp 不提供 RTSP**：MediaMTX 有 8554 RTSP，原场景5 的 `ffplay -rtsp_transport tcp rtsp://...:8554/...` 选项失效，已改文档为只能走 RTMP。
2. **ffplay 直连抗乱序帧未知**：MediaMTX 曾因 `too many reordered frames` 断 ffplay；nginx-rtmp 是否复现待真机验证。已降级为「ffplay 仅可选，判据靠 ffprobe」，即使 ffplay 被断也不影响 PASS。
3. **ffplay 无 DISPLAY 卡死**：实测无 DISPLAY 时 ffplay 卡在 `nan: 0.000` 不退出。已加 `os.environ.get("DISPLAY")` 检查，无则跳过 + killpg 兜底。
4. **`stream_duration` 语义变化**：不再用于 ffmpeg `-t`，改为「推流持续窗口」（探测期间推流须在线，stop 前完成探测）。
5. **pc_ip 自动探测选错网卡的 P0 问题不变**：本次不解决，仍是遗留（见阅读导航第四节）。多网卡机器仍需写死 `rtmp.pc_ip`。
6. **ffmpeg 不再用于拉流**：`ffmpeg_path` 保留在配置里仅作套件就绪代理，实际 RTMP 验证只用 ffprobe/ffplay。

## 六、经验沉淀

1. **服务端由系统管理时，脚本只检查不启停**：nginx-rtmp 是系统服务，脚本 subprocess 启停会与 systemd 冲突且需 sudo。「仅检查端口就绪」是更干净的边界，符合用户手动验证的工作流。对比 MediaMTX（单二进制无系统服务）才适合 subprocess 启停——选型决定接入方式。见 [[rtmp-ffmpeg-bundled]] 同类离线依赖引入。
2. **实时探测 vs 存盘验证**：需求只需「确认流到达」时，ffprobe 直探实时 url 比拉流存盘+解析文件省一个数量级复杂度（无 work_dir/文件管理/大小校验）。存盘只在需「可回放样本」时才值得。
3. **时序反向是实时探测的陷阱**：存盘验证是「stop 后解析留下的文件」，实时探测是「stop 前探测在线的流」——两者时序相反。从存盘迁到实时探测时，必须把 verify 调用挪到 stop 之前，否则必败。这种「同一接口名、相反时序」的迁移最易写错。
4. **ffprobe 挂死用 -rw_timeout 兜底**：ffprobe 连无流源不带 `-rw_timeout` 会挂死 12s+ 才被外层 timeout 杀；带 `-rw_timeout 3000000`（微秒）后 ~2.3s 自行退出。实时探测 RTMP 必加此参数，外层 subprocess timeout 作双保险。
5. **GUI 工具做可选确认、CLI 工具做判据**：ffplay 是 GUI 无机器可读 PASS/FAIL，不适合做无人值守判据；ffprobe 输出 JSON 可解析、退出码可判，才是判据。ffplay 仅作人眼复核，且必须处理无 DISPLAY 环境（跳过）+ 进程组 kill（防 SDL 子进程残留）。
