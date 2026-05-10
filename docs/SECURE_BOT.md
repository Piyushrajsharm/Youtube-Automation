# Secure ViralForge Bot

This is the advanced separate Telegram bot for controlling ViralForge safely from your phone.

It is different from the lightweight `telegram-bot` command. Use this for production.

## Security Model

- Separate CLI command: `viralforge secure-bot`.
- Owner/admin/viewer roles.
- No render/upload commands work until `TELEGRAM_OWNER_CHAT_IDS` is set.
- Uploads require owner approval.
- Inline approve/deny buttons for upload jobs.
- Daily render and upload limits.
- Persistent job state at `outputs/secure_bot_state.json`.
- JSON audit trail at `outputs/secure_bot_audit.jsonl`.
- Secrets are not printed in bot messages or audit events.

## Roles

Owner:

- Can render, approve uploads, deny uploads, upload latest, cancel queued jobs, view config.

Admin:

- Can discover, plan, and render private packages.
- Cannot upload.

Viewer:

- Can inspect status, health, trends, and jobs.
- Cannot render or upload.

Guest:

- Can only use `/id`, `/start`, and `/help`.

## Environment

Add this to `.env`:

```ini
TELEGRAM_BOT_TOKEN=
TELEGRAM_OWNER_CHAT_IDS=
TELEGRAM_ADMIN_CHAT_IDS=
TELEGRAM_ALLOWED_CHAT_IDS=
TELEGRAM_POLL_TIMEOUT=25
TELEGRAM_SEND_VIDEO_MAX_MB=45
SECURE_BOT_MAX_DAILY_RENDERS=6
SECURE_BOT_MAX_DAILY_UPLOADS=3
SECURE_BOT_REQUIRE_UPLOAD_APPROVAL=true
```

Use `TELEGRAM_OWNER_CHAT_IDS` for your own Telegram chat ID.

## Setup

1. Create a Telegram bot with `@BotFather`.
2. Paste the token into `.env` as `TELEGRAM_BOT_TOKEN`.
3. Start the bot:

```powershell
.\.venv\Scripts\viralforge secure-bot
```

4. Send `/id` to the bot in Telegram.
5. Copy the chat ID into `.env`:

```ini
TELEGRAM_OWNER_CHAT_IDS=123456789
```

6. Restart the bot.

## Commands

Read commands:

```text
/discover
/status
/jobs
/job <id>
/health
/whoami
/id
```

Admin commands:

```text
/plan [topic]
/render [topic]
```

Owner commands:

```text
/render_upload [topic]
/approve <job_id>
/deny <job_id>
/upload_latest
/cancel <job_id>
/config
```

## Recommended Workflow

Create a video package:

```text
/render gadget quiz
```

Review the rendered output locally or from the output path.

Render and prepare an upload:

```text
/render_upload cybersecurity news
```

The bot will render first, then ask for approval. Tap **Approve Upload** or send:

```text
/approve abc123def0
```

## Run Locally

```powershell
.\scripts\run_secure_bot.ps1
```

Your laptop must stay on for local operation.

## Run 24/7 On A VPS

```bash
sudo cp /opt/viralforge/deploy/systemd/viralforge-secure-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now viralforge-secure-bot.service
```

Logs:

```bash
journalctl -u viralforge-secure-bot.service -n 100 --no-pager
```

## YouTube Requirement

For upload commands, YouTube OAuth must already be linked:

- `credentials/client_secret.json`
- `credentials/youtube_token.json`

Keep `.env` private and keep uploads private first:

```ini
YOUTUBE_PRIVACY_STATUS=private
```
