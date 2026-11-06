# 测试策略（Test Strategy）

## 1. 测试层级

| 层级 | 方式 | 说明 |
|------|------|------|
| 配置校验 | `--dry-run` | 不连板子，校验配置与依赖 |
| 模块级 | 单模块真机 | 验证单个功能 |
| 场景级 | normal/stress/aging | 完整链路 |
| 手动调试 | `--terminal` | 交互式串口终端，类 Xcom |

## 2. 测试方法

- **主判据优先串口正向标志**（`Capture completed successfully.`、`Video recording completed successfully.`、`Got IP address`、`publish ready`），不靠「无 error 关键字」（初始化日志含 `invalid` 等词会误判）。
- **辅助判据**：FTP 下载校验（JPEG 头 FFD8FF + 大小阈值），失败降级不判 FAIL（串口已确认成功）。
  ⚠️ 固件存在「假成功」：jpg 写失败（`write failed errno=0` / `write open failed errno=-2`）时仍打印 `Save Photo Successful`/`Capture completed successfully.`，此时「未列出 jpg」是唯一暴露失败的信号，应视为需警惕信号而非完全忽略（见 `05_handoff/known_issue.md` eMMC 失效条目）。
  ⚠️ **大小阈值必须按产物类型分档**：同目录下主图（1008×4032 / 1920×1080 等，≥12KB）与固件缩略图 `*_thum.jpg`（480×360，约 9KB）尺寸量级不同，共用同一 `photo_min_size_kb` 会把正常缩略图判成「文件过小」（BUG-008，已修复：三档 `photo_min_size_kb` / `photo_thumb_min_size_kb` / `photo_heif_min_size_kb`）。HEIC 产物仅 7~83KB，同样需独立档位。
  ⚠️ **长时间压测须考虑 eMMC 容量**：实测约 0.53GB/cycle，58.7GB 盘在 ~53 cycle 写满，之后固件拒绝拍照/录像（`eMMC full: not enough free space`），photo/video/rtmp 连锁 FAIL。看到这类 FAIL 先看串口 `Free:` 是否归零，不要当判据 bug 排查。见 `05_handoff/known_issue.md`「eMMC 容量写满」。
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
