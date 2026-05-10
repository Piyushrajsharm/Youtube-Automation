param(
  [string]$TaskName = "ViralForge Autopilot",
  [string]$DailyTime = "09:00",
  [switch]$Upload
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$script = Join-Path $root "scripts\run_autopilot.ps1"
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$script`""

if ($Upload) {
  $arguments += " -Upload"
}

$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument $arguments `
  -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Daily -At $DailyTime

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Description "Creates one ViralForge tech Short package per day. Uploads only when -Upload is set and YouTube OAuth is configured." `
  -Force

Write-Host "Installed scheduled task '$TaskName' at $DailyTime."
