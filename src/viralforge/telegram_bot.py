from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

from .automation import run_once, upload_existing_package
from .config import Settings, load_strategy
from .trends import collect_trends
from .utils import read_json


class TelegramBotError(RuntimeError):
    pass


class TelegramController:
    def __init__(self, settings: Settings, strategy: dict[str, Any] | None = None) -> None:
        if not settings.telegram_bot_token:
            raise TelegramBotError("TELEGRAM_BOT_TOKEN is not configured.")
        self.settings = settings
        self.strategy = strategy if strategy is not None else load_strategy(settings)
        self.base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
        self.offset = 0
        self._consecutive_errors = 0

    def run_forever(self) -> None:
        self._safe_send_admin("ViralForge Telegram bot is online. Send /help for commands.")
        while True:
            try:
                updates = self._request(
                    "getUpdates",
                    {
                        "timeout": self.settings.telegram_poll_timeout,
                        "offset": self.offset,
                        "allowed_updates": json.dumps(["message"]),
                    },
                    timeout=(10, self.settings.telegram_poll_timeout + 15),
                ).get("result", [])
                self._consecutive_errors = 0
                for update in updates:
                    self.offset = max(self.offset, int(update.get("update_id", 0)) + 1)
                    self.handle_update(update)
            except KeyboardInterrupt:
                raise
            except requests.exceptions.RequestException as exc:
                self._consecutive_errors += 1
                time.sleep(min(30, 2 * self._consecutive_errors))
            except TelegramBotError as exc:
                self._consecutive_errors += 1
                backoff = min(60, 5 * self._consecutive_errors)
                print(f"Telegram bot API error (backoff {backoff}s): {exc}", flush=True)
                time.sleep(backoff)
            except Exception as exc:
                self._consecutive_errors += 1
                backoff = min(60, 5 * self._consecutive_errors)
                print(f"Telegram bot critical error (backoff {backoff}s): {type(exc).__name__}: {exc}", flush=True)
                self._safe_send_admin(f"Telegram bot critical error: {type(exc).__name__}: {exc}")
                time.sleep(backoff)

    def handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = int(chat.get("id", 0) or 0)
        text = str(message.get("text") or "").strip()
        if not chat_id or not text:
            return
        command, arg = _split_command(text)
        if not self._allowed(chat_id) and command not in {"/id", "/start", "/help"}:
            self.send_message(
                chat_id,
                f"This chat is not allowed yet.\nChat ID: {chat_id}\nAdd it to TELEGRAM_ALLOWED_CHAT_IDS or TELEGRAM_OWNER_CHAT_IDS.",
            )
            return

        if command in {"/start", "/help"}:
            self.send_message(chat_id, HELP_TEXT)
        elif command == "/id":
            self.send_message(chat_id, f"Chat ID: {chat_id}")
        elif command == "/status":
            self.send_message(chat_id, self._status_text())
        elif command == "/discover":
            self.send_message(chat_id, "Searching current tech trends...")
            trends = collect_trends(self.settings, self.strategy, limit=8)
            lines = [f"{index}. {trend.title}" for index, trend in enumerate(trends[:8], start=1)]
            self.send_message(chat_id, "Top trend candidates:\n" + "\n".join(lines))
        elif command == "/plan":
            self._run_package(chat_id, topic=arg, render=False, upload=False)
        elif command == "/run":
            self._run_package(chat_id, topic=arg, render=True, upload=False)
        elif command == "/run_upload":
            self._run_package(chat_id, topic=arg, render=True, upload=True)
        elif command == "/upload_latest":
            self._upload_latest(chat_id)
        else:
            self.send_message(chat_id, "Unknown command.\n\n" + HELP_TEXT)

    def _run_package(self, chat_id: int, *, topic: str, render: bool, upload: bool) -> None:
        mode = "render + upload" if upload else "render" if render else "plan"
        self.send_message(chat_id, f"Starting {mode} automation. Topic: {topic or 'auto trend'}")
        try:
            package = run_once(
                self.settings,
                self.strategy,
                topic=topic,
                render=render,
                upload=upload,
            )
        except Exception as exc:
            self.send_message(chat_id, f"Automation failed: {type(exc).__name__}: {exc}")
            return

        metadata = package.plan.metadata
        lines = [
            "Automation complete.",
            f"Topic: {package.topic}",
            f"Title: {metadata.title}",
            f"Hashtags: {' '.join(metadata.hashtags)}",
            f"Compliance: {'passed' if package.compliance.passed else 'needs review'}",
            f"Folder: {package.output_dir}",
        ]
        if package.upload_result:
            lines.append(f"YouTube: {package.upload_result.get('url')}")
        self.send_message(chat_id, "\n".join(lines))

        video_path = package.rendered.get("video")
        if video_path:
            self._maybe_send_video(chat_id, Path(str(video_path)))

    def _upload_latest(self, chat_id: int) -> None:
        latest = self._latest_rendered_package()
        if not latest:
            self.send_message(chat_id, "No rendered package found yet.")
            return
        video_path, metadata_path = latest
        self.send_message(chat_id, f"Uploading latest rendered video:\n{video_path}")
        try:
            result = upload_existing_package(self.settings, video_path, metadata_path)
        except Exception as exc:
            self.send_message(chat_id, f"Upload failed: {type(exc).__name__}: {exc}")
            return
        self.send_message(chat_id, f"Uploaded: {result.get('url')}")

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

    def _status_text(self) -> str:
        state_path = self.settings.outputs_dir / "automation_state.json"
        if not state_path.exists():
            return "No automation history yet."
        state = read_json(state_path)
        history = state.get("history", [])[:5]
        if not history:
            return "No automation history yet."
        lines = ["Recent ViralForge runs:"]
        for index, item in enumerate(history, start=1):
            status = "uploaded" if item.get("uploaded") else "created"
            lines.append(f"{index}. {status}: {item.get('topic')} ({item.get('created_at')})")
        return "\n".join(lines)

    def _allowed(self, chat_id: int) -> bool:
        allowed = self.settings.telegram_allowed_chat_ids
        owners = self.settings.telegram_owner_chat_ids
        return chat_id in allowed or chat_id in owners

    def _safe_send_admin(self, text: str) -> None:
        """Send message to admins, silently ignoring failures to prevent error cascades."""
        for chat_id in self.settings.telegram_allowed_chat_ids or self.settings.telegram_owner_chat_ids:
            try:
                self.send_message(chat_id, text)
            except Exception as exc:
                print(f"Admin notification failed: {type(exc).__name__}: {exc}", flush=True)

    def send_admin_message(self, text: str) -> None:
        for chat_id in self.settings.telegram_allowed_chat_ids:
            self.send_message(chat_id, text)

    def send_message(self, chat_id: int, text: str) -> None:
        self._request("sendMessage", {"chat_id": chat_id, "text": text[:3900]}, timeout=30)

    def _maybe_send_video(self, chat_id: int, video_path: Path) -> None:
        limit_bytes = max(1, self.settings.telegram_send_video_max_mb) * 1024 * 1024
        if not video_path.exists():
            return
        if video_path.stat().st_size > limit_bytes:
            self.send_message(chat_id, f"Video is ready, but too large for Telegram preview limit:\n{video_path}")
            return
        with video_path.open("rb") as handle:
            self._request(
                "sendVideo",
                {"chat_id": chat_id, "supports_streaming": True},
                files={"video": handle},
                timeout=300,
            )

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
            raise TelegramBotError(f"Telegram returned non-JSON response: {response.text[:300]}") from exc
        if response.status_code >= 400 or not payload.get("ok"):
            raise TelegramBotError(str(payload))
        return payload


def _split_command(text: str) -> tuple[str, str]:
    parts = text.split(maxsplit=1)
    command = parts[0].split("@", 1)[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    return command, arg


HELP_TEXT = """ViralForge commands:
/discover - show current tech trend candidates
/plan [topic] - create script/metadata only
/run [topic] - render a private video package
/run_upload [topic] - render and upload with YouTube OAuth
/upload_latest - upload the latest rendered package
/status - show recent runs
/id - show this chat ID

Use topics like:
/run funny AI tools
/run gadget quiz
/run cybersecurity news"""
