# 串口控制器通信独立日志留痕（power_switch.log）

## 问题描述

串口控制器（PowerSwitch）走独立 pyserial 直连，`_send_frame`/`_read_frame` 收发帧不写任何日志，
通信字节无留痕，压测问题无法回溯。需让控制器通信写独立文件 `power_switch.log`，与板子的
`serial.log` 分离（压测时开关切换稀疏，不宜混入板子高频串口流）。

## 修复内容（Level 1 模块内部，无需 ADR）

### 1. ATS/core/logger.py

- 新增模块级句柄 `_PWR_FP = None`（对齐 `_SERIAL_FP` 写法）。
- 新增 `log_power_switch(direction, data)`：**懒加载**——首次调用才
  `open(os.path.join(_LOG_DIR, "power_switch.log"), "w", encoding="utf-8")`；
  `_LOG_DIR` 为 None（logger 未初始化）时静默 return。格式与 serial.log 一致：
  `[HH:MM:SS.mmm] TX> A0 01 03 A4`。
- `close()` 补 `_PWR_FP` 关闭与置 None（已打开才关）。

### 2. ATS/drivers/power_switch.py

- `_send_frame(ser, frame)`：`ser.flush()` 后加
  `logger.log_power_switch("TX>", frame.hex(" ").upper())`。
- `_read_frame(ser, timeout)`：读到非空 `buf` 后、`return buf` 前加
  `logger.log_power_switch("RX<", buf.hex(" ").upper())`（空读 `b""` 不记，避免超时刷屏）。
- 帧字节仍只从 `power_commands.py` import，日志只是 hex 渲染，不内联协议字节（红线）。

### 3. ATS/main.py

- `--power-stress` 分支内、调 `run_ps_stress` **前**先初始化 logger（关键前置，否则
  `_LOG_DIR=None` 恒空转）。日志根目录单独约定 `logs/power_stress/<date>/`（power-stress
  不是 scenario，不复用 `_resolve_output_dirs` 场景分层；复用 `report.log_dir` 基准）。
- 顺带 `init_logger` 会一并打开 `run.log`/`serial.log`（正常副作用，run.log 记录压测汇总日志，
  serial.log 因无板子串口而不写字节）。

## 验证结果

- `py_compile` / `compileall ATS/` 通过。
- fake-serial 单测：`_send_frame`/`_read_frame` 留痕后 power_switch.log 正确生成，
  含 `TX> A0 01 03 A4`、`RX< A0 01 01 A2` 行，时间戳+方向+hex 大写格式正确；空读不产生 RX 行。
- 懒加载验证：logger 未初始化时静默 return 不产文件；初始化后未调用不产文件。
- 压测路径端到端 mock（3 周期）：power_switch.log 含 TX/RX 各 6 行，完整收发帧
  （上电 ON / 下电 OFF 各帧正确）。
- enabled=false 的 power_switch_init/close 路径：不产生 power_switch.log。

**待真机**：`python3 -m ATS.main --power-stress`，压测结束后
`logs/power_stress/<date>/<run_ts>/power_switch.log` 存在且含完整 60 次切换收发帧；
板子 `serial.log` 不被控制器帧污染。

## 还会再有吗

探测阶段对非控制器端口（噪声/可能误接的 EVB）发帧后的回帧也会记入 RX，属可接受的合理留痕
（有助于排查防接反）。日志格式与 serial.log 对齐，便于工具链复用。

## 经验沉淀

- 独立 pyserial 直连通道（二进制帧）与文本串口通道应分别留痕，稀疏帧不宜混入高频流，
  否则回溯时被淹没。
- 日志文件懒加载（首写才 open）可避免「每次运行多一个空文件」；`_LOG_DIR=None` 早退保证
  未初始化路径零副作用。
- 工具型 CLI 独立分支（--terminal/--power-stress）在 `init_logger` 之前 return，会绕过日志
  初始化——需要日志留痕的工具必须在分支内自行初始化 logger。
