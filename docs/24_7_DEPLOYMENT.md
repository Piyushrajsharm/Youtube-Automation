# ViralForge 24/7 Deployment

Your laptop cannot run ViralForge while it is fully shut down. For true 24/7 automation, run it on an always-on machine:

- A cloud VPS, recommended.
- A rented Windows server.
- A home mini PC/NAS that stays powered on.
- GitHub Actions for light plan generation only, not recommended for heavy renders or secrets-heavy upload workflows.

## Recommended Setup: Linux VPS + Docker

Pick a VPS with at least:

- 4 vCPU
- 8 GB RAM
- 80 GB disk
- Ubuntu 22.04 or 24.04

Install Docker:

```bash
sudo apt update
sudo apt install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

Log out and back in, then put the project at:

```bash
sudo mkdir -p /opt/viralforge
sudo chown -R $USER:$USER /opt/viralforge
cd /opt/viralforge
```

Copy this project folder to `/opt/viralforge`, including:

- `src/`
- `assets/`
- `config/`
- `deploy/`
- `Dockerfile`
- `pyproject.toml`
- `requirements.txt`
- `.env`
- `credentials/client_secret.json`
- `credentials/youtube_token.json` after OAuth linking

Build and test:

```bash
cd /opt/viralforge
docker compose -f deploy/docker-compose.yml build
docker compose -f deploy/docker-compose.yml run --rm viralforge viralforge autopilot --no-render
```

Run one real private upload:

```bash
docker compose -f deploy/docker-compose.yml run --rm viralforge viralforge autopilot --upload
```

## Daily 24/7 Schedule

Copy the systemd files:

```bash
sudo cp /opt/viralforge/deploy/systemd/viralforge-autopilot.service /etc/systemd/system/
sudo cp /opt/viralforge/deploy/systemd/viralforge-autopilot.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now viralforge-autopilot.timer
```

Check status:

```bash
systemctl list-timers | grep viralforge
systemctl status viralforge-autopilot.timer
journalctl -u viralforge-autopilot.service -n 100 --no-pager
```

The included service uploads by default. If you want private package generation only, edit:

```text
/etc/systemd/system/viralforge-autopilot.service
```

Change:

```bash
viralforge autopilot --upload
```

to:

```bash
viralforge autopilot
```

Then reload:

```bash
sudo systemctl daemon-reload
sudo systemctl restart viralforge-autopilot.timer
```

## 24/7 Telegram Control

After setting `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_CHAT_IDS` in `.env`, run the Telegram control bot as a service:

```bash
sudo cp /opt/viralforge/deploy/systemd/viralforge-telegram-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now viralforge-telegram-bot.service
```

Now you can trigger `/discover`, `/plan`, `/run`, `/run_upload`, and `/status` from Telegram while your laptop is shut down.

See `docs/TELEGRAM_CONTROL.md` for setup details.

For production, prefer the separate secure bot:

```bash
sudo cp /opt/viralforge/deploy/systemd/viralforge-secure-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now viralforge-secure-bot.service
```

That bot uses `TELEGRAM_OWNER_CHAT_IDS`, roles, queued jobs, upload approval, rate limits, and audit logs. See `docs/SECURE_BOT.md`.

## YouTube OAuth On A Server

OAuth is easiest on your laptop first:

1. Put `credentials/client_secret.json` in this project locally.
2. Run `viralforge youtube-auth`.
3. Sign in to the correct YouTube channel account.
4. Confirm `credentials/youtube_token.json` was created.
5. Copy both JSON files to the VPS `credentials/` folder.

Do not commit either JSON file.

## Recommended Safety Defaults

Keep these in `.env` until you trust the whole pipeline:

```ini
YOUTUBE_PRIVACY_STATUS=private
YOUTUBE_UPLOAD_ENABLED=false
YOUTUBE_SELF_DECLARED_MADE_FOR_KIDS=false
YOUTUBE_CONTAINS_SYNTHETIC_MEDIA=true
```

Use `--upload` only when you want the automated run to send the video to YouTube.
