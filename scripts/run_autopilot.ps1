param(
  [int]$Count = 1,
  [double]$IntervalMinutes = 0,
  [switch]$Upload,
  [switch]$NoRender
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

$argsList = @(
  "autopilot",
  "--count", $Count,
  "--interval-minutes", $IntervalMinutes
)

if ($Upload) {
  $argsList += "--upload"
}

if ($NoRender) {
  $argsList += "--no-render"
}

.\.venv\Scripts\viralforge @argsList
