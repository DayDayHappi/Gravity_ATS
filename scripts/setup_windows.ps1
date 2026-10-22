# =============================================================================
# Gravity ATS — Windows 一键准备脚本（feature/windows-cli）
# =============================================================================
# 用途：在新 Windows 机器上准备运行 Gravity ATS CLI 所需的全部环境。
#   1) Python 检查/安装指引  2) 虚拟环境 + pip 依赖  3) ffmpeg 套件
#   4) 防火墙规则（FTP 主动模式，需管理员）  5) nginx-rtmp 1935 就绪检查
#   6) 本地敏感文件指引  7) 配置自检  8) 启动冒烟
#
# 用法：
#   普通（推荐，非管理员时自动请求提权以配置防火墙）:
#       powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
#   跳过管理员步骤（不配置防火墙）:
#       powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -SkipAdmin
#   仅检查不安装:
#       powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -CheckOnly
#   查看全部开关:
#       powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -?
#
# 设计约定：
#   - 幂等：重复运行不会重复安装/重复建规则。
#   - 失败处理：可自动修复的（pip/venv）→ 自动修复；需人工介入的（python 缺失、
#     ffmpeg 缺失、防火墙权限不足、敏感文件缺失）→ 记录到「待人工处理」列表，
#     最终汇总退出码（0=全部就绪，1=有环境/依赖错误，2=有警告，3=被用户中断）。
#   - 不擅自修改业务配置 system.yaml 的 WiFi/串口等值，只做存在性/语法自检。
#   - 提权：非管理员且未指定 -SkipAdmin 时，整体以管理员重跑一遍（含防火墙），
#     父进程等待子进程完成后直接退出，不重复执行。
# =============================================================================

[CmdletBinding()]
param(
    [switch]$SkipAdmin,   # 跳过所有需管理员的操作（不配置防火墙）
    [switch]$CheckOnly,   # 仅检查，不安装/不修改
    [switch]$NoFfmpeg     # 跳过 ffmpeg 安装（已自备或不需要）
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

# 显式声明 stdout 为 UTF-8：重定向/管道日志可读；Write-Host 在真实控制台仍按控制台渲染，不受影响。
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

# -----------------------------------------------------------------------------
# 路径与常量
# -----------------------------------------------------------------------------
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$ConfigFile  = Join-Path $ScriptDir 'setup_windows_config.json'
$VenvDir     = Join-Path $ProjectRoot '.venv-cli'
$VenvPython  = Join-Path $VenvDir 'Scripts\python.exe'

# 所有步骤都在项目根目录下执行，避免 -m ATS.main 找不到包 / 相对路径漂移。
Set-Location $ProjectRoot

$script:Problems = @()   # 需人工介入的项（error 级）
$script:Warnings = @()   # 警告（可降级/可选）

# -----------------------------------------------------------------------------
# 输出辅助
# -----------------------------------------------------------------------------
function Write-Step { param([string]$Text) Write-Host ("==> {0}" -f $Text) -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host ("    [OK]  {0}" -f $Text) -ForegroundColor Green }
function Write-Warn { param([string]$Text) Write-Host ("    [WARN] {0}" -f $Text) -ForegroundColor Yellow }
function Write-Fail { param([string]$Text) Write-Host ("    [FAIL] {0}" -f $Text) -ForegroundColor Red }
function Write-Info { param([string]$Text) Write-Host ("    [ .. ] {0}" -f $Text) -ForegroundColor Gray }

# -----------------------------------------------------------------------------
# 工具函数
# -----------------------------------------------------------------------------
function Test-Administrator {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $pr = New-Object Security.Principal.WindowsPrincipal($id)
    return $pr.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Test-CommandExists { param([string]$Name) return [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

function Load-Config {
    $cfg = $null
    if (Test-Path $ConfigFile) {
        try {
            $cfg = Get-Content -Raw -LiteralPath $ConfigFile | ConvertFrom-Json
        } catch {
            Write-Warn ("读取配置失败，使用内置默认值：{0}" -f $_.Exception.Message)
            $cfg = $null
        }
    }
    if (-not $cfg) {
        $cfg = [pscustomobject]@{
            python   = [pscustomobject]@{ launcher = 'py'; version_arg = '' }
            venv     = [pscustomobject]@{ name = '.venv-cli' }
            pip      = [pscustomobject]@{ packages = @('pyserial','PyYAML','Jinja2'); upgrade_pip = $true }
            ffmpeg   = [pscustomobject]@{ winget_id = 'Gyan.FFmpeg' }
            firewall = [pscustomobject]@{ rule_name = 'Gravity ATS CLI FTP - Board101'; remote_address = '192.168.1.0/24'; local_port = '1024-65535' }
            rtmp     = [pscustomobject]@{ port = 1935 }
            portal   = [pscustomobject]@{ token_file = 'upload.token'; cert_file = '.config\ats-portal\portal.crt' }
        }
    }
    return $cfg
}

function Resolve-PathRelative { param([string]$Relative) return (Join-Path $ProjectRoot $Relative) }

# 读取配置对象中的字符串；缺省回退默认值
function Get-CfgString { param($Section, [string]$Key, [string]$Default)
    if ($Section.PSObject.Properties.Name -contains $Key -and $Section.$Key) { return [string]$Section.$Key }
    return $Default
}

# -----------------------------------------------------------------------------
# 步骤实现
# -----------------------------------------------------------------------------

# 1) Python
function Step-Python {
    Write-Step '检查 Python'
    $launcher = Get-CfgString $config.python 'launcher' 'py'
    $verArg   = Get-CfgString $config.python 'version_arg' ''
    $havePy   = $false
    if (Test-CommandExists $launcher) {
        try {
            $out = & $launcher $verArg --version 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Ok ("Python 可用：{0}" -f ($out -join ' '))
                $havePy = $true
            }
        } catch { }
    }
    if (-not $havePy) {
        Write-Fail '未找到 Python。请从 https://www.python.org/downloads/ 安装 Python 3.13（勾选 Add to PATH）。'
        $script:Problems += 'Python 未安装（需人工安装后重跑本脚本）'
    }
}

# 2) 虚拟环境 + pip 依赖
function Step-Venv {
    Write-Step '虚拟环境与 Python 依赖'
    if (-not (Test-CommandExists 'py')) { Write-Warn 'py 启动器不存在，跳过 venv（需先装 Python）。'; return }
    if ($CheckOnly) {
        if (Test-Path $VenvPython) { Write-Ok '虚拟环境已存在：.venv-cli' }
        else { Write-Fail '虚拟环境不存在（运行不带 -CheckOnly 以创建）'; $script:Problems += '虚拟环境缺失' }
        return
    }
    if (-not (Test-Path $VenvPython)) {
        Write-Info '创建虚拟环境 .venv-cli ...'
        & py -3.13 -m venv $VenvDir
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPython)) {
            Write-Info '回退：尝试用默认 Python 创建 ...'
            & py -3 -m venv $VenvDir
        }
        if (-not (Test-Path $VenvPython)) {
            Write-Fail '虚拟环境创建失败。'
            $script:Problems += '虚拟环境创建失败（请确认 Python 3 已安装）'
            return
        }
        Write-Ok '虚拟环境已创建'
    } else {
        Write-Ok '虚拟环境已存在，跳过创建'
    }

    # pip 升级 + 依赖安装（失败自动重试一次）
    $pkgs = @($config.pip.packages)
    if ($config.pip.upgrade_pip) {
        Write-Info '升级 pip ...'
        & $VenvPython -m pip install --upgrade pip *> $null
    }
    Write-Info ("安装依赖：{0}" -f ($pkgs -join ', '))
    $installed = $false
    for ($attempt = 1; $attempt -le 2 -and -not $installed; $attempt++) {
        & $VenvPython -m pip install @pkgs
        if ($LASTEXITCODE -eq 0) { $installed = $true }
        else {
            Write-Warn ("pip 安装失败（第 {0} 次），重试 ..." -f $attempt)
            Start-Sleep -Seconds 2
        }
    }
    if ($installed) {
        Write-Ok 'Python 依赖安装完成'
        $impOk = & $VenvPython -c "import serial, yaml, jinja2; print('deps-ok')" 2>&1
        if ($impOk -match 'deps-ok') { Write-Ok '依赖 import 冒烟通过' }
        else { Write-Fail ("依赖 import 冒烟失败：{0}" -f ($impOk -join ' ')); $script:Problems += '依赖 import 冒烟失败' }
    } else {
        Write-Fail 'pip 安装失败（重试后仍失败，可能是网络/代理问题）'
        $script:Problems += 'pip 依赖安装失败'
    }
}

# 3) ffmpeg 套件
function Step-Ffmpeg {
    if ($NoFfmpeg) { Write-Warn '-NoFfmpeg 指定，跳过 ffmpeg 检查/安装。'; return }
    Write-Step '检查 ffmpeg / ffprobe / ffplay'
    $missing = @()
    foreach ($t in @('ffmpeg','ffprobe','ffplay')) {
        if (Test-CommandExists $t) { Write-Ok ("{0} 已在 PATH" -f $t) }
        else { $missing += $t }
    }
    if ($missing.Count -eq 0) { return }
    Write-Warn ("缺少：{0}" -f ($missing -join ', '))
    if ($CheckOnly) {
        $script:Problems += ("缺少 ffmpeg 套件：{0}" -f ($missing -join ', '))
        return
    }
    $wingetId = Get-CfgString $config.ffmpeg 'winget_id' 'Gyan.FFmpeg'
    if (-not (Test-CommandExists 'winget')) {
        Write-Fail '未找到 winget，无法自动安装 ffmpeg。'
        $script:Problems += 'ffmpeg 缺失且无 winget（请手动安装 Gyan.FFmpeg 或放入 tools\ffmpeg）'
        return
    }
    Write-Info ("通过 winget 安装 {0} ..." -f $wingetId)
    & winget install -e --id $wingetId --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) {
        Write-Fail 'winget 安装 ffmpeg 失败。'
        $script:Problems += 'ffmpeg 安装失败（需手动安装）'
    } else {
        Write-Warn 'ffmpeg 已安装，但可能需重开终端才在 PATH 生效。'
    }
}

# 4) 防火墙规则（FTP 主动模式）
function Step-Firewall {
    Write-Step '检查 Windows 防火墙规则（FTP 主动模式）'
    if (-not (Test-CommandExists 'Get-NetFirewallRule')) {
        Write-Warn '当前系统无 NetSecurity 模块，跳过防火墙。'
        return
    }
    $ruleName = Get-CfgString $config.firewall 'rule_name' 'Gravity ATS CLI FTP - Board101'
    $existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Ok ("防火墙规则已存在：{0}" -f $ruleName)
        Write-Info '若 FTP 仍超时，请确认该规则 RemoteAddress 为网段（如 192.168.1.0/24）而非单 IP。'
        return
    }
    if (-not (Test-Administrator)) {
        Write-Fail '配置防火墙需要管理员权限（未获得）。'
        $script:Problems += '防火墙规则未创建（需管理员权限）'
        return
    }
    if ($CheckOnly) { Write-Fail '防火墙规则不存在（运行不带 -CheckOnly 以创建）'; $script:Problems += '防火墙规则缺失'; return }
    $remote = Get-CfgString $config.firewall 'remote_address' '192.168.1.0/24'
    $lport  = Get-CfgString $config.firewall 'local_port' '1024-65535'
    try {
        New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
            -Protocol TCP -RemoteAddress $remote -LocalPort $lport | Out-Null
        Write-Ok ("已创建防火墙规则：{0}（RemoteAddress={1}, LocalPort={2}）" -f $ruleName, $remote, $lport)
    } catch {
        Write-Fail ("创建防火墙规则失败：{0}" -f $_.Exception.Message)
        $script:Problems += '防火墙规则创建失败'
    }
}

# 5) nginx-rtmp 1935 就绪检查
function Step-Rtmp {
    Write-Step '检查 RTMP 服务端（nginx-rtmp:1935）'
    $port = [int](Get-CfgString $config.rtmp 'port' '1935')
    $listening = $false
    try {
        $conn = Test-NetConnection -ComputerName 127.0.0.1 -Port $port -WarningAction SilentlyContinue
        if ($conn.TcpTestSucceeded) { $listening = $true }
    } catch { }
    if ($listening) { Write-Ok ("TCP {0} 已监听（nginx-rtmp 就绪）" -f $port) }
    else {
        Write-Warn ("TCP {0} 未监听。含 rtmp 的场景将跳过 preview（photo/video 判据不受影响）。" -f $port)
        Write-Info '如需 RTMP 测试，请手动安装 nginx-rtmp-win32 并监听 1935。'
        $script:Warnings += 'nginx-rtmp 1935 未就绪（RTMP 测试需手动部署）'
    }
}

# 6) 本地敏感文件指引
function Step-PortalFiles {
    Write-Step '检查本地敏感文件（Portal 上传，可选）'
    $token = Resolve-PathRelative (Get-CfgString $config.portal 'token_file' 'upload.token')
    $cert  = Resolve-PathRelative (Get-CfgString $config.portal 'cert_file' '.config\ats-portal\portal.crt')
    if (Test-Path $token) { Write-Ok ("token 文件存在：{0}" -f (Split-Path -Leaf $token)) }
    else { Write-Info '未找到 upload.token（若启用 Portal 上传，需从原机拷贝）。' }
    if (Test-Path $cert) { Write-Ok ("portal 证书存在：{0}" -f (Split-Path -Leaf $cert)) }
    else { Write-Info '未找到 portal.crt（Portal 自签证书，上传时才需要）。' }
}

# 7) 配置自检（只读，不修改）
function Step-ConfigCheck {
    Write-Step '配置自检（只读）'
    $sysYaml = Resolve-PathRelative 'ATS\config\system.yaml'
    if (Test-Path $sysYaml) {
        $chk = & $VenvPython -c "import yaml,sys; yaml.safe_load(open(sys.argv[1],encoding='utf-8')); print('yaml-ok')" $sysYaml 2>&1
        if ($LASTEXITCODE -eq 0 -and ($chk -join ' ') -match 'yaml-ok') { Write-Ok 'ATS/config/system.yaml 语法有效' }
        else { Write-Fail ("ATS/config/system.yaml 解析失败：{0}" -f ($chk -join ' ')); $script:Problems += 'system.yaml 语法错误' }
    } else { Write-Fail '缺少 ATS/config/system.yaml'; $script:Problems += 'system.yaml 缺失' }

    foreach ($d in @('ATS\config\modules', 'ATS\config\scenarios')) {
        $full = Resolve-PathRelative $d
        if (-not (Test-Path $full)) { Write-Fail ("缺少配置目录：{0}" -f $d); $script:Problems += ("配置目录缺失：{0}" -f (Split-Path -Leaf $d)) }
    }
}

# 8) 启动冒烟
function Step-Smoke {
    Write-Step '启动冒烟（--dry-run）'
    if (-not (Test-Path $VenvPython)) { Write-Fail '虚拟环境不存在，跳过冒烟。'; return }
    $out = & $VenvPython -m ATS.main --dry-run 2>&1 | Out-String
    Write-Host ($out.TrimEnd()) -ForegroundColor Gray
    if ($LASTEXITCODE -eq 0) { Write-Ok '--dry-run 通过（配置/契约/模块注册检查）' }
    else {
        Write-Fail ("--dry-run 返回退出码 {0}" -f $LASTEXITCODE)
        $script:Problems += '--dry-run 冒烟失败'
    }
}

# -----------------------------------------------------------------------------
# 汇总
# -----------------------------------------------------------------------------
function Show-Summary {
    Write-Host ''
    Write-Host '================ 准备结果汇总 ================' -ForegroundColor Cyan
    if ($script:Warnings.Count -gt 0) {
        Write-Host '警告（不影响核心 photo/video 测试，按需处理）：' -ForegroundColor Yellow
        $script:Warnings | ForEach-Object { Write-Host ("  - {0}" -f $_) -ForegroundColor Yellow }
    }
    if ($script:Problems.Count -gt 0) {
        Write-Host '待人工处理：' -ForegroundColor Red
        $script:Problems | ForEach-Object { Write-Host ("  - {0}" -f $_) -ForegroundColor Red }
    }
    if ($script:Problems.Count -eq 0 -and $script:Warnings.Count -eq 0) {
        Write-Host '全部就绪，可运行：' -ForegroundColor Green
        Write-Host '  .\.venv-cli\Scripts\python.exe -m ATS.main --scenario stress --no-interactive-wifi' -ForegroundColor Green
    } elseif ($script:Problems.Count -eq 0) {
        Write-Host '核心环境就绪（存在可选警告，见上）。' -ForegroundColor Green
    }
    Write-Host '=============================================' -ForegroundColor Cyan
}

# -----------------------------------------------------------------------------
# 主流程
# -----------------------------------------------------------------------------
try {
    $config = Load-Config

    Write-Host ''
    Write-Host 'Gravity ATS — Windows 一键准备（feature/windows-cli）' -ForegroundColor Magenta
    Write-Host ('项目根目录：{0}' -f $ProjectRoot)
    Write-Host ('管理员权限：{0}' -f (Test-Administrator))
    Write-Host ''

    # 提权：非管理员且未跳过时，整体以管理员重跑一遍，父进程等待后直接退出。
    if (-not (Test-Administrator) -and -not $SkipAdmin) {
        Write-Warn '检测到非管理员运行，为配置防火墙将请求提权重跑本脚本……'
        $argList = @('-NoProfile','-ExecutionPolicy','Bypass','-File', $MyInvocation.MyCommand.Path, '-SkipAdmin')
        if ($CheckOnly) { $argList += '-CheckOnly' }
        if ($NoFfmpeg)  { $argList += '-NoFfmpeg' }
        try {
            $proc = Start-Process powershell -Verb RunAs -PassThru -Wait -ArgumentList $argList
            exit $proc.ExitCode
        } catch {
            Write-Fail ("提权失败，继续以当前权限执行（防火墙将跳过）：{0}" -f $_.Exception.Message)
            $script:Problems += '防火墙规则未创建（无法提权）'
        }
    }

    Step-Python
    Step-Venv
    Step-Ffmpeg
    Step-Firewall
    Step-Rtmp
    Step-PortalFiles
    Step-ConfigCheck
    Step-Smoke

    Show-Summary

    if ($script:Problems.Count -gt 0) { exit 1 }
    elseif ($script:Warnings.Count -gt 0) { exit 2 }
    else { exit 0 }
}
catch {
    Write-Host '' -ForegroundColor Red
    Write-Host ('脚本异常终止：{0}' -f $_.Exception.Message) -ForegroundColor Red
    Write-Host ($_.ScriptStackTrace) -ForegroundColor DarkRed
    exit 3
}
