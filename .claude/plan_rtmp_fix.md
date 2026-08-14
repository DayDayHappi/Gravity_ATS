# RTMP 推流真机验证修复计划

## 背景与诊断

首次 RTMP 真机测试失败:`[FAIL] rtmp (0ms) - 推流启动命令失败`,8 项 7 过 1 失。

### 根因(已从 serial.log 确认)

```
04:14:19  [W/ftp] service go wrong ...    ← FTP 崩溃循环开始(photo/video 阶段)
...       (持续刷屏 2 分多钟,每 1.5s 一次)
04:16:31  TX> rtmp_video_start rtmp://10.1.64.35/live/cam1
04:16:31  TX> echo "__EVBTEST_END_6564b7c6__"   ← exec_sync 哨兵
04:16:33  RX< p] service go wrong ...           ← FTP 崩溃日志淹没响应
04:16:33  RX< rtmp_vid                          ← 命令回显被截断只剩片段
```

两个问题叠加:
1. **FTP 崩溃循环刷屏**(`service go wrong` 每 1.5s 一次,从 04:14:19 持续到 rtmp 测试):这是交接文档 5.1 的已知固件 bug 的极端形态,`ensure_ftp` 在 photo/video 后没能压住。
2. **rtmp 用 `exec_sync`(哨兵定界)**:哨兵 `__EVBTEST_END_...` 被 FTP 洪水打乱,永等不到干净出现,超时判失败。而 photo/video 同类"海量日志"场景已改用 `exec_async` 不依赖哨兵--rtmp 漏改了。

设计文档第 282 行原本就预期 rtmp_video_start "确认无错误 + 侧信道(ffprobe)验证",本就不该死磕命令自身成功标志。交接文档建议第 5 条也明示:"参考 photo/video 的 exec_async + 正向 expect 模式调整"。

### 用户已确认策略
ffprobe 侧信道为主:`rtmp_video_start` 用 exec_async 发命令不强求串口成功标志,真正判据是 PC 端 ffprobe 验证到流到达。

## 修复方案

### 改动 1:`ATS/modules/rtmp.py` run() 逻辑重构

对照 photo.py:75 的 exec_async 模式,把 rtmp 的命令下发从 exec_sync 改 exec_async,并以 ffprobe 为主判据。

**当前 run() 关键逻辑**:
```python
r = console.exec_sync(f"rtmp_video_start {url}", timeout=10.0)
if not r.success:
    return self._fail("推流启动命令失败", detail=r.clean)   # ← 失败点
time.sleep(duration + 2)
console.exec_sync("rtmp_video_stop", timeout=10.0)
info = self._receiver.verify(min_duration=max(1.0, duration * 0.5))
if info.get("ok"):
    res = self._pass(...)
else:
    res = self._fail(...)
```

**改为**:
```python
# 1. 推流命令用 exec_async:发命令后直接等推流相关输出,不依赖被 FTP 刷屏打乱的哨兵。
#    expect 用宽松正则(命令回显片段即可),result_timeout 短;不强求 matched,
#    因真正判据是 PC 端 ffprobe 验到流(侧信道,符合设计文档原意)。
console.exec_async(
    f"rtmp_video_start {url}",
    expect=r"rtmp_video_start|RTMP|push|start",
    result_timeout=8.0,
)
# 2. 等推流时长 + 余量(让 ffmpeg 拉到足够数据)
time.sleep(duration + 2)
# 3. 停止推流(同样 exec_async 容忍刷屏)
console.exec_async("rtmp_video_stop",
                   expect=r"rtmp_video_stop|stop|RTMP",
                   result_timeout=8.0)
# 4. ffprobe 侧信道验证(★ 主判据)
info = self._receiver.verify(min_duration=max(1.0, duration * 0.5))
if info.get("ok"):
    res = self._pass(f"推流验证通过: {info['reason']}")
else:
    res = self._fail(f"推流验证失败: {info.get('reason', '未知')}",
                     detail=str(info))
```

要点:
- `exec_async` 失败不再立即 FAIL(去掉 `if not r.success: return self._fail`),继续走 ffprobe 验证。串口命令发不出去的极端情况(如设备掉线)由后续 ffprobe "流未到达" 判 FAIL 兜底。
- expect 正则宽松(`rtmp_video_start|RTMP|push|start`),只用于 exec_async 尽快返回,不作为成败判据。**真实成功标志需上板实测确认后微调**(见改动 3)。

### 改动 2:`ATS/modules/rtmp.py` run() 前置压制 FTP 崩溃

rtmp 依赖 wifi_join 不依赖 ftp,但 FTP 崩溃刷屏会干扰所有串口命令。run() 开头加一段压制(复用 ftp.ensure_ftp 的恢复手段),给 rtmp 干净串口环境:

```python
def run(self, ctx, console):
    pc_ip = getattr(ctx, "pc_ip", "")
    if not pc_ip:
        return self._fail("无法确定 PC IP,RTMP 推流目标未知")

    # 前置:压制可能正在刷屏的 FTP 崩溃循环,给 rtmp 干净串口环境。
    # rtmp 不依赖 FTP,但 FTP 崩溃日志会打乱后续命令定界。
    try:
        from .ftp import ensure_ftp
        ensure_ftp(ctx, console, force=True)
    except Exception as e:
        logger.warn(f"RTMP 前 FTP 压制异常(可忽略): {e}")
    time.sleep(1.0)  # 等残留刷屏沉淀

    timer = Timer().start()
    url = ...
```

> 注:`ensure_ftp(force=True)` 会重发 `ftp_server` 触发固件恢复。若 FTP 已彻底死循环压不住,改动 1 的 exec_async + ffprobe 侧信道仍能扛住(exec_async 不依赖哨兵),这是双保险。

### 改动 3:上板实测探 `rtmp_video_start` 真实成功标志

历史从未成功执行过 rtmp,grep 全部 serial.log 无 rtmp 响应样本。改动 1 的 expect 正则是猜的宽松值。修复后首次跑测试时,需观察 serial.log 里 `rtmp_video_start` 后 EVB 的真实输出,若有明确的成功标志(如 `RTMP push started`/`stream ready` 之类),回填进 expect 正则收紧判据;若固件确实无明确标志(静默推流),则维持现状靠 ffprobe 主判据。

**这一步是实测驱动的,代码改完先跑一次,根据 serial.log 结果决定是否微调 expect。**

### 改动 4:按规则记 devBugLog + 更新 README 索引

新建 `doc/devBugLog/20260813_<HHMM>_RTMP推流exec_async改造.md`,记录:问题(exec_sync 被 FTP 刷屏打乱)、根因、修复(exec_async + ffprobe 侧信道 + 前置压制 FTP)、验证结果。更新 README.md 索引。

## 不改的部分

- `rtmp_receiver.py`:拉流/验证逻辑正确,不动。
- `test_config.yaml`:RTMP 配置已就绪,不动。
- `core/`、其他模块:不动。

## 验证步骤

1. 改完代码后 `python3 -m ATS.main --dry-run` 确认配置/依赖仍绿。
2. 真机跑 `python3 -m ATS.main --no-interactive-wifi`(8 模块含 rtmp)。
3. 看 rtmp 结果:
   - PASS → ffprobe 验到流,RTMP 验证完成,7/7→8/8 全绿。
   - FAIL → 查 serial.log 里 rtmp_video_start 真实输出,按改动 3 微调 expect 或排查固件推流命令。
4. 记录 devBugLog(含实测 serial.log 片段作为成功标志参考,补全历史空白)。

## 风险

- **固件推流命令名可能不是 `rtmp_video_start`**:交接文档/设计文档都写的是这个名,但实测与手册多处不符(文档 5.x)。若改完仍 FAIL 且 serial.log 显示 `unknown command`,需查板子实际命令名(msh 输入 `rtmp` 按 tab 补全,或 `help`)。
- **EVB 推流需 PC 先起 RTMP 服务**:当前 ffmpeg 是**拉流端**(`-i rtmp://pc_ip/...`),要求 PC 上有 RTMP 服务端接收。ffmpeg 拉流连的是 PC 的 1935 端口--若 PC 没起 nginx-rtmp/flv 服务器,ffmpeg 拉流会连不上,EVB 推流也无目标。**这点需在跑测试前确认**:PC 上是否有 RTMP 服务端监听 1935?(可能需要额外起一个,或 EVB 推流地址/方向理解有误)。这是本次修复最大的未知点,实测时重点观察。
