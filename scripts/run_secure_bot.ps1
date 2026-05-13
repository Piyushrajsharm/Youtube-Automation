param()

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

$env:PYTHONPATH = Join-Path $root "src"
.\.venv\Scripts\python.exe -m viralforge.cli secure-bot
