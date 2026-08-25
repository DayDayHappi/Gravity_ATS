# 设计决策记录索引（ADR）

| 编号 | 决策 | 说明 |
|------|------|------|
| ADR-001 | 串口哨兵机制 | 同步命令换行哨兵定界，异步命令去哨兵等业务正则 |
| ADR-002 | 串口分片写入 | 长命令 32B/片 + 0.1s 延时防溢出丢字节 |
| ADR-003 | FTP 会话策略 | 只发一次 / 冷启动两阶段 / 重建连接 / 主动模式 |
| ADR-004 | RTMP 验证判据 | ffprobe 实时探测（主）+ heartbeat 持续检测 |
| ADR-005 | 配置三层 + Scenario 层 | Scenario/Runner/Module/Config 职责边界 |
| ADR-006 | 内置 ffmpeg + nginx-rtmp | 离线依赖 + 服务端就绪检查 |
| ADR-007 | 模块红线 | 模块只做一次动作，循环由 Scenario/Runner 驱动 |
| ADR-008 | WiFi 职责重划 | wifi_check=状态检测器，prepare.wifi_connect=状态收敛器，scan/join 退出 normal |
| ADR-009 | depends 字段语义定位 | depends 只做 task 间 fail-fast，逻辑依赖移到 module_design 文档，清空死依赖 |
| ADR-010 | PreviewManager 单例播放器 | ffplay 生命周期从 rtmp 模块剥离，归 Scenario 级 drivers/preview_manager.py，prepare/cleanup 挂载 |
