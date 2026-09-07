[CmdletBinding()]
param(
    [string]$Port = "COM10",
    [int]$Baudrate = 2000000,
    [switch]$RunNormal,
    [switch]$RunReleaseSmoke,
    [string]$GoodH265 = "",
    [string]$BadH265 = "",
    [string]$EvidenceDir = "windows_acceptance_evidence"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Missing .venv Python: $Python" }
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$Transcript = Join-Path $EvidenceDir ("acceptance-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
Start-Transcript -Path $Transcript | Out-Null

try {
    Write-Host "== Static and automated tests =="
    & $Python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "pytest failed" }

    Write-Host "== CLI discovery =="
    & $Python -m ATS.main --list-scenarios
    if ($LASTEXITCODE -ne 0) { throw "--list-scenarios failed" }
    & $Python -m ATS.main --list-modules
    if ($LASTEXITCODE -ne 0) { throw "--list-modules failed" }

    Write-Host "== Configuration/dependency checks =="
    & $Python -m ATS.main --scenario normal --port $Port --baudrate $Baudrate --dry-run
    if ($LASTEXITCODE -ne 0) { throw "normal --dry-run failed" }
    & $Python -m ATS.main --scenario release_smoke --port $Port --baudrate $Baudrate --dry-run
    if ($LASTEXITCODE -ne 0) { throw "release_smoke --dry-run failed" }

    Write-Host "== Serial identity =="
    & $Python -m ATS.tools.windows_probe --port $Port --baudrate $Baudrate --json-out (Join-Path $EvidenceDir "serial-probe.json")
    if ($LASTEXITCODE -ne 0) { throw "serial probe failed" }

    if ($RunNormal) {
        Write-Host "== Real EVB normal =="
        & $Python -m ATS.main --scenario normal --port $Port --baudrate $Baudrate --no-interactive-wifi
        if ($LASTEXITCODE -ne 0) { throw "--scenario normal failed" }
    }

    if ($RunReleaseSmoke) {
        Write-Host "== Real EVB Phase 7 smoke =="
        & $Python -m ATS.main --scenario release_smoke --port $Port --baudrate $Baudrate --no-interactive-wifi
        if ($LASTEXITCODE -ne 0) { throw "--scenario release_smoke failed" }
    }

    if ($GoodH265) {
        Write-Host "== H265 expected PASS (Unicode/space-safe argv) =="
        & $Python -m ATS.tools.h265_acceptance --file $GoodH265 --expect PASS --json-out (Join-Path $EvidenceDir "h265-good.json")
        if ($LASTEXITCODE -ne 0) { throw "Known-good H265 acceptance failed" }
    }
    if ($BadH265) {
        Write-Host "== H265 expected FAIL (Unicode/space-safe argv) =="
        & $Python -m ATS.tools.h265_acceptance --file $BadH265 --expect FAIL --json-out (Join-Path $EvidenceDir "h265-bad.json")
        if ($LASTEXITCODE -ne 0) { throw "Known-bad H265 acceptance failed" }
    }

    $reports = Get-ChildItem -Path $ProjectRoot -Recurse -Filter result.json -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 10 FullName, LastWriteTime
    $reports | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $EvidenceDir "recent-result-json.json")
    Write-Host "Acceptance commands completed. Evidence: $EvidenceDir"
}
finally {
    Stop-Transcript | Out-Null
}
