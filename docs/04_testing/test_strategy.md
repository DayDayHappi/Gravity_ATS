# 测试策略（Test Strategy）

## 1. 测试层级

| 层级 | 方式 | 说明 |
|------|------|------|
| 配置校验 | `--dry-run` | 不连板子，校验配置与依赖 |
| 模块级 | 单模块真机 | 验证单个功能 |
| 场景级 | normal/stress/aging | 完整链路 |
| 手动调试 | `--terminal` | 交互式串口终端，类 Xcom |

## 2. 测试方法

- **主判据优先串口正向标志**（`Capture completed successfully.`、`Save Video Successful`、`Got IP address`、`publish ready`），不靠「无 error 关键字」（初始化日志含 `invalid` 等词会误判）。
- **辅助判据**：FTP 下载校验（JPEG 头 FFD8FF + 大小阈值），失败降级不判 FAIL（串口已确认成功）。
- **异步命令**靠业务正则，不靠哨兵（业务未完成 shell 已返回）。
- **RTMP**：ffprobe 实时探测（主）+ heartbeat 持续检测。

## 3. 测试原则

- **fail-fast**：依赖模块 FAIL/ERROR 才 SKIP 本模块；SKIP 不阻断依赖（主动跳过不算失败）。
- **长等待带进度心跳**：>10s 的 sleep 改成分段 sleep + 周期打印，防误判卡住。
- **拍照失败只标该模式 FAIL**，继续下一个模式，不中断后续录像/推流。
- **跑之前**：清残留进程、确认 nginx-rtmp 已启动（`ss -tln | grep 1935`）、PC 防火墙放行高位端口。

## 4. 验证顺序

```bash
python3 -m ATS.main --scenario normal --no-interactive-wifi   # 先通正常链路
python3 -m ATS.main --scenario stress --no-interactive-wifi   # 再通压测循环
```
