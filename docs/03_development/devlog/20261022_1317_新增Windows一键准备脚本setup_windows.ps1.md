# 20261022_1317_新增Windows一键准备脚本setup_windows.ps1

## 问题描述

`feature/windows-cli` 分支要部署到另一台 Windows 电脑，此前环境准备全靠 `docs/05_handoff/windows_cli_启动指南.md` 里的人工清单（装 Python、建 venv、pip 依赖、ffmpeg、防火墙规则、nginx-rtmp、拷贝敏感文件、改配置）。步骤多且易漏，尤其防火墙规则历史上已因错配/网段写死复发两次（devlog `20260920_1600`、`20261019`），急需一个可重复执行、带失败处理的一键准备入口。

## 根因分析

环境准备涉及多种异构动作：需要下载安装的（Python、pip 包、ffmpeg）、需要管理员权限的（防火墙规则）、只能靠人工的（EVB 串口驱动、敏感文件拷贝、WiFi 凭据）。此前无统一入口，靠人肉核对，出错代价高（FTP 主动模式超时导致 photo 每项卡 ~68s）。

## 修复内容

新增两个文件（`scripts/` 目录，属 Code Agent 交付物，不进 git 忽略范围）：

1. `scripts/setup_windows.ps1` —— 一键准备脚本，8 个步骤 + 失败处理 + 退出码汇总：
   - 步骤：①Python 检查 ②虚拟环境 + pip 依赖 ③ffmpeg 套件 ④防火墙规则 ⑤nginx-rtmp 1935 就绪检查 ⑥本地敏感文件（upload.token / portal.crt）检查 ⑦配置自检（system.yaml 语法 + modules/scenarios 目录存在性，只读不写）⑧`--dry-run` 启动冒烟。
   - 失败处理：可自动修复的（venv/pip 安装失败自动重试一次；Python 3.13 不可用回退默认版本）→ 自动修复；需人工介入的（Python 缺失、ffmpeg 无 winget、防火墙无法提权、敏感文件缺失）→ 记入「待人工处理」列表，不在中途中断。
   - 退出码：`0` 全部就绪 / `1` 有环境或依赖错误 / `2` 有警告（如 RTMP 未就绪，不影响 photo/video）/ `3` 脚本异常或用户中断。
   - 提权：非管理员且未 `-SkipAdmin` 时整体以管理员重跑一遍（含防火墙），父进程等待子进程后 `exit $proc.ExitCode` 直接退出，不重复执行。
   - 参数：`-SkipAdmin`（跳过管理员步骤）、`-CheckOnly`（仅检查不安装）、`-NoFfmpeg`（跳过 ffmpeg）、`-?`（帮助）。
   - 幂等：重复运行不会重复建 venv/装依赖/建防火墙规则；已存在的防火墙规则只提示复核网段、不覆盖用户手工调整。

2. `scripts/setup_windows_config.json` —— 默认配置（Python 启动器、venv 名、pip 包清单、ffmpeg winget id、防火墙规则名/网段/端口、RTMP 端口、portal 敏感文件相对路径）。缺省时脚本用内置默认值兜底。

关键设计：
- 脚本所有步骤 `Set-Location $ProjectRoot` 后执行，`-m ATS.main` 和相对路径（token/cert/yaml）不会随 cwd 漂移。
- 显式 `[Console]::OutputEncoding = UTF8`，重定向/管道日志中文可读。
- 文件以 UTF-8 BOM 保存（PowerShell 5.1 无 BOM 会按 GBK 解析中文致语法错误），行尾 CRLF。
- 防火墙 `RemoteAddress` 默认网段 `192.168.1.0/24`（遵守环境红线，禁止写死单 IP）。
- 不改业务配置 `system.yaml` 的串口/WiFi/pc.ip 等值，只做只读自检。

## Files

- `scripts/setup_windows.ps1`（新增）
- `scripts/setup_windows_config.json`（新增）

## Verification

- `System.Management.Automation.Language.Parser::ParseFile` 语法解析通过（SYNTAX OK）。
- 本机 `-CheckOnly -SkipAdmin` 只读冒烟跑通：Python 3.13.15 / venv 已存在 / ffmpeg 三件套 PATH 命中 / 防火墙规则已存在 / RTMP 1935 未监听(WARN) / token 存在、portal.crt 缺失(提示) / system.yaml 语法有效 / `--dry-run` 通过，最终退出码 `2`（有 RTMP 警告），符合设计。

## Known limitation

- ffmpeg 经 winget 安装后 PATH 需重开终端才生效；`-CheckOnly` 模式首跑若 venv 尚不存在，本脚本也会建（幂等，实际无副作用）。
- EVB USB 转串口驱动、nginx-rtmp-win32 安装（文档 TODO-CONFIRM 未记录安装源）仍属人工步骤，脚本只做提示/就绪检查，不代为安装。
- 测试范围仅本机只读冒烟；真实新机器（无 Python/无 venv/需提权建防火墙）的完整链路待真机验证。
