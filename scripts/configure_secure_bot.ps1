param()

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$envPath = Join-Path $root ".env"

if (-not (Test-Path $envPath)) {
  Copy-Item (Join-Path $root ".env.example") $envPath
}

function Set-EnvValue {
  param(
    [string]$Path,
    [string]$Name,
    [string]$Value
  )

  $escapedName = [regex]::Escape($Name)
  $line = "$Name=$Value"

  if (Select-String -Path $Path -Pattern "^$escapedName=" -Quiet) {
    $content = Get-Content -Path $Path
    $content = $content | ForEach-Object {
      if ($_ -match "^$escapedName=") { $line } else { $_ }
    }
    Set-Content -Path $Path -Value $content -Encoding UTF8
  } else {
    Add-Content -Path $Path -Value $line -Encoding UTF8
  }
}

Write-Host ""
Write-Host "ViralForge secure Telegram bot configuration"
Write-Host "Do not paste your bot token into chat. Paste it only into this terminal."
Write-Host ""

$token = Read-Host "Paste TELEGRAM_BOT_TOKEN from BotFather"
if ([string]::IsNullOrWhiteSpace($token)) {
  throw "Token is required."
}

$owner = Read-Host "Paste your Telegram Chat ID, or press Enter to fill it after running /id"

Set-EnvValue -Path $envPath -Name "TELEGRAM_BOT_TOKEN" -Value $token.Trim()
if (-not [string]::IsNullOrWhiteSpace($owner)) {
  Set-EnvValue -Path $envPath -Name "TELEGRAM_OWNER_CHAT_IDS" -Value $owner.Trim()
}

Set-EnvValue -Path $envPath -Name "SECURE_BOT_REQUIRE_UPLOAD_APPROVAL" -Value "true"
Set-EnvValue -Path $envPath -Name "SECURE_BOT_MAX_DAILY_RENDERS" -Value "6"
Set-EnvValue -Path $envPath -Name "SECURE_BOT_MAX_DAILY_UPLOADS" -Value "3"

Write-Host ""
Write-Host "Saved secure bot settings to $envPath"
if ([string]::IsNullOrWhiteSpace($owner)) {
  Write-Host "Next: run .\.venv\Scripts\viralforge secure-bot, send /id to your bot, then add that ID to TELEGRAM_OWNER_CHAT_IDS."
} else {
  Write-Host "Next: run .\.venv\Scripts\viralforge secure-bot"
}
