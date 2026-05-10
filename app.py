import os
import threading
import time
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn
from src.viralforge.config import load_settings
from src.viralforge.secure_bot import SecureTelegramBot

print("Application is initializing...", flush=True)

def run_bot():
    print("Bot thread is alive and initializing settings...", flush=True)
    try:
        settings = load_settings()
        bot = SecureTelegramBot(settings)
        bot.run_forever()
    except Exception as e:
        print(f"BOT CRASHED: {e}", flush=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("FastAPI Lifespan started. Launching bot thread...", flush=True)
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    yield
    print("FastAPI Lifespan shutting down...", flush=True)

app = FastAPI(lifespan=lifespan)

@app.get("/")
def health_check():
    return {"status": "alive", "message": "ViralForge Hugging Face Space is running"}

if __name__ == "__main__":
    print("Starting Uvicorn server...", flush=True)
    uvicorn.run("app:app", host="0.0.0.0", port=7860, log_level="info")

