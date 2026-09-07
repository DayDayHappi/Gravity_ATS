[CmdletBinding()]
param(
    [string]$FfmpegBin = "",
    [string]$NginxRoot = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Runtime = Join-Path $ProjectRoot "runtime"
$FfmpegTarget = Join-Path $Runtime "ffmpeg"
New-Item -ItemType Directory -Force -Path $FfmpegTarget | Out-Null

$tools = @("ffmpeg.exe", "ffprobe.exe", "ffplay.exe")
foreach ($tool in $tools) {
    if ($FfmpegBin) {
        $source = Join-Path $FfmpegBin $tool
    } else {
        $command = Get-Command $tool -ErrorAction SilentlyContinue
        $source = if ($command) { $command.Source } else { "" }
    }
    if (-not $source -or -not (Test-Path $source)) {
        throw "Cannot locate $tool. Supply -FfmpegBin <directory>."
    }
    Copy-Item -Force $source (Join-Path $FfmpegTarget $tool)
}

if ($NginxRoot) {
    if (-not (Test-Path (Join-Path $NginxRoot "nginx.exe"))) {
        throw "NginxRoot does not contain nginx.exe: $NginxRoot"
    }
    $NginxTarget = Join-Path $Runtime "nginx"
    if (Test-Path $NginxTarget) { Remove-Item -Recurse -Force $NginxTarget }
    Copy-Item -Recurse -Force $NginxRoot $NginxTarget
}

Write-Host "Runtime prepared at $Runtime"
Write-Host "Keep the corresponding FFmpeg/nginx license notices with the redistributed binaries."
