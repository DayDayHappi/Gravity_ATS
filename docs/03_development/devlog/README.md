# devBugLog - 修改记录索引

本目录记录 ATS 脚本的所有修改（bug 修复、功能改进、重构等）。

## 规则

**每次对 ATS 代码的修改，都必须在本目录新建一个记录文档**，文件名格式：

```
<YYYYMMDD>_<HHMM>_<简短描述>.md
```

例如：`20260812_2302_修复连续运行emmc报错.md`

## 文档模板

每篇记录包含：

1. **问题描述**：现象、复现步骤、严重程度
2. **根因分析**：为什么会这样
3. **修复内容**：改了哪些文件、具体改动（diff 形式）
4. **验证结果**：修复后如何验证、结果数据
5. **还会再有吗**：是否彻底解决、有无残留风险
6. **经验沉淀**：可复用的排查思路或设计原则

## 文件清单

按时间倒序：

| 日期 | 文件 | 说明 |
|------|------|------|
| 2026-09-22 | [20260922_1330_ADR016运行时闭环修复7P0_6P1.md](20260922_1330_ADR016运行时闭环修复7P0_6P1.md) | ADR-016 运行时闭环修复（验收报告驱动 7 P0+6 P1）：P0-01/02 watchdog 持续监测线程（check_interval 超时置 SUSPECTED+request_recovery，禁阻塞）+ runtime_control 触发链闭环；P0-03 confirm_health 同安全点一次性 confirm_failures 次确认；P0-04 ScenarioAbort 异常退出整个 loop；P0-05 recovery_history 在 ctx.cleanup 前保存到 manager；P0-06 snapshot_rx_cursor/wait_for_ready_since fresh-ready；P0-07 monitor-only UNRESPONSIVE 记 board_health FAIL+abort；P1-01 retry 二次 Outcome while 循环处理、P1-02 validate 前置校验 backend、P1-03 recovery 要求 monitor、P1-04 restore fail-closed、P1-05 HTML Recovery Events、P1-06 参数合法性校验+时间参数接线；离线 mock 全过待 TC-BH/TC-RCV 真机 |
| 2026-09-21 | [20260921_1820_板卡健康监测与可插拔恢复机制ADR016实施.md](20260921_1820_板卡健康监测与可插拔恢复机制ADR016实施.md) | ADR-016 实施（Phase 1~5）：新增 ATS/application/ 包（board_health_monitor.py HEALTHY/SUSPECTED/UNRESPONSIVE 状态机+listener 轻量、recovery_coordinator.py IDLE→RECOVERING→RECONCILING→HEALTHY/FAILED+互斥+max_attempts、recovery_backends/base+power_cycle、runtime_control.py 协作式取消）；core 加 log_recovery/recovery.log、Context.invalidate_board_runtime_state、Scenario health_monitor/recovery 字段、board_ready+health_monitor_start/stop 动作、runner recovery checkpoint、reporter recovery_events、video.py 长录像 runtime.wait；config/modules/board_health.yaml；全部能力默认关闭向后兼容，红线全守（Monitor 不认识 PowerSwitch、listener 禁阻塞、禁静默 fallback），离线 TC-BH/TC-RCV mock 全过待真机 |
| 2026-09-21 | [20260921_1517_TCPS001节拍改15min乘2周期与长等待心跳.md](20260921_1517_TCPS001节拍改15min乘2周期与长等待心跳.md) | TC-PS-001 节拍改 15min×2 周期：power_switch_stress.py 的 _DEFAULT_CYCLES 30→2、_DEFAULT_HOLD_ON/OFF 10→900s（对称交替总时长 1h 4 次切换），docstring 同步；新增 _HEARTBEAT_STEP=60 + _sleep_with_heartbeat 分段 sleep 进度心跳（>10s 长等待防误判卡死，test_strategy 原则），两处 time.sleep 改调；协议/配置零改动，Level 1 无 ADR，mock 2 周期 PASS 待真机 |
| 2026-09-21 | [20260921_1436_压测首轮上电误判修复_读空重试与探测后延时.md](20260921_1436_压测首轮上电误判修复_读空重试与探测后延时.md) | 压测首轮上电误判修复：根因是探测帧与 cycle1 上电帧间隔约 3ms 被控制器去抖忽略、不回响应；两层修复——驱动层 power_switch.py 新增 _send_and_read 读空响应延时 0.5s 重发一帧（power_on/off 共用，reboot 自动继承），压测层 power_switch_stress.py 探测后加 _DETECT_SETTLE_DELAY=0.5 错开；不改帧常量/判据/配置，Level 1 无 ADR，mock 端到端 PASS 待真机 |
| 2026-09-21 | [20260921_1402_串口控制器通信独立日志留痕power_switch_log.md](20260921_1402_串口控制器通信独立日志留痕power_switch_log.md) | 串口控制器独立日志留痕：logger.py 新增 _PWR_FP 句柄 + log_power_switch(direction,data) 懒加载（首次写才 open power_switch.log，_LOG_DIR=None 静默 return），close 补关闭；power_switch.py 的 _send_frame/_read_frame 收发帧处写 TX>/RX< hex 大写留痕（空读不记）；main.py --power-stress 分支内先 init_logger（logs/power_stress/<date>/），否则 _LOG_DIR=None 恒空转；Level 1 无 ADR，mock 端到端 PASS 待真机 |
| 2026-09-21 | [20260921_1330_上下电控制模块发帧读响应与TCPS001压测.md](20260921_1330_上下电控制模块发帧读响应与TCPS001压测.md) | TC-PS-001 压测补强：power_commands.py 新增 is_valid_state_frame/frame_state 判据（校验和+帧头+状态提取，ADR-011 唯一来源）；power_switch.py 的 power_on/power_off 增强为发帧+读响应返回，新增 query_state；新建 tools/power_switch_stress.py（--power-stress，上电 10s/下电 10s×30 周期，上电回 ON 硬判据+长连接存活性）；main.py 加 --power-stress CLI 分支；Level 1 模块内部无 ADR，mock 冒烟 PASS 待真机 |
| 2026-09-21 | [20260921_1104_串口上下电控制模块ADR-015实施.md](20260921_1104_串口上下电控制模块ADR-015实施.md) | ADR-015 实施：新增 drivers/power_commands.py（4 字节二进制帧协议唯一来源：上电 A0 01 03 A4/下电 A0 01 02 A3/状态 A0 01 01 A2|A0 01 00 A1，末字节=前三字节求和&0xFF）+ drivers/power_switch.py（PowerSwitch 能力接口 power_on/off/reboot + detect_power_switch 独立探测长连接）；system.yaml 增 power_switch 段（enabled:false 默认关零影响）；scenario_manager 注册 power_switch_init/power_switch_close 动作，normal/stress 挂接；不接触发时机（红线），reboot_delay TODO-CONFIRM 待真机 |
| 2026-09-20 | [20260920_1053_修复环形缓冲滚满致cam_set误判_方案A序号游标定位.md](20260920_1053_修复环形缓冲滚满致cam_set误判_方案A序号游标定位.md) | 方案 A 修复 serial_console 环形缓冲滚满后快照定位失效致 cam_set 误判：快照从字符串前缀改单调递增序号游标（deque(str)→deque(tuple[int,str])，新增 _snapshot_seq/_buffer_text_since，_wait_pattern/_wait_regex/exec_sync/exec_async/wait_for_ready 改用游标），并收窄 _ERROR_RE 排除 invalid,use default 相机正常 fallback；对外 API 不变，离线模拟滚满场景 PASS，待真机 stress 26 轮验证 |
| 2026-09-18 | [20260918_0030_新增检测串imu_fmq_overflow.md](20260918_0030_新增检测串imu_fmq_overflow.md) | 新增检测串 `imu fmq overflow f=`：detect_strings.py 追加 imu_fmq_overflow（字面串、`=` 后数字不校验、跨 chunk 前缀自动推导），video/rtmp.yaml 的 detect_strings 加 imu_fmq_overflow；纯数据改动，业务代码零改动 |
| 2026-09-18 | [20260918_0010_检测关键字符串集中化与配置选择ADR-014.md](20260918_0010_检测关键字符串集中化与配置选择ADR-014.md) | ADR-014 源码实施：检测串集中到 drivers/detect_strings.py（DetectString+DETECT_STRINGS 唯一来源）；tt_error_monitor.py→string_hit_monitor.py（TTErrorMonitor→StringHitMonitor 泛化，截断前缀自动推导+展示文案 attach_to 收敛）；video/rtmp 改读 detect_strings 配置、删两份 _attach_tt_hits；video/rtmp.yaml 加 detect_strings:[tt_error]；缺省不检测 |
| 2026-09-17 | [20260917_1824_utest细粒度判据实施.md](20260917_1824_utest细粒度判据实施.md) | utest 单文件→包迁移 + D1 叠加判据：drivers/utest_commands.py→drivers/utest/（_common + 8 per-case commands，业务关键串正则 D7 严格/宽松）、modules/utest.py→modules/utest/（base.py 叠加判据模板 + 8 case 模块 utest_*）、scenario tasks 改 8 个 utest_<case>、config._MODULE_FILE_MAP 补映射、utest.yaml 加 min_speed_kbs=0；mock 样本 8 case 全 PASS + 负向路径（业务串缺失/FAILED 不救回/无 result 行/阈值）全符合 D1 |
| 2026-09-17 | [20260917_1659_video新增480p_1组合.md](20260917_1659_video新增480p_1组合.md) | video 新增 480p_1：video_commands.py 的 VIDEO_PROFILES 补 480p_1（cam_set video 480p 1，640×480 横屏 TODO-CONFIRM）+ 从 BLOCKED_VIDEO_PROFILES 移除（保留空常量防 NameError）；stress.yaml 480p_0/480p_2 之间插 480p_1 task；video_size_traverse.yaml 仅修正过时禁用注释（不加 480p_1）；video.py 零改动 |
| 2026-09-17 | [20260917_1634_stress_photo模式独立repeat拆分.md](20260917_1634_stress_photo模式独立repeat拆分.md) | stress.yaml photo task 1→10 拆分（各单模式 + repeat:1，搭骨架支持每模式独立 repeat）；机制已核实 photo.py 遍历单元素列表 + Runner 按 repeat 驱动 + override 整体替换，纯配置零源码改动；其余 task/prepare/loop/cleanup 未动，非 photo task 13 个不变 |
| 2026-09-17 | [20260917_1620_photo单拍新增3个分辨率变体.md](20260917_1620_photo单拍新增3个分辨率变体.md) | photo 单拍新增 single 1080p/720p/480p 3 个分辨率变体：photo_commands.py 的 PHOTO_MODES 枚举 +3 条，stress.yaml photo task override.photo_modes 7→10 项；命令模板 str.format 天然支持含空格模式名，photo.py 零改动；已核实 report 消费方对含空格 name 无副作用，待真机核实固件是否接受三 token 写法 |
| 2026-09-17 | [20260917_0927_utest真机修复4点.md](20260917_0927_utest真机修复4点.md) | utest 真机修复：pvt_auto_test 超时 10→20（真机实测 10.2s）；哨兵超时后先用白名单 UTEST_RESULT_RE 重判 r.clean（修复「result 行已出现却误报未知」），抽 _mk_from_status 复用；场景去掉 qspi_test（9→8 项）；去掉「脚本超时」日志打印 |
| 2026-09-16 | [20260916_1832_串口探测指纹按场景分派ADR-013.md](20260916_1832_串口探测指纹按场景分派ADR-013.md) | ADR-013 实施：串口探测/就绪指纹按场景分派（utest 固件 `msh >` 无斜杠适配）；serial_console 加 _FINGERPRINT_SETS/_READY_RE_SETS 映射 + detect_port(fingerprint_set=)/SerialConsole(ready_set=) 可选参数，Scenario 加 serial_fingerprint 字段，scenario_manager parse/run/serial_init 透传，utest.yaml 加 serial_fingerprint: utest；default 路径逐字不动零影响 |
| 2026-09-16 | [20260916_1720_新增utest固件自检框架接入.md](20260916_1720_新增utest固件自检框架接入.md) | ADR-012 实施：新增 utest 独立模块与场景（9 项板级自检），唯一判据取 testcase 级 result 行，显式传 expect 避开 _ERROR_RE 误判 qspi "1 lane fail!"，每项独立超时由 scenario 驱动；新增 4 文件 + 1 接线，现有代码零改动 |
| 2026-09-16 | [20260916_0001_无网络场景cleanup移除冗余stop_stream.md](20260916_0001_无网络场景cleanup移除冗余stop_stream.md) | no_network.yaml cleanup 移除冗余 stop_stream（场景不推流却发 rtmp_video_stop 空等约 8s），只留 close_serial |
| 2026-09-16 | [20260916_0000_下载行为可配置与无网络场景.md](20260916_0000_下载行为可配置与无网络场景.md) | photo/video 新增 `ftp_download` 开关（默认 true）；false 时走纯拍摄/纯录像分支（不碰 FTP）；新增无网络场景 no_network.yaml（prepare 去 wifi/ftp/preview，photo/video override ftp_download=false，去 rtmp/video_integrity） |
| 2026-09-14 | [20260914_1358_rtmp码率可选配置.md](20260914_1358_rtmp码率可选配置.md) | RTMP 新增可选推流码率设置：rtmp_commands.py 加 RTMP_BITRATE_COMMAND/RTMP_BITRATE_TIMEOUT，rtmp.py 在 rtmp_video_start 之前可选发送 cam_set live bitrate（失败即 FAIL），rtmp.yaml 加 bitrate: 0（0=不设置，task.override 可覆盖） |
| 2026-09-14 | [20260914_1321_ADR011_emmc_CD_ROOT_timeout收尾.md](20260914_1321_ADR011_emmc_CD_ROOT_timeout收尾.md) | ADR-011 收尾：emmc_commands.py 补 EMMC_CD_ROOT_TIMEOUT=5.0，scenario_manager preclean 的 cd / 裸超时 5.0 提升为命名常量（值不变） |
| 2026-09-14 | [20260914_1110_串口协议集中化ADR-011.md](20260914_1110_串口协议集中化ADR-011.md) | ADR-011 实施：photo/rtmp/ftp/wifi/emmc 协议字符串（命令/判据/超时/正则/路径）集中迁移到 drivers/<module>_commands.py 唯一来源，模块与 scenario_manager 改查表引用；纯移动不改语义；顺带修 emmc.py 缺失 logger 导入、EMMC_CD_ROOT_COMMAND 显式化 cd / |
| 2026-09-09 | [20260909_录像size显式命令与遍历.md](20260909_录像size显式命令与遍历.md) | 新增 drivers/video_commands.py 完整命令表（11 种 size 组合 ID，含宽高/方向/禁用校验）+ video.py 改查表不拼命令 + 新增 video_size_traverse.yaml 场景 + 24 项离线回归通过，待真机 |
| 2026-09-09 | [20260909_1940_video_size_traverse接入H265检测.md](20260909_1940_video_size_traverse接入H265检测.md) | video_size_traverse 场景 11 个 video 后插入 video_integrity（all_unchecked+skip，一轮 29 文件全检跨 loop 去重）+ 头注释修正 + cleanup 补 stop_stream 兜底 |
| 2026-09-09 | [20260909_1457_新增场景3k录像压测.md](20260909_1457_新增场景3k录像压测.md) | 新增场景 stress_traverse_photo_mode_3k.yaml（复制 stress_traverse_photo_mode，唯一差异 video task override.video_resolution="3k"），纯配置不改源码，全局默认保持 1080p |
| 2026-09-09 | [20260909_1437_TT_ERROR检测与rep字段报告.md](20260909_1437_TT_ERROR检测与rep字段报告.md) | video/rtmp 过程检测 TT ERROR（命中不判 FAIL，仅报告标注 cycle/rep 与第几次命中）；TestResult 新增 rep 字段 + runner 传递填充 + 新建 tt_error_monitor.py（严格匹配+跨 chunk 拼接）+ reporter JSON/HTML 加 rep/轮次次数列 |
| 2026-09-08 | [20260908_1847_video_integrity新增all_unchecked_selection.md](20260908_1847_video_integrity新增all_unchecked_selection.md) | video_integrity 新增 selection 值 `all_unchecked`（过滤已检 + 取全部，与 latest_unchecked 对称；现有 latest/all/latest_unchecked 行为不变），解决 video repeat 多文件「全检 + 跨 loop 不重复检」 |
| 2026-09-08 | [20260908_1608_RTMP心跳超时阈值默认值对齐30to40.md](20260908_1608_RTMP心跳超时阈值默认值对齐30to40.md) | RTMP heartbeat_timeout 三处默认值对齐 30→40（rtmp.py L120 fallback + rtmp_monitor.py docstring/示例/__init__），yaml 权威值 40 不动，纯参数默认值对齐 |
| 2026-09-07 | [20260907_2039_stress_traverse接入H265完整性检测.md](20260907_2039_stress_traverse接入H265完整性检测.md) | stress_traverse_photo_mode 场景 video 与 rtmp 之间插入 video_integrity task（override source=current_run/selection=latest_unchecked/empty_input_policy=skip），形成录像→检测闭环 |
| 2026-09-07 | [20260907_2007_RTMP心跳正则放宽为裸f_index匹配.md](20260907_2007_RTMP心跳正则放宽为裸f_index匹配.md) | RTMP heartbeat 正则锚定 `[RTMP]` → 裸 `f_index\s*=\s*\d+`（固件日志格式 `[RTMP] f_index` → `I/App Rtmp: f_index` 变更，monitor 失配 60s 误判 TIMEOUT）；窗口隔离前提钉死；同步修正 rtmp.py/rtmp.yaml/video.py 过时 `[RTMP]` 注释 |
| 2026-09-07 | [20260907_1853_video模块默认分辨率改为3k.md](20260907_1853_video模块默认分辨率改为3k.md) | video 模块默认分辨率 `video_resolution` 1080p → 3k（纯配置改 modules/video.yaml，video.py fallback 不动；3k 档经真机日志核实合法） |
| 2026-09-07 | [20260907_1848_video录像前恢复cam_set.md](20260907_1848_video录像前恢复cam_set.md) | video 录像前恢复 cam_set：删除 `if False:` 跳过逻辑 + TODO-TEMP-DISABLE-CAM_SET 注释，cam_set video 还原顶格（仅挑 testvideo 分支 dcf19ff 的恢复 cam_set 段） |
| 2026-09-02 | [20260902_1339_新增H265视频完整性检测模块.md](20260902_1339_新增H265视频完整性检测模块.md) | 新增 H265 视频完整性检测：drivers/h265_validator.py（FFmpeg 三阶段诊断+错误分类+POC gap 判定）+ modules/video_integrity.py（文件选择+manifest 去重+聚合 TestResult，模块内 deep-merge）+ 配置与 standalone 场景 |
| 2026-08-31 | [20260831_1032_日志目录按场景日期运行时间戳分层.md](20260831_1032_日志目录按场景日期运行时间戳分层.md) | 日志目录按「场景/日期/run_ts」三级分层：所有场景日志统一 logs/<场景>/<日期>/（去掉中间冗余 logs 层），报告也按天分（normal->reports/<日期>/、非 normal->logs/<场景>/report/<日期>/），problem 记录不按天打散到 logs/<场景>/problem/ |
| 2026-08-28 | [20260828_0233_stress_traverse注释去具体时长次数.md](20260828_0233_stress_traverse注释去具体时长次数.md) | stress_traverse_photo_mode.yaml 注释去具体时长/次数（video 3min/rtmp 10min/20 次 → 自行按需配置；repeat 行内注释去掉「50 次」），纯注释 |
| 2026-08-27 | [20260827_0739_video录像前暂时取消cam_set.md](20260827_0739_video录像前暂时取消cam_set.md) | video 录像前临时禁用 cam_set video，直接 dfs_video_start（TODO-TEMP-DISABLE-CAM_SET 标记，后续恢复） |
| 2026-08-27 | [20260827_0721_video启动判据加f_index与失败清理.md](20260827_0721_video启动判据加f_index与失败清理.md) | video 启动判据 Record Start → Record Start\|f_index=（固件漏打 Record Start 但编码在跑时不再误判）；失败分支补发 dfs_video_stop 清理 stream_on 半初始化态，避免泄漏给 rtmp |
| 2026-08-26 | [20260826_2321_video判据改VideoRecordingCompleted与路径扫描.md](20260826_2321_video判据改VideoRecordingCompleted与路径扫描.md) | video 判据 Save Video Successful → Video recording completed successfully.（出现早/路径分块截断致 flaky）；路径改从 r.clean 缓冲扫描 /emmc/VIDEO/<dir>/Video_<n>_0.h265 |
| 2026-08-26 | [20260826_2247_新增场景stress_traverse_photo_mode.md](20260826_2247_新增场景stress_traverse_photo_mode.md) | 新增 stress_traverse_photo_mode.yaml：photo task 用 override.photo_modes 遍历 auto/single/mfnr/hdr_0~3 全模式，其余与 stress 一致（纯配置，不改源码） |
| 2026-08-25 | [20260825_0514_photo判据改CaptureCompleted与路径扫描.md](20260825_0514_photo判据改CaptureCompleted与路径扫描.md) | photo 主判据 Save Photo Successful → Capture completed successfully.（日志未打印完/路径分块截断致提前发命令错位）；路径改从 r.clean 累积缓冲扫描 /emmc/PIC/<ts>/ |
| 2026-08-25 | [20260825_0111_PreviewManager单例播放器实施.md](20260825_0111_PreviewManager单例播放器实施.md) | ADR-010 实施：新增 drivers/preview_manager.py + config/modules/preview.yaml，ffplay 从 rtmp 模块抽离为 Scenario 生命周期单例，scenario_manager 挂 preview_start/preview_stop 动作，normal/stress 补 preview.enabled |
| 2026-08-24 | [20260824_2259_修正base模块docstring语义.md](20260824_2259_修正base模块docstring语义.md) | 修正 base.py docstring 过时语义（拓扑排序→声明顺序执行；depends→运行时 fail-fast），对齐 ADR-009 |
| 2026-08-24 | [20260824_0555_stress场景循环次数3改10.md](20260824_0555_stress场景循环次数3改10.md) | stress 场景 loop.count 3 → 10（压测整轮循环增至 10 次）；第 1 行注释「3 次」过时待同步 |
| 2026-08-24 | [20260824_0250_depends字段清理.md](20260824_0250_depends字段清理.md) | ADR-009 方向 A：清空 6 个模块死依赖 depends（photo/video/rtmp/ftp/wifi_scan/wifi_join），depends 只保留 task 间 fail-fast 语义 |
| 2026-08-24 | [20260824_0230_WiFi职责重划源码实施.md](20260824_0230_WiFi职责重划源码实施.md) | ADR-008 实施：normal 移除 wifi_check/scan/join，wifi_connect 改状态收敛器，wifi_check 产出 ctx.wifi_ready |
| 2026-08-24 | [20260824_0205_修复no_interactive_wifi断链.md](20260824_0205_修复no_interactive_wifi断链.md) | 修复 --no-interactive-wifi 下 wifi_connect 直接 return 导致 evb_ip 拿不到、photo/video 全 SKIP：非交互改为自动用默认 SSID join |
| 2026-08-24 | [20260824_0150_移除normal场景tasks重复ftp.md](20260824_0150_移除normal场景tasks重复ftp.md) | normal 场景 tasks 删除重复的 ftp 模块（ftp_ready 已做 FTP 准备），保留 modules/ftp.py 代码；photo/video 依赖不阻断 |
| 2026-08-20 | [20260820_2246_ftp_ready下沉ftp_server启动幂等只发一次.md](20260820_2246_ftp_ready下沉ftp_server启动幂等只发一次.md) | 新增 start_ftp 幂等函数，ftp_ready 下沉 ftp_server 启动（全局只发一次），client 每次重建；修 stress 无 ftp 模块导致 FTP 未启动 |
| 2026-08-20 | [20260820_2124_按场景隔离日志与报告目录.md](20260820_2124_按场景隔离日志与报告目录.md) | 非 normal 场景日志/报告按场景隔离：logs/<场景>/logs/ + logs/<场景>/report/ |
| 2026-08-20 | [20260820_0833_引入测试场景层Scenario配置彻底拆分.md](20260820_0833_引入测试场景层Scenario配置彻底拆分.md) | 引入 Scenario 层：配置拆 system/modules/scenarios，Runner 支持 Task/repeat/loop，模块 run(params) 参数入口，--scenario 主入口 |
| 2026-08-20 | [20260820_0759_新增gitignore只跟踪ATS与tools.md](20260820_0759_新增gitignore只跟踪ATS与tools.md) | 新增 .gitignore 并 git rm --cached 取消跟踪 logs/reports/doc/handoff/res/.claude/pyc，仓库只保留 ATS 源码 + tools 内置 ffmpeg 二进制 |
| 2026-08-20 | [20260820_0414_RTMP推流持续性检测heartbeat机制与独立monitor模块.md](20260820_0414_RTMP推流持续性检测heartbeat机制与独立monitor模块.md) | 新增独立 RTMPMonitor 模块：用板端 [RTMP] f_index 作 heartbeat 持续检测推流稳定性，串口层只加原始数据 listener 不加业务逻辑；推流中途停止 5s 内判 FAIL，杜绝盲等 sleep 误判 PASS |
| 2026-08-20 | [20260820_0206_串口同步异步命令执行机制改造_exec_async去哨兵.md](20260820_0206_串口同步异步命令执行机制改造_exec_async去哨兵.md) | 抽离统一 _write_safe；exec_async 不再发送哨兵只发命令等业务 expect；rtmp expect 从命令回显改为 publish ready/Push Start、Push Stop/Stop requested；哨兵与业务完成语义分离 |
| 2026-08-20 | [20260820_0132_修复TX时间戳晚于RX的日志假象.md](20260820_0132_修复TX时间戳晚于RX的日志假象.md) | _write_cmd 的 TX 日志从分片循环后移到循环前：分片 sleep 会让 TX 时间戳后移到"发送完成"，晚于板子回显 RX 造成"先收后发"假象 |
| 2026-08-19 | [20260819_0436_测试结束询问问题记录到logs_problem目录.md](20260819_0436_测试结束询问问题记录到logs_problem目录.md) | 测试结束询问用户本次问题，有输入则记录到 logs/problem/<时间戳>.log（回车=无问题不记录），EOFError 兜底防无人值守卡死 |
| 2026-08-19 | [20260819_0231_录像模块拍摄与下载阶段日志及耗时.md](20260819_0231_录像模块拍摄与下载阶段日志及耗时.md) | video 模块加拍摄开始/结束、FTP 开始下载/下载完成日志及各自耗时，避免录像静默期和 FTP 大文件传输让人误判卡住 |
| 2026-08-18 | [20260818_2202_ffplay低延迟参数与模块计时进度日志.md](20260818_2202_ffplay低延迟参数与模块计时进度日志.md) | ffplay 参数换成低延迟直播(-rtmp_live live -rtmp_buffer 0 -fflags nobuffer -flags low_delay -framedrop -sync ext)，URL 复用运行时 pc_ip 不写死；runner 用 time.monotonic+try/finally 给各模块开始/结束计时打印；rtmp 600s 推流改每 30s 打进度防误判卡住 |
| 2026-08-18 | [20260818_0319_rtmp推流与ffplay改为10分钟可手动关闭.md](20260818_0319_rtmp推流与ffplay改为10分钟可手动关闭.md) | rtmp 推流时长与 ffplay 展示都改 10 分钟(stream_duration=600)；原 stream_duration 是死配置、真正时长藏在 ffplay_show_duration，统一到 stream_duration 控制推流持续，删除冗余 ffplay_show_duration；ffplay 独立窗口跟随流播放、用户可手动关 |
| 2026-08-17 | [20260817_2311_ftp冷启动必须等service_launched再connect.md](20260817_2311_ftp冷启动必须等service_launched再connect.md) | 删预清理后 ftp 冷启动：init success 到 service launched 有约 3.4s 延迟，脚本只等 init success 就 connect 撞上未 listen 窗口 Connection refused；改 exec_async 等 service launched 再连 |
| 2026-08-17 | [20260817_2241_ftp每次下载前重建连接_应对3s空闲超时.md](20260817_2241_ftp每次下载前重建连接_应对3s空闲超时.md) | 板子 FTP 服务端 3s 空闲即断会话，旧代码缓存复用连接导致拍照/录像后下载失败；改为每次下载前重建独立连接(connect 恢复工作目录+关旧 socket)，ensure_ftp 不再探测旧连接，数据连接由 ftplib 主动模式每次换新端口 |
| 2026-08-17 | [20260817_0628_ftp_server只启动一次去除重复重启噪音.md](20260817_0628_ftp_server只启动一次去除重复重启噪音.md) | main.py 预清理 + ensure_ftp(force=True) 都会重发 ftp_server，叠加起来多次触发固件崩溃循环刷屏；改为全程只在 ftp 模块启动一次，ensure_ftp 只重连 PC 端客户端；wifi join 成功后加 sleep(5) 等状态稳定 |
| 2026-08-17 | [20260817_0309_rtmp移除ftp_server前置压制.md](20260817_0309_rtmp移除ftp_server前置压制.md) | rtmp 模块删除 run() 里 ensure_ftp(force=True) 前置调用：rtmp 不依赖 FTP 且重发 ftp_server 会加剧固件 FTP 崩溃循环/线程堆积拖慢推流 |
| 2026-08-17 | [20260817_0248_ffplay画面确认改用独立终端窗口播放.md](20260817_0248_ffplay画面确认改用独立终端窗口播放.md) | ffplay 画面确认改用 gnome-terminal 独立终端窗口播放(去 -rw_timeout 耐心等关键帧)；窗口生命周期独立于脚本，teardown 不再 kill |
| 2026-08-17 | [20260817_0203_RTMP探测失败_板子编码慢关键帧稀疏加大超时.md](20260817_0203_RTMP探测失败_板子编码慢关键帧稀疏加大超时.md) | rtmp 探测失败根因是板子推1080p编码慢+FTP刷屏抢CPU→关键帧IDR稀疏(600帧/57s一个)；ffprobe -rw_timeout 3s→15s、analyzeduration/probesize放宽、重试加大，耐心等IDR |
| 2026-08-17 | [20260817_0141_ffplay画面确认增强_stderr落日志与展示延长.md](20260817_0141_ffplay画面确认增强_stderr落日志与展示延长.md) | ffplay 画面确认 stderr 从 DEVNULL 改落 logs/<ts>/ffplay.log；探测到流后、stop 前延长展示窗口(新增 ffplay_show_duration 配置)，解决"启动了但看不到窗口" |
| 2026-08-17 | [20260817_0115_RTMP命令串口溢出丢字节_长命令分片写入修复.md](20260817_0115_RTMP命令串口溢出丢字节_长命令分片写入修复.md) | rtmp 推流命令(45B+哨兵77B)超板子串口缓冲RT_SERIAL_RB_BUFSZ(64B)溢出丢字节，命令截断报command not found；serial_console 新增 _write_cmd 分片+片间延时写入 |
| 2026-08-14 | [20260814_0500_MediaMTX换nginx-rtmp.md](20260814_0500_MediaMTX换nginx-rtmp.md) | 删除内置 MediaMTX，RTMP 服务端改用系统 nginx-rtmp（仅检查就绪不启停）；验证改 ffprobe 实时探测+可选ffplay，去存盘；cam1→cam 统一 |
| 2026-08-14 | [20260814_0010_新增migrate迁移脚本.md](20260814_0010_新增migrate迁移脚本.md) | 新增 `migrate.sh` 一键迁移脚本(8项检查+收集sudo命令)+`迁移指南.md`，用于换 Ubuntu PC 时初始化环境 |
| 2026-08-13 | [20260813_0535_新增串口终端模式.md](20260813_0535_新增串口终端模式.md) | 新增 `--terminal` 交互式串口终端(类Xcom)：手动发命令、实时看TX/RX、Tab切ANSI，用于RTMP等调试 |
| 2026-08-13 | [20260813_0500_RTMP服务端与拉流时序修复.md](20260813_0500_RTMP服务端与拉流时序修复.md) | RTMP 真机验证打通：引入 MediaMTX 服务端中转 + 修 ffmpeg 拉流参数(-reconnect 不兼容) + 先推后拉时序 + exec_async 抗 FTP 刷屏（4 层根因） |
| 2026-08-13 | [20260813_0400_内置ffmpeg打通RTMP依赖.md](20260813_0400_内置ffmpeg打通RTMP依赖.md) | 引入预编译静态 ffmpeg/ffprobe 到 tools/ffmpeg/，配置指向内置二进制，打通 RTMP 离线依赖（零代码改动） |
| 2026-08-13 | [20260813_0243_照片路径与视频断点续传下载.md](20260813_0243_照片路径与视频断点续传下载.md) | 照片下载打印路径；视频下载到本地（断点续传+socket超时，解决FTP卡死） |
| 2026-08-13 | [20260813_0410_wifi_check模块与依赖SKIP修复.md](20260813_0410_wifi_check模块与依赖SKIP修复.md) | 新增 wifi_check 模块（ifconfig 检测有IP跳过wifi）；修复依赖链 SKIP 误伤后续模块 |
| 2026-08-12 | [20260812_2302_修复连续运行emmc报错.md](20260812_2302_修复连续运行emmc报错.md) | emmc 连续运行报错（目录残留 + FTP 刷屏），cd 改绝对路径 + 预清理加 cd / |

## 另含

- `20260812_开发过程报告.md`：初版开发的完整过程报告（含 10 个问题的排查）
- `20260812_使用手册.md`：脚本使用手册
