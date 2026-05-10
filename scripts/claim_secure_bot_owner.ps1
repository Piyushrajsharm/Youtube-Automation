param(
  [int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$envPath = Join-Path $root ".env"

function Get-EnvValue {
  param([string]$Path, [string]$Name)
  $line = Select-String -Path $Path -Pattern "^$([regex]::Escape($Name))=" -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $line) { return "" }
  return (($line.Line -split "=", 2)[1]).Trim()
}

function Set-EnvValue {
  param([string]$Path, [string]$Name, [string]$Value)
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

if (-not (Test-Path $envPath)) {
  throw "Missing .env at $envPath"
}

$token = Get-EnvValue -Path $envPath -Name "TELEGRAM_BOT_TOKEN"
if ([string]::IsNullOrWhiteSpace($token)) {
  throw "TELEGRAM_BOT_TOKEN is missing in .env"
}

$me = Invoke-RestMethod -Method Get -Uri "https://api.telegram.org/bot$token/getMe"
if (-not $me.ok) {
  throw "Telegram rejected the bot token."
}

$username = $me.result.username
Write-Host "Bot detected: @$username"
Write-Host "Opening the bot chat. Press Start if Telegram shows it, then send: /id"
Start-Process "tg://resolve?domain=$username"

Invoke-RestMethod -Method Post -Uri "https://api.telegram.org/bot$token/deleteWebhook" -Body @{ drop_pending_updates = "false" } | Out-Null

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$offset = 0
while ((Get-Date) -lt $deadline) {
  $updates = Invoke-RestMethod -Method Post -Uri "https://api.telegram.org/bot$token/getUpdates" -Body @{
    timeout = 5
    offset = $offset
    allowed_updates = '["message"]'
  }

  foreach ($update in $updates.result) {
    $offset = [Math]::Max($offset, [int]$update.update_id + 1)
    if ($null -eq $update.message -or $null -eq $update.message.chat) {
      continue
    }
    $chatId = [string]$update.message.chat.id
    $text = [string]$update.message.text
    if ($text -eq "/id" -or $text -eq "/start") {
      Set-EnvValue -Path $envPath -Name "TELEGRAM_OWNER_CHAT_IDS" -Value $chatId
      Invoke-RestMethod -Method Post -Uri "https://api.telegram.org/bot$token/getUpdates" -Body @{ offset = $offset } | Out-Null
      Write-Host "Owner chat ID saved: $chatId"
      Write-Host "Now start the secure bot:"
      Write-Host "cd D:\Automation"
      Write-Host ".\.venv\Scripts\viralforge secure-bot"
      exit 0
    }
  }
  Write-Host "Waiting for /id in @$username..."
}

throw "Timed out. Open @$username in Telegram, press Start, send /id, then run this script again."
