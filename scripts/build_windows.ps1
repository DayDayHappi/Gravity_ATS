[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$BuildInstaller,
    [string]$InnoCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Missing .venv Python: $Python" }

foreach ($tool in @("ffmpeg.exe", "ffprobe.exe", "ffplay.exe")) {
    $path = Join-Path $ProjectRoot "runtime\ffmpeg\$tool"
    if (-not (Test-Path $path)) {
        throw "Missing bundled runtime tool: $path. Run scripts\prepare_runtime.ps1 first."
    }
}

if (-not $SkipTests) {
    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
}

Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
& $Python -m PyInstaller --clean --noconfirm "packaging\gravity_ats.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$Exe = Join-Path $ProjectRoot "dist\GravityATS\GravityATS.exe"
if (-not (Test-Path $Exe)) { throw "Expected executable was not produced: $Exe" }
Write-Host "Onedir build complete: $Exe"

if ($BuildInstaller) {
    if (-not (Test-Path $InnoCompiler)) { throw "Inno Setup compiler not found: $InnoCompiler" }
    & $InnoCompiler "packaging\GravityATS.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed" }
    Write-Host "Installer output: $ProjectRoot\installer_output"
}
