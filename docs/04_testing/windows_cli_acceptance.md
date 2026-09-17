# Windows CLI 移植验收记录

日期：2026-09-16。基线：all_source(8).txt，2026-09-16 11:06:04 / 166文件。

## 1. 结论边界

源码已实施，交付为可核对基线的增量包。**不能表述为“Windows真机已通过”或“Ubuntu硬件回归已通过”。**
本次真正执行的环境是 Debian GNU/Linux 13、Python 3.13.5、pytest 9.0.2、PyYAML 6.0.3、Jinja2 3.1.6。
系统 FFmpeg 为7.1.5-0+deb13u1。Windows API分支由测试替身验证契约，不是运行了Windows操作系统。
环境未安装pySerial；安装尝试因网络不可达失败。串口/FTP外部交互使用测试替身；没有连接EVB。
最新快照未收录用户工程根的既有tests/requirements/tools，因此不能声称已运行用户仓库原有全量测试。

## 2. 已执行的自动化验证

| 验证项 | 结果 | 证据与限制 |
|---|---|---|
| 本轮 `tests/windows_cli` | 84 passed | 完整运行，含真实Linux子进程、PTY和FFmpeg测试 |
| 增量安装器测试 | 10 passed | 只读check、正常安装、原字节备份、重复安装、冲突拒绝、CRLF/BOM、payload损坏拒绝、路径越界/软链接拒绝、异常及KeyboardInterrupt自动回滚 |
| 正常H.265完整CLI | 返回0 / PASS | 真实FFmpeg生成小视频，含中文/空格路径，生成JSON/JUnit/HTML |
| 无效H.265完整CLI | 返回1 / FAIL | 损坏输入产生解码诊断；不是声称验证了某一真实缺帧POC定位精度 |
| 编译/AST | PASS | AST覆盖交付ATS源码；compileall覆盖ATS与本轮测试 |
| 差异检查 | PASS | 原8个正式场景、8个模块YAML、system.yaml、6个串口协议文件保持原样 |
| 干净基线应用后复测 | 见包内安装验证日志 | 从原始git基线恢复干净工程，应用实际payload后重新运行84项；非Windows运行 |

包内 `validation/cli_tests.log`、`cli_test_results.xml`、`installer_tests.log`、`installer_test_results.xml` 为实际执行输出。
`validation/source_audit.json` 固化源文件和不变范围审计。
`validation/install_clean_baseline.log` 和 `installed_cli_tests.log` 固化干净基线安装与复测结果。
测试数量按用例统计，不等同84种硬件或84次Windows现场测试。

## 3. 覆盖范围

平台层：COM自然排序、USB优先、蓝牙过滤、Linux候选规则；Windows惰性msvcrt导入；POSIX粘贴中文按字符及时输出并恢复tty；平台exe选择与真实-version；拒绝显式错误路径；argv字面传递；进程超时/中断回收。

调用链：config-dir贯穿prepare/Runner/依赖检查；override在setup前生效；本地完整性检测不要求串口；CLI的新开关；setup失败的teardown；运行中断的部分结果、cycle/rep和130退出码；清理期间再次中断仍释放其它资源。

业务回归：11组完整录像命令、裸档位与禁用组合拒绝；串口换行哨兵和不带哨兵的异步命令；32字节分片；主动FTP新会话；每录即下载；H.265 all_unchecked的manifest去重；RTMP异常停流和监听器摘除；ffplay单实例、退出重连与回收。

未修改的H.265解码/showinfo/trace参数和POC算法单独进行AST结构对比；本次没有解决原算法全部潜在误判。
本次未修订原Runner任一PASS即模块通过等历史聚合策略，也没有把FTP辅助失败统一改成FAIL。

## 4. Windows现场验收（待执行）

| 项目 | 操作 / 必须观察的证据 | 状态 |
|---|---|---|
| 纯CLI依赖 | 新建.venv-cli，仅安装ATS/requirements-cli.txt；不需要Qt | 待现场 |
| 工具 | 记录Windows exe来源、版本、SHA256；-version及trace_headers支持；中文目录检测 | 待现场 |
| COM/驱动 | --list-ports与设备管理器一致；显式COM与自动EVB指纹；2Mbps持续RX/TX | 待现场 |
| 手动终端 | Enter/Tab/Backspace、Ctrl+C、exit；结束后Xcom或ATS可重开同口 | 待现场 |
| 拍照/录像 | cli_smoke_capture完成；核对完整命令、完成标志；photos/videos实际文件存在 | 待现场 |
| 主动FTP | 安全范围防火墙规则；数据回连、LIST/RETR；本地与远程长度一致，不仅看PASS | 待现场 |
| Windows本机RTMP | nginx -t接受rtmp配置；先本地publisher/ffprobe，再EVB→Windows | 待现场 |
| heartbeat失败 | 按测试条件触发停流/无心跳，观察FAIL与停止尝试，不误判稳定通过 | 待现场 |
| 可选预览 | 开/关预览不改变自动判据；同一时刻一个ffplay，断流重连、退出回收 | 待现场 |
| 中断/断连 | 拍摄、下载、探测、保持、检测期间分别Ctrl+C；已有报告保留；重开串口；停止未应答有警告 | 待现场 |
| 资源所有权 | ATS不结束外部nginx或用户其它ffplay；退出后无本次遗留工具进程 | 待现场 |

## 5. Ubuntu现场回归（待执行）

继续使用同一份源码、原虚拟环境与原配置。首先运行两个smoke场景，再复测normal及正式压力场景。
必须核对已有2Mbps串口链路、主动FTP、ffprobe与原有RTMP heartbeat行为。
预览有一个明确的部署变化：直接启动ffplay，不再额外开gnome-terminal/xterm；信息记录到preview.log。
Debian测试通过不能代替Ubuntu驱动、桌面、网络和EVB回归。

## 6. 已知限制与验收注意

- 包中不包含Windows FFmpeg/nginx-rtmp构建，也未验证任何特定Windows构建；服务器部署是现场前置条件。
- RTMP就绪仍为本机TCP1935可连接，不校验应用层握手；必须做真实发布/探测。
- 停止录像/推流是尽力清理；串口断开或板端卡死时不保证停止成功。记录警告，现场确认。
- RTMP正常停止ACK失败不改变原ffprobe/heartbeat主判据；preview_required仍非硬性失败开关。
- `--no-problem-prompt`仅跳过末尾问题记录；无人值守还应显式端口、配置Wi-Fi并加--no-interactive-wifi。
- 正式场景及用户自定义配置不被移植包改写；apply_patch遇到同路径额外修改时整包拒绝，需人工合并。
- 不附带旧UI热修复，不把本轮文件与feature/ats-ui-windows旧包混用。
