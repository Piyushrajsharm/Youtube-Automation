from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Any

from .config import Settings
from .models import UploadMetadata
from .utils import ensure_dir


SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
RETRIABLE_STATUS_CODES = {500, 502, 503, 504}
RETRIABLE_EXCEPTIONS = (OSError, TimeoutError)


class UploadDisabled(RuntimeError):
    pass


def upload_video(video_path: Path, metadata: UploadMetadata, settings: Settings) -> dict[str, Any]:
    if not settings.youtube_upload_enabled:
        raise UploadDisabled("YOUTUBE_UPLOAD_ENABLED is false.")
    if not video_path.exists():
        raise FileNotFoundError(video_path)

    youtube = _youtube_service(settings)

    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    body = {
        "snippet": {
            "title": metadata.title,
            "description": metadata.description,
            "tags": metadata.tags[:5],  # Optimize for 2026 Shorts algorithm: max 5 highly relevant hashtags
            "categoryId": metadata.category_id,
            "defaultLanguage": settings.youtube_default_language,
            "defaultAudioLanguage": settings.youtube_default_language,
        },
        "status": {
            "privacyStatus": metadata.privacy_status,
            "selfDeclaredMadeForKids": metadata.made_for_kids,
            "containsSyntheticMedia": metadata.contains_synthetic_media,
        },
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    error = None
    retry = 0
    while response is None:
        try:
            _, response = request.next_chunk()
            if response:
                video_id = response["id"]
                return {"id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}", "response": response}
        except HttpError as exc:
            if exc.resp.status not in RETRIABLE_STATUS_CODES:
                raise
            error = f"Retriable HTTP error {exc.resp.status}: {exc.content}"
        except RETRIABLE_EXCEPTIONS as exc:
            error = f"Retriable upload error: {exc}"

        if error is not None:
            retry += 1
            if retry > 5:
                raise RuntimeError(f"Upload failed after retries: {error}")
            sleep_seconds = random.random() * (2**retry)
            time.sleep(sleep_seconds)
            error = None

    raise RuntimeError("Upload ended without a response.")


def authorize_youtube(settings: Settings) -> dict[str, Any]:
    _youtube_service(settings)
    return {
        "client_secrets": str(settings.youtube_client_secrets),
        "token_file": str(settings.youtube_token_file),
        "scopes": SCOPES,
        "upload_enabled": bool(settings.youtube_upload_enabled),
    }


def get_channel_stats(settings: Settings) -> dict[str, Any]:
    youtube = _youtube_service(settings)
    request = youtube.channels().list(part="statistics", mine=True)
    response = request.execute()
    if not response.get("items"):
        return {}
    return response["items"][0].get("statistics", {})


def youtube_token_status(settings: Settings) -> dict[str, Any]:
    """Check YouTube OAuth token health without triggering a full auth flow."""
    result: dict[str, Any] = {
        "token_file_exists": settings.youtube_token_file.exists(),
        "client_secrets_exists": settings.youtube_client_secrets.exists(),
        "valid": False,
        "expired": False,
        "has_refresh_token": False,
        "error": None,
    }
    if not settings.youtube_token_file.exists():
        result["error"] = "Token file not found. Run: python -m viralforge.cli authorize"
        return result
    try:
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(settings.youtube_token_file), SCOPES)
        result["expired"] = bool(creds.expired)
        result["has_refresh_token"] = bool(creds.refresh_token)
        result["valid"] = bool(creds.valid)
    except Exception as exc:
        result["error"] = f"Token parse error: {type(exc).__name__}: {exc}"
    return result


def _youtube_service(settings: Settings) -> Any:
    if not settings.youtube_client_secrets.exists():
        raise FileNotFoundError(
            f"Missing OAuth client secrets at {settings.youtube_client_secrets}. "
            "Create an OAuth Desktop client in Google Cloud and save it there."
        )

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if settings.youtube_token_file.exists():
        creds = Credentials.from_authorized_user_file(str(settings.youtube_token_file), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:
                raise RuntimeError(
                    f"YouTube OAuth token refresh failed: {type(exc).__name__}: {exc}. "
                    "The refresh token has likely expired or been revoked. "
                    "If your Google Cloud project is in 'Testing' mode, tokens expire after 7 days. "
                    "Fix: Re-authorize locally with 'python -m viralforge.cli authorize', "
                    "then update the YOUTUBE_TOKEN_JSON secret on Hugging Face Space."
                ) from exc
        else:
            if os.getenv("SPACE_ID"):
                raise RuntimeError(
                    "YouTube OAuth token is missing or invalid, and interactive re-authorization "
                    "is not possible on Hugging Face Space. "
                    "Fix: Re-authorize locally with 'python -m viralforge.cli authorize', "
                    "then update the YOUTUBE_TOKEN_JSON secret on Hugging Face Space."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(settings.youtube_client_secrets), SCOPES)
            creds = flow.run_local_server(port=0)
        ensure_dir(settings.youtube_token_file.parent)
        settings.youtube_token_file.write_text(creds.to_json(), encoding="utf-8")

    return build("youtube", "v3", credentials=creds)
