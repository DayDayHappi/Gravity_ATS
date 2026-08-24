# 术语表（Glossary）

统一术语，防止不同 Agent 对同一概念产生不同理解。

## Scenario（场景）

一次完整测试流程的描述，定义「怎么组合测试」：prepare 动作、tasks 任务列表、loop 循环、cleanup 动作。对应 `config/scenarios/*.yaml`。

## Module（模块）

可复用的业务能力单元，实现「一次测试动作 + 参数接口」，不感知场景/循环。对应 `modules/*.py` + `config/modules/*.yaml`。

## Runner（调度器）

负责「什么时候执行」：按 Task 列表调度、repeat/loop、重试、fail-fast。

## Prepare / Cleanup

运行前环境准备阶段 / 运行后清理阶段。Scenario 层的框架级动作（如 serial_init、wifi_connect、ftp_ready、stop_stream、close_serial）。

## Task（任务）

Scenario 中 tasks 列表的一项，声明要执行的 module + 参数（repeat / duration）。

## 哨兵（Sentinel）

命令结束定界机制：发 `cmd` 后追加 `echo "TOKEN"`，等行首 TOKEN 出现即认为命令已返回（同步命令用）。

## exec_sync / exec_async

两种串口执行方式：exec_sync（同步，发命令+哨兵，等哨兵定界）；exec_async（异步，只发命令，直接等业务正则，不依赖哨兵）。

## heartbeat（心跳）

RTMP 推流持续性检测：用板端 `[RTMP] f_index` 日志作心跳，超时无心跳判推流异常。

## EVB

Evaluation Board，评估板。

## msh

RT-Thread 的命令行 shell（提示符 `msh />` 或子目录 `msh /emmc>`）。

## eMMC

嵌入式多媒体存储卡，板端挂载到 `/emmc`。

## RTMP

Real-Time Messaging Protocol，实时消息传输协议（推流）。

## FTP

File Transfer Protocol，文件传输协议（板端只支持主动模式，用户 loogg/loogg）。

## ffprobe / ffplay

ffmpeg 工具链：ffprobe 实时探测流（主判据），ffplay 可选画面确认。

## 波特率（Baudrate）

串口速率，实测 UART0 = **2000000**（手册 250000 为旧固件）。

## IDR（关键帧）

视频编码中的关键帧。板子编码慢会导致 IDR 稀疏，影响 ffprobe 探测速度。
