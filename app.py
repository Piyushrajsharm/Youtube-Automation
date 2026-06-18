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
from fastapi.responses import HTMLResponse

from viralforge.config import load_settings, load_strategy
from viralforge.secure_bot import OWNER, SecureTelegramBot
from viralforge.youtube import youtube_token_status


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
    # Check YouTube token health
    yt_token_health: dict[str, Any] | None = None
    try:
        settings = load_settings()
        yt_token_health = youtube_token_status(settings)
    except Exception:
        yt_token_health = {"error": "Could not load settings to check token."}
    return {
        "status": "running" if thread_alive and not _bot_last_error else "degraded" if thread_alive else "starting",
        "service": "viralforge-huggingface-space",
        "space_id": os.getenv("SPACE_ID", ""),
        "bot_thread_alive": thread_alive,
        "bot_started_at": _bot_started_at,
        "last_error": _bot_last_error,
        "youtube_client_secret_configured": bool(os.getenv("YOUTUBE_CLIENT_SECRETS") or os.getenv("YOUTUBE_CLIENT_SECRETS_JSON")),
        "youtube_token_configured": bool(os.getenv("YOUTUBE_TOKEN_FILE") or os.getenv("YOUTUBE_TOKEN_JSON")),
        "youtube_token_health": yt_token_health,
        "telegram_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "nvidia_configured": bool(os.getenv("NVIDIA_API_KEY") or os.getenv("NVIDIA_SD35_API_KEY")),
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


def _require_admin_secret(request: Request) -> None:
    expected_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    received_secret = request.headers.get("X-ViralForge-Admin-Secret", "")
    if not expected_secret or received_secret != expected_secret:
        raise HTTPException(status_code=403, detail="Invalid admin secret.")


def _bot_or_503() -> SecureTelegramBot:
    with _bot_lock:
        bot = _bot
    if bot is None:
        raise HTTPException(status_code=503, detail="Bot is not ready.")
    return bot


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("ViralForge Space booting. Launching secure bot supervisor.", flush=True)
    _start_bot_once()
    yield
    print("ViralForge Space shutting down.", flush=True)


app = FastAPI(title="ViralForge Secure Control", lifespan=lifespan)


HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ViralForge Bot Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #090d16;
            --panel: rgba(15, 23, 42, 0.7);
            --border: rgba(255, 255, 255, 0.08);
            --primary: #8b5cf6;
            --primary-glow: rgba(139, 92, 246, 0.4);
            --accent: #06b6d4;
            --accent-glow: rgba(6, 182, 212, 0.4);
            --text: #f3f4f6;
            --text-dim: #94a3b8;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg);
            color: var(--text);
            min-height: 100vh;
            background-image: 
                radial-gradient(circle at 10% 20%, rgba(139, 92, 246, 0.08) 0%, transparent 40%),
                radial-gradient(circle at 90% 80%, rgba(6, 182, 212, 0.08) 0%, transparent 40%);
            background-attachment: fixed;
            padding: 2rem;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2.5rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border);
        }

        h1 {
            font-size: 2.2rem;
            font-weight: 800;
            background: linear-gradient(to right, #a78bfa, #22d3ee);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.5px;
        }

        .auth-box {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            background: var(--panel);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border);
            padding: 0.5rem 1rem;
            border-radius: 9999px;
        }

        .auth-box input {
            background: transparent;
            border: none;
            color: var(--text);
            font-family: inherit;
            outline: none;
            width: 180px;
            font-size: 0.9rem;
        }

        .grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 2rem;
        }

        @media (max-width: 900px) {
            .grid {
                grid-template-columns: 1fr;
            }
        }

        .card {
            background: var(--panel);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 1.75rem;
            margin-bottom: 2rem;
            box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.5);
            transition: transform 0.2s ease, border-color 0.2s ease;
        }

        .card:hover {
            border-color: rgba(255, 255, 255, 0.15);
        }

        .card-title {
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 1.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            padding-bottom: 0.75rem;
        }

        .btn {
            font-family: inherit;
            font-weight: 600;
            padding: 0.75rem 1.5rem;
            border-radius: 8px;
            border: none;
            cursor: pointer;
            transition: all 0.2s ease;
            font-size: 0.95rem;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
        }

        .btn-primary {
            background: var(--primary);
            color: var(--text);
            box-shadow: 0 4px 14px var(--primary-glow);
        }

        .btn-primary:hover {
            background: #7c3aed;
            box-shadow: 0 6px 20px var(--primary-glow);
            transform: translateY(-1px);
        }

        .btn-accent {
            background: var(--accent);
            color: #0f172a;
            box-shadow: 0 4px 14px var(--accent-glow);
        }

        .btn-accent:hover {
            background: #0891b2;
            box-shadow: 0 6px 20px var(--accent-glow);
            transform: translateY(-1px);
        }

        .btn:active {
            transform: translateY(1px);
        }

        /* Health Grid */
        .health-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: 1rem;
        }

        .health-item {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 10px;
            padding: 1rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .health-label {
            font-size: 0.9rem;
            color: var(--text-dim);
        }

        .health-status {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-weight: 600;
            font-size: 0.9rem;
        }

        .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            display: inline-block;
        }

        .dot-green { background: var(--success); box-shadow: 0 0 8px var(--success); }
        .dot-red { background: var(--danger); box-shadow: 0 0 8px var(--danger); }
        .dot-yellow { background: var(--warning); box-shadow: 0 0 8px var(--warning); }

        /* Forms */
        .form-group {
            margin-bottom: 1.25rem;
        }

        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            font-size: 0.9rem;
            color: var(--text-dim);
        }

        .form-group input, .form-group select {
            width: 100%;
            padding: 0.75rem 1rem;
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid var(--border);
            border-radius: 8px;
            color: var(--text);
            font-family: inherit;
            outline: none;
            font-size: 0.95rem;
            transition: border-color 0.2s;
        }

        .form-group input:focus, .form-group select:focus {
            border-color: var(--primary);
        }

        .flex-row {
            display: flex;
            gap: 1rem;
            align-items: flex-end;
        }

        /* Jobs list */
        .job-card {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.04);
            border-radius: 12px;
            padding: 1.25rem;
            margin-bottom: 1rem;
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
        }

        .job-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .job-id {
            font-family: monospace;
            font-size: 0.95rem;
            background: rgba(255, 255, 255, 0.08);
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            color: var(--accent);
        }

        .job-badge {
            font-size: 0.8rem;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-weight: 600;
            text-transform: uppercase;
        }

        .badge-queued { background: rgba(156, 163, 175, 0.15); color: #9ca3af; }
        .badge-running { background: rgba(59, 130, 246, 0.15); color: #3b82f6; }
        .badge-cloud_rendering { background: rgba(139, 92, 246, 0.15); color: #8b5cf6; }
        .badge-completed { background: rgba(16, 185, 129, 0.15); color: #10b981; }
        .badge-uploaded { background: rgba(6, 182, 212, 0.15); color: #06b6d4; }
        .badge-failed { background: rgba(239, 68, 68, 0.15); color: #ef4444; }

        .job-topic {
            font-weight: 600;
            font-size: 1.05rem;
        }

        .job-info {
            display: flex;
            flex-wrap: wrap;
            gap: 1.5rem;
            font-size: 0.85rem;
            color: var(--text-dim);
        }

        .job-error {
            color: var(--danger);
            font-size: 0.85rem;
            background: rgba(239, 68, 68, 0.08);
            padding: 0.5rem;
            border-radius: 6px;
            border-left: 3px solid var(--danger);
            margin-top: 0.25rem;
        }

        .job-url a {
            color: var(--accent);
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
        }

        .job-url a:hover {
            text-decoration: underline;
        }

        /* Toast notification */
        .toast {
            position: fixed;
            bottom: 2rem;
            right: 2rem;
            background: rgba(15, 23, 42, 0.95);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border);
            padding: 1rem 1.5rem;
            border-radius: 8px;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.3);
            display: flex;
            align-items: center;
            gap: 0.75rem;
            transform: translateY(150%);
            transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1);
            z-index: 9999;
        }

        .toast.show {
            transform: translateY(0);
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>ViralForge</h1>
                <p style="color: var(--text-dim); font-size: 0.9rem; margin-top: 0.25rem;">Automated Video Production & Upload Engine</p>
            </div>
            <div class="auth-box">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--text-dim);"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
                <input type="password" id="adminSecret" placeholder="Admin Secret Key" onchange="saveSecret()">
            </div>
        </header>

        <div class="grid">
            <div class="main-column">
                <!-- System Health Card -->
                <div class="card">
                    <div class="card-title">System Health Status</div>
                    <div class="health-grid" id="healthGrid">
                        <div style="color: var(--text-dim);">Loading health...</div>
                    </div>
                </div>

                <!-- Recent Jobs Card -->
                <div class="card">
                    <div class="card-title">Recent Jobs</div>
                    <div id="jobsList">
                        <div style="color: var(--text-dim); text-align: center; padding: 2rem;">Loading jobs...</div>
                    </div>
                </div>
            </div>

            <div class="side-column">
                <!-- Direct Controls Card -->
                <div class="card">
                    <div class="card-title">Manual Creation Trigger</div>
                    <div class="form-group">
                        <label for="manualTopic">Explicit Topic (Optional)</label>
                        <input type="text" id="manualTopic" placeholder="e.g. Future of Quantum Computing">
                    </div>
                    <button class="btn btn-primary" style="width: 100%;" onclick="triggerManualJob()">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                        Queue Render & Upload
                    </button>
                </div>

                <!-- Autopilot Controls Card -->
                <div class="card">
                    <div class="card-title">Autopilot Scheduler</div>
                    <div class="form-group">
                        <label for="autopilotEnabled">Autopilot Status</label>
                        <select id="autopilotEnabled" onchange="updateAutopilotSettings()">
                            <option value="true">Enabled (Active)</option>
                            <option value="false">Disabled (Paused)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="autopilotInterval">Interval (Hours)</label>
                        <select id="autopilotInterval" onchange="updateAutopilotSettings()">
                            <option value="4">Every 4 Hours</option>
                            <option value="8">Every 8 Hours</option>
                            <option value="12">Every 12 Hours</option>
                            <option value="24">Every 24 Hours</option>
                        </select>
                    </div>
                    <button class="btn btn-accent" style="width: 100%; margin-top: 0.5rem;" onclick="runAutopilotNow()">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"></path></svg>
                        Trigger Autopilot Now
                    </button>
                </div>
            </div>
        </div>
    </div>

    <div class="toast" id="toast">
        <span id="toastMsg">Action completed!</span>
    </div>

    <script>
        // Load secret from localStorage on startup
        document.getElementById('adminSecret').value = localStorage.getItem('vf_admin_secret') || '';

        function saveSecret() {
            const secret = document.getElementById('adminSecret').value;
            localStorage.setItem('vf_admin_secret', secret);
            showToast('Secret key saved locally.');
            refreshData();
        }

        function getHeaders() {
            const secret = document.getElementById('adminSecret').value.trim();
            return {
                'Content-Type': 'application/json',
                'X-ViralForge-Admin-Secret': secret
            };
        }

        function showToast(msg, isError = false) {
            const toast = document.getElementById('toast');
            const toastMsg = document.getElementById('toastMsg');
            toastMsg.innerText = msg;
            toast.style.borderColor = isError ? 'var(--danger)' : 'var(--border)';
            toast.classList.add('show');
            setTimeout(() => {
                toast.classList.remove('show');
            }, 3000);
        }

        async function fetchHealth() {
            try {
                const resp = await fetch('/health');
                const data = await resp.json();
                
                const grid = document.getElementById('healthGrid');
                grid.innerHTML = '';

                // Helper to render health rows
                const addHealthRow = (label, isTrue, valText = '') => {
                    const statusClass = isTrue ? 'dot-green' : 'dot-red';
                    const text = valText || (isTrue ? 'Ready' : 'Not Configured');
                    grid.innerHTML += `
                        <div class="health-item">
                            <span class="health-label">${label}</span>
                            <span class="health-status">
                                <span class="dot ${statusClass}"></span>
                                ${text}
                            </span>
                        </div>
                    `;
                };

                addHealthRow('System Status', data.status === 'running', data.status.toUpperCase());
                addHealthRow('Bot Engine Thread', data.bot_thread_alive);
                
                const ytHealth = data.youtube_token_health || {};
                const ytOk = ytHealth.token_file_exists && !ytHealth.error;
                addHealthRow('YouTube Upload OAuth', ytOk, ytOk ? 'Authorized (Permanent)' : 'Expired/Error');

                addHealthRow('NVIDIA GenAI API', data.nvidia_configured);
                addHealthRow('Pexels Stock API', data.pexels_configured);
                addHealthRow('Telegram Webhook', data.telegram_webhook_configured);
            } catch (err) {
                console.error(err);
            }
        }

        async function fetchJobs() {
            const secret = document.getElementById('adminSecret').value.trim();
            if (!secret) {
                document.getElementById('jobsList').innerHTML = `
                    <div style="color: var(--warning); text-align: center; padding: 2rem; font-weight: 600;">
                        ⚠️ Enter your Admin Secret Key above to load jobs & autopilot state.
                    </div>
                `;
                return;
            }

            try {
                const resp = await fetch('/control/jobs', {
                    headers: getHeaders()
                });
                if (resp.status === 403) {
                    document.getElementById('jobsList').innerHTML = `
                        <div style="color: var(--danger); text-align: center; padding: 2rem; font-weight: 600;">
                            ❌ Invalid Admin Secret Key. Access Denied.
                        </div>
                    `;
                    return;
                }
                const data = await resp.json();
                
                // Update autopilot form values if they aren't focused
                if (document.activeElement !== document.getElementById('autopilotEnabled')) {
                    document.getElementById('autopilotEnabled').value = String(data.autopilot);
                }
                if (document.activeElement !== document.getElementById('autopilotInterval')) {
                    document.getElementById('autopilotInterval').value = String(data.autopilot_interval_hours);
                }

                // Render jobs list
                const list = document.getElementById('jobsList');
                if (!data.jobs || data.jobs.length === 0) {
                    list.innerHTML = `<div style="color: var(--text-dim); text-align: center; padding: 2rem;">No jobs registered yet.</div>`;
                    return;
                }

                list.innerHTML = '';
                data.jobs.forEach(job => {
                    let infoHtml = `
                        <div class="job-info">
                            <span>Type: <strong>${job.type}</strong></span>
                            <span>Created: ${new Date(job.created_at).toLocaleString()}</span>
                            ${job.finished_at ? `<span>Finished: ${new Date(job.finished_at).toLocaleString()}</span>` : ''}
                        </div>
                    `;

                    if (job.upload_url) {
                        infoHtml += `
                            <div class="job-url" style="margin-top: 0.5rem; font-size: 0.9rem;">
                                🎥 <a href="${job.upload_url}" target="_blank">Watch on YouTube: ${job.title || 'Video'}</a>
                            </div>
                        `;
                    }

                    if (job.error) {
                        infoHtml += `<div class="job-error">${job.error}</div>`;
                    }

                    list.innerHTML += `
                        <div class="job-card">
                            <div class="job-header">
                                <span class="job-id">${job.id}</span>
                                <span class="job-badge badge-${job.status}">${job.status}</span>
                            </div>
                            <div class="job-topic">${job.topic || 'Auto Selection'}</div>
                            ${infoHtml}
                        </div>
                    `;
                });
            } catch (err) {
                console.error(err);
            }
        }

        async function triggerManualJob() {
            const topic = document.getElementById('manualTopic').value.trim();
            try {
                const resp = await fetch('/control/render-upload', {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({ topic: topic })
                });
                if (resp.ok) {
                    showToast('Job queued successfully!');
                    document.getElementById('manualTopic').value = '';
                    refreshData();
                } else {
                    const err = await resp.text();
                    showToast('Failed to queue job: ' + err, true);
                }
            } catch (err) {
                showToast('Network error: ' + err, true);
            }
        }

        async function updateAutopilotSettings() {
            const enabled = document.getElementById('autopilotEnabled').value === 'true';
            const interval = parseFloat(document.getElementById('autopilotInterval').value);
            try {
                const resp = await fetch('/control/autopilot', {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({ enabled: enabled, interval_hours: interval })
                });
                if (resp.ok) {
                    showToast('Autopilot settings updated!');
                    refreshData();
                } else {
                    showToast('Failed to update autopilot', true);
                }
            } catch (err) {
                showToast('Network error: ' + err, true);
            }
        }

        async function runAutopilotNow() {
            const enabled = document.getElementById('autopilotEnabled').value === 'true';
            const interval = parseFloat(document.getElementById('autopilotInterval').value);
            try {
                const resp = await fetch('/control/autopilot', {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({ enabled: enabled, interval_hours: interval, run_now: true })
                });
                if (resp.ok) {
                    showToast('Autopilot run triggered immediately!');
                    refreshData();
                } else {
                    showToast('Failed to trigger autopilot', true);
                }
            } catch (err) {
                showToast('Network error: ' + err, true);
            }
        }

        function refreshData() {
            fetchHealth();
            fetchJobs();
        }

        // Initial load and periodic refresh
        refreshData();
        setInterval(refreshData, 10000);
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def root():
    return HTML_CONTENT


@app.get("/health")
def health() -> dict[str, Any]:
    return _health_payload()


@app.get("/control/jobs")
def control_jobs(request: Request) -> dict[str, Any]:
    _require_admin_secret(request)
    bot = _bot_or_503()
    state = bot.store.load()
    return {
        "jobs": bot.store.recent_jobs(12),
        "usage": state.get("usage", {}),
        "autopilot": bool(state.get("autopilot")),
        "autopilot_interval_hours": state.get("autopilot_interval_hours"),
        "last_autopilot_time": state.get("last_autopilot_time"),
        "queue_size": bot.jobs.qsize(),
    }


@app.get("/control/test-jobs")
def control_test_jobs() -> dict[str, Any]:
    bot = _bot_or_503()
    return {
        "jobs": bot.store.recent_jobs(12),
        "queue_size": bot.jobs.qsize(),
    }


@app.get("/control/git-runs")
def control_git_runs() -> dict[str, Any]:
    bot = _bot_or_503()
    token = bot.settings.github_token
    repo = bot.settings.github_repo
    url = f"https://api.github.com/repos/{repo}/actions/runs?per_page=5"
    headers = {
        "Authorization": f"token {token}" if token else "",
        "User-Agent": "FastAPI"
    }
    try:
        import requests
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            runs = []
            for run in data.get("workflow_runs", []):
                runs.append({
                    "id": run.get("id"),
                    "name": run.get("name"),
                    "status": run.get("status"),
                    "conclusion": run.get("conclusion"),
                    "event": run.get("event"),
                    "html_url": run.get("html_url"),
                    "created_at": run.get("created_at"),
                })
            return {"ok": True, "runs": runs}
        else:
            return {"ok": False, "status_code": r.status_code, "text": r.text}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/control/test-dispatch")
def control_test_dispatch() -> dict[str, Any]:
    bot = _bot_or_503()
    token = bot.settings.github_token
    repo = bot.settings.github_repo
    url = f"https://api.github.com/repos/{repo}/dispatches"
    headers = {
        "Authorization": f"token {token}" if token else "",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "FastAPI"
    }
    payload = {
        "event_type": "render_video",
        "client_payload": {
            "topic": "Test Topic",
            "plan_json": {}
        }
    }
    try:
        import requests
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        return {
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
            "text": resp.text
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/control/render-upload")
async def control_render_upload(request: Request) -> dict[str, Any]:
    _require_admin_secret(request)
    bot = _bot_or_503()
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    topic = str(payload.get("topic") or "").strip()
    owner_id = int(bot.settings.telegram_owner_chat_ids[0]) if bot.settings.telegram_owner_chat_ids else 0
    job = bot.store.create_job(job_type="render_upload", topic=topic, chat_id=owner_id, role=OWNER)
    bot.jobs.put(job["id"])
    print(f"Direct control queued render_upload job {job['id']} topic={topic or 'auto trend'}", flush=True)
    return {"ok": True, "job": job}


@app.get("/control/test-trigger")
def control_test_trigger(topic: str = "Future of Quantum Computing") -> dict[str, Any]:
    bot = _bot_or_503()
    owner_id = int(bot.settings.telegram_owner_chat_ids[0]) if bot.settings.telegram_owner_chat_ids else 0
    job = bot.store.create_job(job_type="render_upload", topic=topic, chat_id=owner_id, role=OWNER)
    bot.jobs.put(job["id"])
    print(f"Test trigger queued render_upload job {job['id']} topic={topic}", flush=True)
    return {"ok": True, "job": job}


@app.post("/control/autopilot")
async def control_autopilot(request: Request) -> dict[str, Any]:
    _require_admin_secret(request)
    bot = _bot_or_503()
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    enabled = bool(payload.get("enabled", True))
    interval_hours = float(payload.get("interval_hours") or bot.store.load().get("autopilot_interval_hours", 4))
    run_now = bool(payload.get("run_now", False))
    state = bot.store.load()
    state["autopilot"] = enabled
    state["autopilot_interval_hours"] = max(0.25, interval_hours)
    if enabled and run_now:
        state["last_autopilot_time"] = 0.0
    bot.store.save(state)
    print(
        f"Direct control set autopilot enabled={enabled} interval={state['autopilot_interval_hours']} run_now={run_now}",
        flush=True,
    )
    return {
        "ok": True,
        "autopilot": bool(state.get("autopilot")),
        "autopilot_interval_hours": state.get("autopilot_interval_hours"),
        "last_autopilot_time": state.get("last_autopilot_time"),
    }


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
