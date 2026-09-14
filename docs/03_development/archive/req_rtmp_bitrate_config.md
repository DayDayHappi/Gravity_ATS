# 新增需求：RTMP 推流码率可选配置

## Background

`rtmp` 模块当前只做推流（`rtmp_video_start`）与验证（ffprobe + heartbeat），不设置推流码率。用户需要在推流前可设置码率，命令为：

```
cam_set live bitrate <value>
```

在 `rtmp_video_start` **之前**发送。该命令属固件协议，按 ADR-011 应沉淀到 `drivers/rtmp_commands.py`，不得内联到业务逻辑。

## 需求

1. **协议沉淀**：码率命令 + 超时写到 `ATS/drivers/rtmp_commands.py`（唯一来源）。
2. **业务插入点**：`ATS/modules/rtmp.py` 的 `run()` 中，在 `rtmp_video_start` 之前，若配置了码率则发送该命令。
3. **scenario 可选配**：码率通过配置项可选，不配置则行为与现状完全一致（不发命令）。

## 协议定义（drivers/rtmp_commands.py）

- `RTMP_BITRATE_COMMAND = "cam_set live bitrate {bitrate}"`（命令模板，值在业务侧 format，与 `RTMP_START_COMMAND = "rtmp_video_start {url}"` 同范式）
- `RTMP_BITRATE_TIMEOUT = 10.0`（默认超时，可调）

## 业务逻辑（modules/rtmp.py）

`run()` 中，在 `# 3. EVB 开始推流`（`exec_async(RTMP_START_COMMAND...)`）之前插入：

- 读 `bitrate = self.config.get("bitrate", 0)`
- 若 `bitrate` 有效（正整数 `> 0`）：
  - `r = console.exec_sync(commands.RTMP_BITRATE_COMMAND.format(bitrate=bitrate), timeout=commands.RTMP_BITRATE_TIMEOUT)`
  - `r.success` 为 False → 直接 `self._fail(...)`，不继续推流（与 video 模块 `cam_set` 失败即 FAIL 对齐）
- 若未配置 / `0` / 空 → 跳过，不发送。

## 配置

- `ATS/config/modules/rtmp.yaml`：新增 `bitrate: 0`（`0` = 不设置，保持现状默认行为），注释说明可选。
- scenario 层：`task.override` 里可配 `bitrate: 18000000`，经 runner 的 `params` 合并进模块 `self.config`，实现「可选配」。

## 边界

- 不配置 / `0` / 空 → 不发命令，行为与现状一致（纯增量，无回归风险）。
- 码率值**不做合法性校验**（固件自行拒绝非法值）；只要求按正整数解释（`int(...)`），非数字在 format 前即失败。
- 命令模板值来自用户实测命令 `cam_set live bitrate 18000000`，数字部分可变，故用模板 + format。

## 留痕（工程红线）

- 改 `ATS/` 代码 → 新建 `docs/03_development/devlog/<YYYYMMDD>_<HHMM>_<描述>.md` 并更新其 README 索引。
- 协议新增到 `rtmp_commands.py` 属 ADR-011 既定范式，无需新 ADR。
