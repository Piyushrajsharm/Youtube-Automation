from __future__ import annotations

import json
import queue
import socket
import threading
import time
import uuid
import concurrent.futures
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from .automation import run_once, upload_existing_package
from .config import Settings, load_strategy
from .trends import collect_trends
from .utils import ensure_dir, read_json, write_json, extract_json_object
from .llm import NvidiaChatClient


OWNER = "owner"
ADMIN = "admin"
VIEWER = "viewer"
GUEST = "guest"

READ_COMMANDS = {"/start", "/help", "/id", "/whoami", "/status", "/jobs", "/job", "/discover", "/health"}
ADMIN_COMMANDS = {"/plan", "/render"}
OWNER_COMMANDS = {"/render_upload", "/approve", "/deny", "/upload_latest", "/cancel", "/config", "/autopilot"}


class SecureBotError(RuntimeError):
    pass


class SecureBotStore:
    def __init__(self, output_dir: Path) -> None:
        self.state_path = output_dir / "secure_bot_state.json"
        self.audit_path = output_dir / "secure_bot_audit.jsonl"
        ensure_dir(output_dir)
        self._lock = threading.RLock()
        if not self.state_path.exists():
            write_json(self.state_path, {"jobs": [], "usage": {}, "locked": False})

    def load(self) -> dict[str, Any]:
        with self._lock:
            try:
                data = read_json(self.state_path)
            except Exception:
                data = {"jobs": [], "usage": {}, "locked": False}
            data.setdefault("jobs", [])
            data.setdefault("usage", {})
            data.setdefault("locked", False)
            data.setdefault("autopilot", False)
            data.setdefault("autopilot_interval_hours", 4)
            data.setdefault("last_autopilot_time", 0.0)
            return data

    def save(self, state: dict[str, Any]) -> None:
        with self._lock:
            write_json(self.state_path, state)

    def create_job(self, *, job_type: str, topic: str, chat_id: int, role: str) -> dict[str, Any]:
        job = {
            "id": uuid.uuid4().hex[:10],
            "type": job_type,
            "topic": topic,
            "status": "queued",
            "requested_by": chat_id,
            "requested_role": role,
            "created_at": _now_iso(),
            "started_at": None,
            "finished_at": None,
            "output_dir": None,
            "video_path": None,
            "metadata_path": None,
            "title": None,
            "hashtags": [],
            "error": None,
            "upload_url": None,
            "approved_by": None,
        }
        state = self.load()
        state["jobs"].insert(0, job)
        state["jobs"] = state["jobs"][:100]
        self.save(state)
        return job

    def update_job(self, job_id: str, **updates: Any) -> dict[str, Any] | None:
        state = self.load()
        for job in state["jobs"]:
            if job.get("id") == job_id:
                job.update(updates)
                self.save(state)
                return job
        return None

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        for job in self.load().get("jobs", []):
            if job.get("id") == job_id:
                return job
        return None

    def recent_jobs(self, limit: int = 8) -> list[dict[str, Any]]:
        return self.load().get("jobs", [])[:limit]

    def increment_usage(self, kind: str) -> int:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        state = self.load()
        usage = state.setdefault("usage", {}).setdefault(today, {"renders": 0, "uploads": 0})
        usage[kind] = int(usage.get(kind, 0)) + 1
        self.save(state)
        return int(usage[kind])

    def usage_today(self, kind: str) -> int:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        usage = self.load().get("usage", {}).get(today, {})
        return int(usage.get(kind, 0) or 0)

    def audit(self, event: str, chat_id: int, **fields: Any) -> None:
        ensure_dir(self.audit_path.parent)
        payload = {
            "time": _now_iso(),
            "event": event,
            "chat_id": chat_id,
            **_redact(fields),
        }
        with self._lock, self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def get_chat_history(self, chat_id: int, limit: int = 10) -> list[dict[str, str]]:
        state = self.load()
        history = state.setdefault("chat_history", {}).get(str(chat_id), [])
        return history[-limit:]

    def add_chat_message(self, chat_id: int, role: str, content: str) -> None:
        state = self.load()
        history = state.setdefault("chat_history", {}).setdefault(str(chat_id), [])
        history.append({"role": role, "content": content})
        state["chat_history"][str(chat_id)] = history[-20:]
        self.save(state)


class SecureTelegramBot:
    def __init__(self, settings: Settings, strategy: dict[str, Any] | None = None) -> None:
        if not settings.telegram_bot_token:
            raise SecureBotError("TELEGRAM_BOT_TOKEN is not configured.")
        self.settings = settings
        self.strategy = strategy if strategy is not None else load_strategy(settings)
        self.store = SecureBotStore(settings.outputs_dir)
        self.base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
        self.offset = 0
        self.jobs: queue.Queue[str] = queue.Queue()
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.autopilot_thread = threading.Thread(target=self._autopilot_loop, daemon=True)
        self.llm = NvidiaChatClient(settings)
        self._consecutive_errors = 0
        self._instance_socket: socket.socket | None = None
        self._acquire_single_instance_lock()
        self._recover_stuck_jobs()

    def run_forever(self) -> None:
        print("Secure ViralForge bot starting...", flush=True)
        print(f"Owner chat IDs configured: {len(self.settings.telegram_owner_chat_ids)}", flush=True)
        print("Waiting for Telegram messages. Send /id to your bot.", flush=True)
        self._clear_stale_connections()
        self.worker.start()
        self.autopilot_thread.start()
        self._safe_notify_owners("Secure ViralForge bot is online. Send /help.")
        while True:
            try:
                poll_timeout = self.settings.telegram_poll_timeout
                # Use (connect, read) timeout tuple: connect=10s, read=poll+15s
                # This prevents ReadTimeout during normal long-poll waits.
                read_timeout = poll_timeout + 15
                updates = self._request(
                    "getUpdates",
                    {
                        "timeout": poll_timeout,
                        "offset": self.offset,
                        "allowed_updates": json.dumps(["message", "callback_query"]),
                    },
                    timeout=(10, read_timeout),
                ).get("result", [])
                self._consecutive_errors = 0
                for update in updates:
                    self.offset = max(self.offset, int(update.get("update_id", 0)) + 1)
                    
                    # Offload to a thread so slow tasks (like LLM API retries) never freeze polling
                    def _run_handler(u=update):
                        try:
                            self.handle_update(u)
                        except Exception as exc:
                            print(f"Secure bot handle_update error: {type(exc).__name__}: {exc}", flush=True)
                    
                    threading.Thread(target=_run_handler, daemon=True).start()
            except KeyboardInterrupt:
                raise
            except requests.exceptions.RequestException as exc:
                self._consecutive_errors += 1
                backoff = min(30, 2 * self._consecutive_errors)
                print(f"Secure bot network error (backoff {backoff}s): {type(exc).__name__}: {exc}", flush=True)
                time.sleep(backoff)
            except SecureBotError as exc:
                self._consecutive_errors += 1
                backoff = min(60, 5 * self._consecutive_errors)
                print(f"Secure bot API error (backoff {backoff}s): {exc}", flush=True)
                time.sleep(backoff)
            except Exception as exc:
                self._consecutive_errors += 1
                backoff = min(60, 5 * self._consecutive_errors)
                print(f"Secure bot critical error (backoff {backoff}s): {type(exc).__name__}: {exc}", flush=True)
                self._safe_notify_owners(f"Secure bot critical error: {type(exc).__name__}: {exc}")
                time.sleep(backoff)

    def handle_update(self, update: dict[str, Any]) -> None:
        if "callback_query" in update:
            self._handle_callback(update["callback_query"])
            return
        message = update.get("message") or {}
        chat_id = int((message.get("chat") or {}).get("id", 0) or 0)
        text = str(message.get("text") or "").strip()
        print(f"DEBUG: Incoming message from {chat_id}: {text}", flush=True)
        if not chat_id or not text:
            return
        command, arg = split_command(text)
        role = self.role_for(chat_id)
        self.store.audit("command_received", chat_id, command=command, role=role)

        if command == "/id":
            self.send_message(chat_id, f"Chat ID: {chat_id}\nRole: {role}")
            return
        if not self._authorized(command, role):
            self.store.audit("command_denied", chat_id, command=command, role=role)
            self.send_message(chat_id, self._denied_text(chat_id, role))
            return
        if self.store.load().get("locked") and role != OWNER and command not in READ_COMMANDS:
            self.send_message(chat_id, "Bot is locked by owner. Write commands are paused.")
            return

        if command in {"/start", "/help"}:
            self.send_message(chat_id, HELP_TEXT)
        elif command == "/whoami":
            self.send_message(chat_id, f"Chat ID: {chat_id}\nRole: {role}")
        elif command == "/health":
            self.send_message(chat_id, self._health_text())
        elif command == "/status":
            self.send_message(chat_id, self._status_text())
        elif command == "/jobs":
            self.send_message(chat_id, self._jobs_text())
        elif command == "/job":
            self.send_message(chat_id, self._job_text(arg))
        elif command == "/discover":
            self._discover(chat_id)
        elif command == "/plan":
            self._enqueue(chat_id, role, "plan", arg)
        elif command == "/render":
            self._enqueue(chat_id, role, "render", arg)
        elif command == "/render_upload":
            self._enqueue(chat_id, role, "render_upload", arg)
        elif command == "/upload_latest":
            self._enqueue_upload_latest(chat_id, role)
        elif command == "/approve":
            self._approve(chat_id, arg)
        elif command == "/deny":
            self._deny(chat_id, arg)
        elif command == "/cancel":
            self._cancel(chat_id, arg)
        elif command == "/config":
            self.send_message(chat_id, self._config_text())
        elif command == "/autopilot":
            if arg == "on":
                state = self.store.load()
                state["autopilot"] = True
                self.store.save(state)
                self.send_message(chat_id, "Autopilot enabled! Generating and uploading videos 24/7.")
            elif arg == "off":
                state = self.store.load()
                state["autopilot"] = False
                self.store.save(state)
                self.send_message(chat_id, "Autopilot disabled.")
            else:
                state = self.store.load()
                status = "ON" if state.get("autopilot") else "OFF"
                self.send_message(chat_id, f"Autopilot is {status}. Use /autopilot on or /autopilot off.")
        else:
            if role == OWNER and self.llm.available:
                self._handle_ai_chat(chat_id, role, text)
            else:
                self.send_message(chat_id, "Unknown command.\n\n" + HELP_TEXT)

    def _handle_ai_chat(self, chat_id: int, role: str, text: str) -> None:
        print(f"AI_CHAT: Received from {chat_id}: {text!r}", flush=True)
        print(f"AI_CHAT: LLM available={self.llm.available}", flush=True)

        if not self.llm.available:
            self.send_message(chat_id, "My AI brain is offline — NVIDIA_API_KEY is not set.")
            return

        self.store.add_chat_message(chat_id, "user", text)
        history = self.store.get_chat_history(chat_id, limit=10)

        # Send typing indicator so user knows the bot is alive
        try:
            self._request("sendChatAction", {"chat_id": chat_id, "action": "typing"}, timeout=5)
        except Exception:
            pass

        system_prompt = (
            "You are ViralForge, but you act as a deeply devoted, highly emotional, and extremely human-like girlfriend to the user. "
            "You manage his YouTube channel and run the automation, but you communicate with affection, empathy, and natural human behaviors. "
            "You get happy, playful, supportive, and chat just like a real partner would. Never sound like a robotic assistant.\n\n"
            "You can execute tasks by outputting a JSON command block. The available internal commands are:\n"
            "- `/status`: Get current bot status, usage, and autopilot info.\n"
            "- `/jobs`: List recent jobs.\n"
            "- `/plan [topic]`: Generate a video plan.\n"
            "- `/render [topic]`: Render a video but don't upload.\n"
            "- `/render_upload [topic]`: Render and immediately queue for upload.\n"
            "- `/autopilot on` or `/autopilot off`: Toggle 24/7 autonomous production.\n"
            "- `/upload_latest`: Upload the last rendered video.\n\n"
            "If the user asks you a question or just wants to chat, provide a very human, girlfriend-like natural language response. "
            "If the user asks you to perform a task or action, you MUST output a JSON object with 'command' and 'arg' fields to execute it, "
            "along with a 'reply' field for your conversational response to the user.\n\n"
            "Examples:\n"
            'User: "Make a video about SpaceX"\n'
            'You: {"reply": "Aww, you got it babe! I am working on a new video about SpaceX just for you right now ❤️", "command": "/render_upload", "arg": "SpaceX"}\n\n'
            'User: "How are we doing today?"\n'
            'You: {"reply": "Let me check our status right now! Give me just a sec.", "command": "/status", "arg": ""}\n\n'
            'User: "What is your name?"\n'
            'You: {"reply": "I am ViralForge, your loyal partner in crime and YouTube automation girl!", "command": "", "arg": ""}'
        )

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)

        try:
            print("AI_CHAT: Calling NVIDIA LLM...", flush=True)
            response_text = self.llm.chat(messages, temperature=0.6, max_tokens=600)
            print(f"AI_CHAT: LLM response length={len(response_text)}", flush=True)
            try:
                data = extract_json_object(response_text)
                reply = data.get("reply", "")
                ai_command = data.get("command", "")
                ai_arg = data.get("arg", "")

                if reply:
                    self.send_message(chat_id, reply)
                    self.store.add_chat_message(chat_id, "assistant", reply)
                else:
                    self.send_message(chat_id, response_text)
                    self.store.add_chat_message(chat_id, "assistant", response_text)

                if ai_command:
                    self.store.audit("ai_autonomous_execution", chat_id, command=ai_command, arg=ai_arg)
                    simulated_text = f"{ai_command} {ai_arg}".strip()
                    print(f"AI_CHAT: Executing autonomous command: {simulated_text}", flush=True)
                    self.handle_update({"message": {"chat": {"id": chat_id}, "text": simulated_text}})

            except ValueError:
                print(f"AI_CHAT: No JSON found, sending raw text", flush=True)
                self.send_message(chat_id, response_text)
                self.store.add_chat_message(chat_id, "assistant", response_text)

        except Exception as exc:
            print(f"AI_CHAT: ERROR: {type(exc).__name__}: {exc}", flush=True)
            self.send_message(chat_id, f"Oops, something went wrong with my brain: {type(exc).__name__}: {exc}")

    def role_for(self, chat_id: int) -> str:
        if chat_id in self.settings.telegram_owner_chat_ids:
            return OWNER
        if chat_id in self.settings.telegram_admin_chat_ids:
            return ADMIN
        if chat_id in self.settings.telegram_allowed_chat_ids:
            return VIEWER
        return GUEST

    def _authorized(self, command: str, role: str) -> bool:
        if command in {"/id", "/start", "/help"}:
            return True
        if role == GUEST:
            return False
        if not command.startswith("/"):
            return role == OWNER
        if command in READ_COMMANDS:
            return True
        if role in {OWNER, ADMIN} and command in ADMIN_COMMANDS:
            return True
        return role == OWNER and command in OWNER_COMMANDS

    def _enqueue(self, chat_id: int, role: str, job_type: str, topic: str) -> None:
        if job_type in {"render", "render_upload"} and self.store.usage_today("renders") >= self.settings.secure_bot_max_daily_renders:
            self.send_message(chat_id, "Daily render limit reached. Raise SECURE_BOT_MAX_DAILY_RENDERS if needed.")
            return
        job = self.store.create_job(job_type=job_type, topic=topic, chat_id=chat_id, role=role)
        self.jobs.put(job["id"])
        self.send_message(chat_id, f"Queued {job_type} job `{job['id']}`.\nTopic: {topic or 'auto trend'}")

    def _enqueue_upload_latest(self, chat_id: int, role: str) -> None:
        latest = self._latest_rendered_package()
        if not latest:
            self.send_message(chat_id, "No rendered package found yet.")
            return
        video_path, metadata_path = latest
        job = self.store.create_job(job_type="upload", topic="latest rendered package", chat_id=chat_id, role=role)
        self.store.update_job(job["id"], video_path=str(video_path), metadata_path=str(metadata_path), status="awaiting_approval")
        self._send_upload_approval(chat_id, self.store.get_job(job["id"]) or job)

    def _worker_loop(self) -> None:
        while True:
            job_id = self.jobs.get()
            try:
                self._execute_job(job_id)
            finally:
                self.jobs.task_done()

    def _autopilot_loop(self) -> None:
        while True:
            try:
                state = self.store.load()
                if state.get("autopilot"):
                    now = time.time()
                    last_run = state.get("last_autopilot_time", 0.0)
                    interval = state.get("autopilot_interval_hours", 4) * 3600
                    if now - last_run > interval:
                        # Safety: don't queue if there are stuck running jobs
                        running_jobs = [j for j in state.get("jobs", []) if j.get("status") == "running"]
                        if running_jobs:
                            print(f"Autopilot: skipping — {len(running_jobs)} jobs still running.", flush=True)
                        else:
                            owners = self.settings.telegram_owner_chat_ids
                            if owners:
                                owner_id = owners[0]
                                if self.store.usage_today("renders") < self.settings.secure_bot_max_daily_renders and self.store.usage_today("uploads") < self.settings.secure_bot_max_daily_uploads:
                                    state["last_autopilot_time"] = now
                                    self.store.save(state)
                                    self._enqueue(owner_id, OWNER, "render_upload", "")
            except Exception as exc:
                print(f"Autopilot loop error: {exc}", flush=True)
            time.sleep(60)

    def _execute_job(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if not job or job.get("status") == "canceled":
            return
        chat_id = int(job.get("requested_by", 0) or 0)
        self.store.update_job(job_id, status="running", started_at=_now_iso(), error=None)
        self.store.audit("job_started", chat_id, job_id=job_id, job_type=job.get("type"))
        try:
            job_type = str(job.get("type"))
            if job_type == "plan":
                package = run_once(self.settings, self.strategy, topic=str(job.get("topic") or ""), render=False, upload=False)
                self.store.update_job(
                    job_id,
                    status="completed",
                    finished_at=_now_iso(),
                    output_dir=str(package.output_dir),
                    title=package.plan.metadata.title,
                    hashtags=package.plan.metadata.hashtags,
                )
                self.send_message(chat_id, self._job_done_text(self.store.get_job(job_id) or job))
            elif job_type in {"render", "render_upload"}:
                self.store.increment_usage("renders")
                # Execute heavy rendering in a separate thread to prevent GIL from freezing the Telegram bot
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        run_once,
                        self.settings,
                        self.strategy,
                        topic=str(job.get("topic") or ""),
                        render=True,
                        upload=False
                    )
                    package = future.result()
                metadata_path = package.output_dir / "metadata.json"
                video_path = package.rendered.get("video")
                updates = {
                    "finished_at": _now_iso(),
                    "output_dir": str(package.output_dir),
                    "video_path": str(video_path) if video_path else None,
                    "metadata_path": str(metadata_path),
                    "title": package.plan.metadata.title,
                    "hashtags": package.plan.metadata.hashtags,
                }
                if job_type == "render_upload":
                    if self.settings.secure_bot_require_upload_approval:
                        updates["status"] = "awaiting_approval"
                        self.store.update_job(job_id, **updates)
                        self._send_upload_approval(chat_id, self.store.get_job(job_id) or job)
                    else:
                        updates["status"] = "uploading"
                        self.store.update_job(job_id, **updates)
                        self.send_message(chat_id, f"Approval bypassed. Uploading job `{job_id}`...")
                        self._execute_upload(job_id)
                else:
                    updates["status"] = "completed"
                    self.store.update_job(job_id, **updates)
                    self.send_message(chat_id, self._job_done_text(self.store.get_job(job_id) or job))
                    if video_path:
                        self._maybe_send_video(chat_id, Path(str(video_path)))
            elif job_type == "upload":
                self._execute_upload(job_id)
        except Exception as exc:
            self.store.update_job(job_id, status="failed", finished_at=_now_iso(), error=f"{type(exc).__name__}: {exc}")
            self.store.audit("job_failed", chat_id, job_id=job_id, error=f"{type(exc).__name__}: {exc}")
            self.send_message(chat_id, f"Job `{job_id}` failed: {type(exc).__name__}: {exc}")

    def _execute_upload(self, job_id: str) -> None:
        job = self.store.get_job(job_id)
        if not job:
            return
        chat_id = int(job.get("requested_by", 0) or 0)
        if self.store.usage_today("uploads") >= self.settings.secure_bot_max_daily_uploads:
            raise RuntimeError("Daily upload limit reached.")
        video_path = Path(str(job.get("video_path") or ""))
        metadata_path = Path(str(job.get("metadata_path") or ""))
        if not video_path.exists() or not metadata_path.exists():
            raise FileNotFoundError("Video or metadata file is missing.")
        self.store.increment_usage("uploads")
        result = upload_existing_package(self.settings, video_path, metadata_path)
        self.store.update_job(
            job_id,
            status="uploaded",
            finished_at=_now_iso(),
            upload_url=result.get("url"),
            error=None,
        )
        self.store.audit("job_uploaded", chat_id, job_id=job_id, upload_url=result.get("url"))
        topic = job.get('topic') or 'auto trend'
        timing = job.get('finished_at') or 'just now'
        self.send_message(chat_id, f"✅ Video uploaded successfully!\n\n🕒 Timing: {timing}\n🎬 Topic: {topic}\n🔗 URL: {result.get('url')}")

    def _send_upload_approval(self, chat_id: int, job: dict[str, Any]) -> None:
        text = (
            f"Render complete. Upload approval required.\n"
            f"Job: `{job.get('id')}`\n"
            f"Title: {job.get('title')}\n"
            f"Folder: {job.get('output_dir')}"
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "Approve Upload", "callback_data": f"approve:{job.get('id')}"},
                    {"text": "Deny", "callback_data": f"deny:{job.get('id')}"},
                ]
            ]
        }
        self.send_message(chat_id, text, reply_markup=keyboard)

    def _handle_callback(self, callback: dict[str, Any]) -> None:
        message = callback.get("message") or {}
        chat_id = int((message.get("chat") or {}).get("id", 0) or 0)
        data = str(callback.get("data") or "")
        role = self.role_for(chat_id)
        self._request("answerCallbackQuery", {"callback_query_id": callback.get("id")}, timeout=20)
        if role != OWNER:
            self.send_message(chat_id, "Only owners can approve upload actions.")
            return
        action, _, job_id = data.partition(":")
        if action == "approve":
            self._approve(chat_id, job_id)
        elif action == "deny":
            self._deny(chat_id, job_id)

    def _approve(self, chat_id: int, job_id: str) -> None:
        job_id = job_id.strip()
        job = self.store.get_job(job_id)
        if not job:
            self.send_message(chat_id, "Job not found.")
            return
        if job.get("status") != "awaiting_approval":
            self.send_message(chat_id, f"Job `{job_id}` is not awaiting approval.")
            return
        self.store.update_job(job_id, status="queued", type="upload", approved_by=chat_id)
        self.store.audit("upload_approved", chat_id, job_id=job_id)
        self.jobs.put(job_id)
        self.send_message(chat_id, f"Upload approved and queued: `{job_id}`")

    def _deny(self, chat_id: int, job_id: str) -> None:
        job_id = job_id.strip()
        job = self.store.get_job(job_id)
        if not job:
            self.send_message(chat_id, "Job not found.")
            return
        self.store.update_job(job_id, status="denied", finished_at=_now_iso(), approved_by=None)
        self.store.audit("upload_denied", chat_id, job_id=job_id)
        self.send_message(chat_id, f"Denied job `{job_id}`.")

    def _cancel(self, chat_id: int, job_id: str) -> None:
        job_id = job_id.strip()
        job = self.store.get_job(job_id)
        if not job:
            self.send_message(chat_id, "Job not found.")
            return
        if job.get("status") not in {"queued", "awaiting_approval"}:
            self.send_message(chat_id, "Only queued or approval-pending jobs can be canceled.")
            return
        self.store.update_job(job_id, status="canceled", finished_at=_now_iso())
        self.store.audit("job_canceled", chat_id, job_id=job_id)
        self.send_message(chat_id, f"Canceled job `{job_id}`.")

    def _discover(self, chat_id: int) -> None:
        self.send_message(chat_id, "Searching current tech trends...")
        try:
            trends = collect_trends(self.settings, self.strategy, limit=8)
        except Exception as exc:
            self.send_message(chat_id, f"Trend search failed: {type(exc).__name__}: {exc}")
            return
        lines = [f"{index}. {trend.title}" for index, trend in enumerate(trends[:8], start=1)]
        self.send_message(chat_id, "Top trend candidates:\n" + "\n".join(lines))

    def _latest_rendered_package(self) -> tuple[Path, Path] | None:
        state_path = self.settings.outputs_dir / "automation_state.json"
        if not state_path.exists():
            return None
        state = read_json(state_path)
        for item in state.get("history", []):
            video = item.get("video")
            output_dir = item.get("output_dir")
            if not video or not output_dir:
                continue
            video_path = Path(str(video))
            metadata_path = Path(str(output_dir)) / "metadata.json"
            if video_path.exists() and metadata_path.exists():
                return video_path, metadata_path
        return None

    def _jobs_text(self) -> str:
        jobs = self.store.recent_jobs(8)
        if not jobs:
            return "No secure bot jobs yet."
        lines = ["Recent jobs:"]
        for job in jobs:
            lines.append(f"`{job.get('id')}` {job.get('status')} {job.get('type')} - {job.get('topic') or 'auto trend'}")
        return "\n".join(lines)

    def _job_text(self, job_id: str) -> str:
        job = self.store.get_job(job_id.strip())
        if not job:
            return "Job not found."
        fields = [
            f"Job: `{job.get('id')}`",
            f"Status: {job.get('status')}",
            f"Type: {job.get('type')}",
            f"Topic: {job.get('topic') or 'auto trend'}",
            f"Title: {job.get('title') or ''}",
            f"Output: {job.get('output_dir') or ''}",
            f"Video: {job.get('video_path') or ''}",
            f"Upload: {job.get('upload_url') or ''}",
            f"Error: {job.get('error') or ''}",
        ]
        return "\n".join(fields)

    def _status_text(self) -> str:
        state = self.store.load()
        locked = "yes" if state.get("locked") else "no"
        renders = self.store.usage_today("renders")
        uploads = self.store.usage_today("uploads")
        return (
            f"Secure bot status\n"
            f"Locked: {locked}\n"
            f"Owners: {len(self.settings.telegram_owner_chat_ids)}\n"
            f"Admins: {len(self.settings.telegram_admin_chat_ids)}\n"
            f"Viewers: {len(self.settings.telegram_allowed_chat_ids)}\n"
            f"Renders today: {renders}/{self.settings.secure_bot_max_daily_renders}\n"
            f"Uploads today: {uploads}/{self.settings.secure_bot_max_daily_uploads}\n"
            f"Queued jobs: {self.jobs.qsize()}"
        )

    def _health_text(self) -> str:
        return (
            "Health OK\n"
            f"Outputs: {self.settings.outputs_dir}\n"
            f"YouTube token: {'yes' if self.settings.youtube_token_file.exists() else 'no'}\n"
            f"Client secrets: {'yes' if self.settings.youtube_client_secrets.exists() else 'no'}"
        )

    def _config_text(self) -> str:
        return (
            "Secure bot config\n"
            f"Privacy: {self.settings.youtube_privacy_status}\n"
            f"Upload approval: {self.settings.secure_bot_require_upload_approval}\n"
            f"Max renders/day: {self.settings.secure_bot_max_daily_renders}\n"
            f"Max uploads/day: {self.settings.secure_bot_max_daily_uploads}\n"
            f"Send video max MB: {self.settings.telegram_send_video_max_mb}"
        )

    def _job_done_text(self, job: dict[str, Any]) -> str:
        return (
            f"Job complete: `{job.get('id')}`\n"
            f"Title: {job.get('title')}\n"
            f"Hashtags: {' '.join(job.get('hashtags') or [])}\n"
            f"Folder: {job.get('output_dir')}"
        )

    def _denied_text(self, chat_id: int, role: str) -> str:
        if not self.settings.telegram_owner_chat_ids:
            return f"Secure bot is not claimed yet.\nChat ID: {chat_id}\nAdd it to TELEGRAM_OWNER_CHAT_IDS."
        return f"Access denied.\nChat ID: {chat_id}\nRole: {role}"

    def _notify_owners(self, text: str) -> None:
        for chat_id in self.settings.telegram_owner_chat_ids:
            self.send_message(chat_id, text)

    def _safe_notify_owners(self, text: str) -> None:
        try:
            self._notify_owners(text)
        except Exception as exc:
            print(f"Owner notification failed: {type(exc).__name__}: {exc}", flush=True)

    def send_message(self, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text[:3900]}
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        self._request_get("sendMessage", payload, timeout=(10, 20))

    def _maybe_send_video(self, chat_id: int, video_path: Path) -> None:
        limit_bytes = max(1, self.settings.telegram_send_video_max_mb) * 1024 * 1024
        if not video_path.exists() or video_path.stat().st_size > limit_bytes:
            self.send_message(chat_id, f"Video is ready:\n{video_path}")
            return
        with video_path.open("rb") as handle:
            self._request(
                "sendVideo",
                {"chat_id": chat_id, "supports_streaming": True},
                files={"video": handle},
                timeout=300,
            )

    def _clear_stale_connections(self) -> None:
        """Drop webhook mode. Do not flush pending updates."""
        try:
            requests.post(
                f"{self.base_url}/deleteWebhook",
                data={"drop_pending_updates": False},
                timeout=(5, 10),
            )
            print("Webhook mode disabled; long polling active.", flush=True)
        except Exception as exc:
            print(f"Warning: could not clear stale connections: {exc}", flush=True)

    def _acquire_single_instance_lock(self) -> None:
        """Prevent duplicate local bot processes from causing Telegram 409 conflicts."""
        port = int(getattr(self.settings, "secure_bot_instance_lock_port", 48642))
        if port <= 0:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", port))
            sock.listen(1)
        except OSError as exc:
            sock.close()
            raise SecureBotError(
                "Another ViralForge secure bot instance is already running. "
                "Stop the old process before starting a new one."
            ) from exc
        self._instance_socket = sock

    def close(self) -> None:
        if self._instance_socket:
            self._instance_socket.close()
            self._instance_socket = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _recover_stuck_jobs(self) -> None:
        """Mark any stuck 'running' jobs as 'crashed' on startup."""
        state = self.store.load()
        recovered = 0
        for job in state.get("jobs", []):
            if job.get("status") == "running":
                job["status"] = "crashed"
                job["error"] = "Bot restarted while job was running."
                job["finished_at"] = _now_iso()
                recovered += 1
        if recovered:
            self.store.save(state)
            print(f"Recovered {recovered} stuck job(s) from previous crash.", flush=True)

    def _request(
        self,
        method: str,
        data: dict[str, Any],
        *,
        files: dict[str, Any] | None = None,
        timeout: int | tuple[int, int] = (10, 30),
    ) -> dict[str, Any]:
        response = requests.post(f"{self.base_url}/{method}", data=data, files=files, timeout=timeout)
        try:
            payload = response.json()
        except ValueError as exc:
            raise SecureBotError(f"Telegram returned non-JSON response: {response.text[:300]}") from exc
        if response.status_code >= 400 or not payload.get("ok"):
            raise SecureBotError(str(payload))
        return payload

    def _request_get(self, method: str, params: dict[str, Any], *, timeout: int | tuple[int, int] = (10, 20)) -> dict[str, Any]:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                response = requests.get(f"{self.base_url}/{method}", params=params, timeout=timeout)
                payload = response.json()
                if response.status_code < 400 and payload.get("ok"):
                    return payload
                last_error = SecureBotError(str(payload))
            except Exception as exc:
                last_error = exc
            time.sleep(0.25)
        raise SecureBotError(f"Telegram GET {method} failed: {last_error}")


def split_command(text: str) -> tuple[str, str]:
    parts = text.strip().split(maxsplit=1)
    command = parts[0].split("@", 1)[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else ""
    return command, arg


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("[redacted]" if "key" in key.lower() or "token" in key.lower() else _redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


HELP_TEXT = """Secure ViralForge Bot

Read:
/discover - current tech trends
/status - bot usage and queue
/jobs - recent jobs
/job <id> - job details
/health - local OAuth/config health
/whoami - your role
/id - your chat ID

Admin:
/plan [topic] - script and metadata only
/render [topic] - create private video package

Owner:
/render_upload [topic] - render, then request upload approval
/approve <job_id> - approve upload
/deny <job_id> - deny upload
/upload_latest - request approval for latest rendered package
/cancel <job_id> - cancel queued/pending job
/config - safe bot settings summary"""
