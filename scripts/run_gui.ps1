[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Missing .venv. Run: python -m venv .venv; .\.venv\Scripts\python -m pip install -r requirements-gui.txt"
}

& ".venv\Scripts\python.exe" -m ATS.gui
exit $LASTEXITCODE
