from __future__ import annotations

import os
import threading
import time
import traceback
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from viralforge.config import load_settings, load_strategy
from viralforge.secure_bot import SecureTelegramBot


BOT_RESTART_DELAY_SECONDS = 30

_bot_lock = threading.Lock()
_bot_thread: threading.Thread | None = None
_bot_started_at: str | None = None
_bot_last_error: str | None = None
_bot: SecureTelegramBot | None = None


def _write_json_secret(secret_name: str, path_env_name: str, filename: str) -> None:
    value = os.getenv(secret_name, "").strip()
    if not value or os.getenv(path_env_name):
        return

    credentials_dir = Path(os.getenv("VIRALFORGE_CREDENTIALS_DIR", "/tmp/viralforge_credentials"))
    credentials_dir.mkdir(parents=True, exist_ok=True)
    target = credentials_dir / filename
    target.write_text(value, encoding="utf-8")
    os.environ[path_env_name] = str(target)


def _prepare_space_environment() -> None:
    _write_json_secret("YOUTUBE_CLIENT_SECRETS_JSON", "YOUTUBE_CLIENT_SECRETS", "client_secret.json")
    _write_json_secret("YOUTUBE_TOKEN_JSON", "YOUTUBE_TOKEN_FILE", "youtube_token.json")


def _run_bot_supervisor() -> None:
    global _bot, _bot_last_error, _bot_started_at
    while True:
        bot: SecureTelegramBot | None = None
        try:
            _prepare_space_environment()
            settings = load_settings()
            strategy = load_strategy(settings)
            bot = SecureTelegramBot(settings, strategy)
            bot.start_background_workers(notify_owners=False)
            with _bot_lock:
                _bot = bot
            _bot_started_at = datetime.now(UTC).isoformat()
            _bot_last_error = None
            print("ViralForge secure Telegram webhook bot started inside Hugging Face Space.", flush=True)
            while True:
                time.sleep(3600)
        except Exception as exc:
            _bot_last_error = f"{type(exc).__name__}: {exc}"
            print("ViralForge bot supervisor caught an error:", _bot_last_error, flush=True)
            print(traceback.format_exc(), flush=True)
        finally:
            with _bot_lock:
                if _bot is bot:
                    _bot = None
            if bot is not None:
                bot.close()
        time.sleep(BOT_RESTART_DELAY_SECONDS)


def _start_bot_once() -> None:
    global _bot_thread
    with _bot_lock:
        if _bot_thread and _bot_thread.is_alive():
            return
        _bot_thread = threading.Thread(target=_run_bot_supervisor, name="viralforge-secure-bot", daemon=True)
        _bot_thread.start()


def _health_payload() -> dict[str, Any]:
    thread_alive = bool(_bot_thread and _bot_thread.is_alive())
    return {
        "status": "running" if thread_alive and not _bot_last_error else "degraded" if thread_alive else "starting",
        "service": "viralforge-huggingface-space",
        "space_id": os.getenv("SPACE_ID", ""),
        "bot_thread_alive": thread_alive,
        "bot_started_at": _bot_started_at,
        "last_error": _bot_last_error,
        "youtube_client_secret_configured": bool(os.getenv("YOUTUBE_CLIENT_SECRETS") or os.getenv("YOUTUBE_CLIENT_SECRETS_JSON")),
        "youtube_token_configured": bool(os.getenv("YOUTUBE_TOKEN_FILE") or os.getenv("YOUTUBE_TOKEN_JSON")),
        "telegram_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "nvidia_configured": bool(os.getenv("NVIDIA_API_KEY")),
        "pexels_configured": bool(os.getenv("PEXELS_API_KEY")),
        "telegram_webhook_configured": bool(os.getenv("TELEGRAM_WEBHOOK_SECRET")),
    }


def _handle_telegram_update(update: dict[str, Any]) -> None:
    with _bot_lock:
        bot = _bot
    if bot is None:
        print("Telegram webhook update received before bot was ready.", flush=True)
        return
    try:
        bot.handle_update(update)
    except Exception as exc:
        print(f"Telegram webhook handler failed: {type(exc).__name__}: {exc}", flush=True)
        print(traceback.format_exc(), flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("ViralForge Space booting. Launching secure bot supervisor.", flush=True)
    _start_bot_once()
    yield
    print("ViralForge Space shutting down.", flush=True)


app = FastAPI(title="ViralForge Secure Control", lifespan=lifespan)


@app.get("/")
def root() -> dict[str, Any]:
    return _health_payload()


@app.get("/health")
def health() -> dict[str, Any]:
    return _health_payload()


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict[str, bool]:
    expected_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if not expected_secret:
        raise HTTPException(status_code=404, detail="Telegram webhook is not configured.")
    received_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if received_secret != expected_secret:
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret.")

    update = await request.json()
    threading.Thread(target=_handle_telegram_update, args=(update,), daemon=True).start()
    return {"ok": True}
