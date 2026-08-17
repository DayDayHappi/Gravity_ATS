#!/usr/bin/env bash
# migrate.sh — 在新 Ubuntu PC 上初始化 VX100 EVB 自动化测试环境
#
# 作用：自动检查/装好运行 ATS 所需的依赖，校验内置工具与配置，
#       并跑一遍 dry-run 确认环境就绪。可重复运行（幂等）。
# 不会做的：不替你执行 sudo 命令（串口权限、防火墙需交互密码），
#           只在最后打印出来让你手动跑。
#
# 用法：  ./migrate.sh            # 执行迁移检查
#         ./migrate.sh --help     # 帮助
# 详见：  迁移指南.md

set -u

# 项目根目录 = 脚本所在目录（不依赖当前 cwd）
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || { echo "无法进入项目根目录 $ROOT"; exit 1; }

# 颜色输出
G="\033[32m"; Y="\033[33m"; R="\033[31m"; D="\033[2m"; B="\033[1m"; N="\033[0m"
ok()    { printf "${G}✓${N} %s\n" "$1"; }
warn()  { printf "${Y}!${N} %s\n" "$1"; }
fail()  { printf "${R}✗${N} %s\n" "$1"; }
title() { printf "\n${B}=== %s ===${N}\n" "$1"; }

# 计数
PASS=0; WARN=0; FAIL=0

# sudo 待办命令收集（最后统一打印）
SUDO_CMDS=()

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    sed -n '2,12p' "$0"
    exit 0
fi

printf "${B}VX100 EVB 自动化测试 — 环境迁移初始化${N}\n"
printf "项目目录: ${D}%s${N}\n\n" "$ROOT"

# ---------- 1. Python 版本 ----------
title "1/8 检查 Python 版本 (需 3.7+)"
if command -v python3 >/dev/null 2>&1; then
    PYVER="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)"
    PYOK="$(python3 -c 'import sys;print(1 if sys.version_info[:2]>=(3,7) else 0)' 2>/dev/null)"
    if [ "$PYOK" = "1" ]; then
        ok "Python $PYVER"; PASS=$((PASS+1))
    else
        fail "Python 版本 <3.7 (检测到: ${PYVER:-未知})，请升级"; FAIL=$((FAIL+1))
    fi
else
    fail "未找到 python3，请先安装：sudo apt install python3 python3-pip"; FAIL=$((FAIL+1))
fi

# ---------- 2. Python 依赖 ----------
title "2/8 安装/检查 Python 依赖 (pyserial, pyyaml)"
if python3 -c 'import serial, yaml' 2>/dev/null; then
    ok "pyserial + pyyaml 已安装"; PASS=$((PASS+1))
else
    printf "  ${D}尝试 pip3 install --user ...${N}\n"
    if pip3 install --user pyserial pyyaml >/tmp/ats_pip.log 2>&1; then
        ok "安装成功 (--user)"; PASS=$((PASS+1))
    elif pip3 install pyserial pyyaml >/tmp/ats_pip.log 2>&1; then
        ok "安装成功"; PASS=$((PASS+1))
    else
        fail "pip 安装失败"; WARN=$((WARN+1))
        if grep -qi "externally-managed" /tmp/ats_pip.log 2>/dev/null; then
            warn "系统受 PEP 668 限制(externally-managed-environment)。二选一："
            printf "  ${D}A) 推荐 venv:${N}\n"
            printf "     python3 -m venv .venv && source .venv/bin/activate && pip install pyserial pyyaml\n"
            printf "     # 之后用 .venv/bin/python3 -m ATS.main 跑测试\n"
            printf "  ${D}B) 强装系统:${N}\n"
            printf "     pip3 install --break-system-packages --user pyserial pyyaml\n"
        else
            printf "  ${D}pip 日志:${N}\n"; tail -5 /tmp/ats_pip.log
        fi
    fi
fi

# ---------- 3. 内置二进制工具 + nginx-rtmp 服务端 ----------
title "3/8 检查内置二进制工具 (ffmpeg/ffprobe/ffplay) + nginx-rtmp 服务端"
BIN_OK=1
for f in tools/ffmpeg/ffmpeg tools/ffmpeg/ffprobe tools/ffmpeg/ffplay; do
    if [ -x "$f" ]; then
        ok "$f"
    elif [ -f "$f" ]; then
        warn "$f 存在但无执行权限，尝试 chmod +x"
        chmod +x "$f" && ok "$f (已加执行权限)" || { fail "$f chmod 失败"; BIN_OK=0; }
    else
        fail "$f 缺失（打包迁移时漏了？）"; BIN_OK=0
    fi
done
# nginx-rtmp 服务端就绪检查（nginx 由用户/系统手动启动，脚本不替你启停）
if command -v nginx >/dev/null 2>&1; then
    if nginx -t 2>&1 | grep -q "syntax is ok"; then
        if ss -tln 2>/dev/null | grep -q ":1935 "; then
            ok "nginx-rtmp 已启动，1935 监听中"; PASS=$((PASS+1))
        else
            warn "nginx 已安装且配置语法 OK，但 1935 未监听——nginx-rtmp 未启动"
            printf "  ${D}请手动启动: systemctl start nginx (或 nginx 命令)${N}\n"
            WARN=$((WARN+1))
        fi
    else
        warn "nginx 已安装但配置语法检查未通过（或非 root 权限受限）"
        WARN=$((WARN+1))
    fi
else
    fail "未找到 nginx——RTMP 推流测试需要 nginx-rtmp 服务端"
    printf "  ${D}安装: sudo apt install nginx libnginx-mod-rtmp${N}\n"
    printf "  ${D}配置: /etc/nginx/rtmp.conf 加 application live { live on; record off; } 监听 1935${N}\n"
    WARN=$((WARN+1))
fi
if [ "$BIN_OK" = "1" ]; then PASS=$((PASS+1)); else WARN=$((WARN+1)); fi

# ---------- 4. 串口权限 (dialout 组) ----------
title "4/8 检查串口权限 (dialout 组)"
if id -nG 2>/dev/null | tr ' ' '\n' | grep -qx dialout; then
    ok "当前用户在 dialout 组"; PASS=$((PASS+1))
else
    warn "当前用户不在 dialout 组，打开 /dev/ttyUSB* 会失败"
    SUDO_CMDS+=("sudo usermod -aG dialout \$USER   # 加组后需注销重新登录生效")
    WARN=$((WARN+1))
fi

# ---------- 5. 串口设备 ----------
title "5/8 检查串口设备 (/dev/ttyUSB*)"
DEVS="$(ls /dev/ttyUSB* 2>/dev/null)"
if [ -n "$DEVS" ]; then
    ok "发现串口设备: $(echo $DEVS | tr '\n' ' ')"
    # 检查能否读写
    if [ -r /dev/ttyUSB0 ] && [ -w /dev/ttyUSB0 ]; then
        ok "/dev/ttyUSB0 可读写"; PASS=$((PASS+1))
    else
        warn "/dev/ttyUSB0 权限不足（需 dialout 组或临时 chmod）"
        SUDO_CMDS+=("sudo chmod 666 /dev/ttyUSB*   # 临时放开权限（重启失效）")
        WARN=$((WARN+1))
    fi
else
    warn "未发现 /dev/ttyUSB*（EVB 可能未连接/未上电/驱动未加载）"
    printf "  ${D}确认: 1) EVB 已上电 2) USB 线接好 3) lsusb 看 FT2232 是否识别${N}\n"
    printf "  ${D}驱动: Ubuntu 一般自带 ftdi_sio，可 lsmod | grep ftdi 确认${N}\n"
    WARN=$((WARN+1))
fi

# ---------- 6. 防火墙 (需要 sudo，仅打印命令) ----------
title "6/8 防火墙 (RTMP/FTP 需放行高端口)"
if command -v ufw >/dev/null 2>&1; then
    printf "  ${D}ufw 已安装。状态需 sudo 查看，无法自动检测。${N}\n"
    printf "  ${D}RTMP(1935)/FTP数据端口都在 1024-65535 段，放行即可：${N}\n"
    SUDO_CMDS+=("sudo ufw status                      # 查看当前规则")
    SUDO_CMDS+=("sudo ufw allow 1024:65535/tcp        # 放行高端口(推荐)")
    SUDO_CMDS+=("# 或测试期间直接关: sudo ufw disable")
    ok "已给出防火墙配置命令"; PASS=$((PASS+1))
else
    ok "未装 ufw，默认无防火墙拦截"; PASS=$((PASS+1))
fi

# ---------- 7. dry-run 校验 ----------
title "7/8 dry-run 校验 (配置 + 依赖，不连板子)"
DRY="$(python3 -m ATS.main --dry-run 2>&1)"
if echo "$DRY" | grep -q "配置与依赖校验通过"; then
    ok "dry-run 通过"; PASS=$((PASS+1))
else
    fail "dry-run 未通过"; WARN=$((WARN+1))
    echo "$DRY" | tail -8 | sed 's/^/    /'
fi

# ---------- 8. 列模块 ----------
title "8/8 列出已注册模块"
MODS="$(python3 -m ATS.main --list-modules 2>&1)"
if echo "$MODS" | grep -q "可用模块"; then
    ok "模块加载正常"; PASS=$((PASS+1))
    echo "$MODS" | grep -E "wifi|emmc|ftp|photo|video|rtmp" | sed 's/^/    /'
else
    fail "模块加载失败"; WARN=$((WARN+1))
    echo "$MODS" | tail -8 | sed 's/^/    /'
fi

# ---------- 汇总 ----------
printf "\n${B}══════════ 迁移检查汇总 ══════════${N}\n"
printf "  ${G}通过 %d${N}  ${Y}注意 %d${N}  ${R}失败 %d${N}\n\n" "$PASS" "$WARN" "$FAIL"

if [ ${#SUDO_CMDS[@]} -gt 0 ]; then
    printf "${Y}以下命令需要 sudo，请手动执行：${N}\n"
    for c in "${SUDO_CMDS[@]}"; do printf "  ${D}%s${N}\n" "$c"; done
    printf "\n"
fi

if [ "$FAIL" -gt 0 ]; then
    fail "有致命项未通过，请先解决上面 ✗ 的项再继续"
    exit 2
elif [ "$WARN" -gt 0 ]; then
    warn "基本就绪，但有需注意项（! 标记）。解决后可跑测试"
    printf "\n${B}下一步：${N}\n"
    printf "  1) 执行上面的 sudo 命令（串口权限/防火墙）\n"
    printf "  2) 连好 EVB，确认 ${D}ls /dev/ttyUSB*${N} 有输出\n"
    printf "  3) 跑核心通路: ${D}python3 -m ATS.main --no-interactive-wifi --skip rtmp${N}\n"
    printf "  4) 含 RTMP 完整测试: ${D}python3 -m ATS.main --no-interactive-wifi${N}\n"
    exit 1
else
    ok "环境就绪！可开始测试"
    printf "\n${B}下一步：${N}\n"
    printf "  1) 连好 EVB，确认 ${D}ls /dev/ttyUSB*${N} 有输出\n"
    printf "  2) 跑核心通路: ${D}python3 -m ATS.main --no-interactive-wifi --skip rtmp${N}\n"
    printf "  3) 含 RTMP 完整测试: ${D}python3 -m ATS.main --no-interactive-wifi${N}\n"
    printf "  4) RTMP 手动调试: 确保 nginx-rtmp 已启动(${D}systemctl start nginx${N})\n"
    printf "     另开终端: ${D}python3 -m ATS.main --terminal${N} 发推流命令\n"
    exit 0
fi
