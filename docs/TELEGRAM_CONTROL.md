# Telegram Control

ViralForge can run as a private Telegram bot so you can trigger and monitor automation from your phone.

## What The Bot Can Do

- `/discover` - show current tech trend candidates.
- `/plan [topic]` - generate script, metadata, compliance package only.
- `/run [topic]` - render a private video package.
- `/run_upload [topic]` - render and upload through linked YouTube OAuth.
- `/upload_latest` - upload the latest rendered package.
- `/status` - show recent automation runs.
- `/id` - show the chat ID for allowlisting.

## Create The Telegram Bot

1. Open Telegram.
2. Message `@BotFather`.
3. Send `/newbot`.
4. Choose a name and username.
5. Copy the bot token.
6. Paste it in `.env`:

```ini
TELEGRAM_BOT_TOKEN=123456789:your_token_here
TELEGRAM_ALLOWED_CHAT_IDS=
```

## Find Your Chat ID

Start the bot locally:

```powershell
.\.venv\Scripts\viralforge telegram-bot
```

Open your bot in Telegram and send:

```text
/id
```

The bot replies with a number. Put it in `.env`:

```ini
TELEGRAM_ALLOWED_CHAT_IDS=123456789
```

Restart the bot. Now only that chat can run commands.

Until `TELEGRAM_ALLOWED_CHAT_IDS` is set, only `/id`, `/start`, and `/help` are allowed. Render/upload commands stay locked.

For multiple users:

```ini
TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321
```

## Run Locally

```powershell
.\scripts\run_telegram_bot.ps1
```

Your laptop must stay on for this local bot to respond.

## Run 24/7 On A VPS

Copy the systemd service:

```bash
sudo cp /opt/viralforge/deploy/systemd/viralforge-telegram-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now viralforge-telegram-bot.service
```

Check logs:

```bash
journalctl -u viralforge-telegram-bot.service -n 100 --no-pager
```

The bot uses Telegram long polling, so it does not need a public webhook URL.

## Safe Defaults

Keep YouTube uploads private first:

```ini
YOUTUBE_PRIVACY_STATUS=private
```

Use `/run` for private video creation and manual review. Use `/run_upload` only after YouTube OAuth is linked and you trust the output.
