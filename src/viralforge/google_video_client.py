from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import requests

from .config import Settings


class GoogleVideoProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GoogleVeoClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def available(self) -> bool:
        return bool(self.settings.google_ai_api_key)

    def list_models(self) -> list[str]:
        response = requests.get(
            f"{self.settings.google_video_base_url}/models",
            headers=self._headers(),
            timeout=60,
        )
        if response.status_code >= 400:
            raise GoogleVideoProviderError(_provider_error(response), status_code=response.status_code)
        return sorted(str(item.get("name", "")).replace("models/", "") for item in response.json().get("models", []))

    def generate_text_video(
        self,
        prompt: str,
        *,
        output_path: Path,
        aspect_ratio: str | None = None,
        duration_seconds: int | None = None,
        resolution: str | None = None,
    ) -> Path:
        payload = self._payload(
            {"prompt": prompt},
            aspect_ratio=aspect_ratio,
            duration_seconds=duration_seconds,
            resolution=resolution,
        )
        return self._generate(payload, output_path)

    def generate_image_video(
        self,
        prompt: str,
        *,
        image_bytes: bytes,
        mime_type: str,
        output_path: Path,
        aspect_ratio: str | None = None,
        duration_seconds: int | None = None,
        resolution: str | None = None,
    ) -> Path:
        instance = {
            "prompt": prompt,
            "image": {
                "inlineData": {
                    "mimeType": mime_type,
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }
            },
        }
        return self._generate(
            self._payload(
                instance,
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_seconds,
                resolution=resolution,
            ),
            output_path,
        )

    def _payload(
        self,
        instance: dict[str, Any],
        *,
        aspect_ratio: str | None,
        duration_seconds: int | None,
        resolution: str | None,
    ) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "aspectRatio": aspect_ratio or self.settings.google_video_aspect_ratio,
            "durationSeconds": int(duration_seconds or self.settings.google_video_duration_seconds),
        }
        chosen_resolution = (resolution or self.settings.google_video_resolution).strip()
        if chosen_resolution:
            parameters["resolution"] = chosen_resolution
        return {"instances": [instance], "parameters": parameters}

    def _generate(self, payload: dict[str, Any], output_path: Path) -> Path:
        if not self.available:
            raise GoogleVideoProviderError("GOOGLE_AI_API_KEY is not configured.")
        endpoint = f"{self.settings.google_video_base_url}/models/{self.settings.google_video_model}:predictLongRunning"
        response = requests.post(endpoint, headers=self._headers(), json=payload, timeout=120)
        if response.status_code >= 400:
            raise GoogleVideoProviderError(_provider_error(response), status_code=response.status_code)
        operation_name = response.json().get("name")
        if not operation_name:
            raise GoogleVideoProviderError(f"Google Veo response did not include an operation name: {response.text[:500]}")
        result = self._poll_operation(str(operation_name))
        video_uri = _extract_video_uri(result)
        video_bytes = _extract_video_bytes(result)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if video_bytes:
            output_path.write_bytes(video_bytes)
            return output_path
        if not video_uri:
            raise GoogleVideoProviderError("Google Veo operation finished but no video URI or bytes were found.")
        download = requests.get(video_uri, headers=self._headers(), timeout=300, allow_redirects=True)
        if download.status_code >= 400:
            raise GoogleVideoProviderError(_provider_error(download), status_code=download.status_code)
        output_path.write_bytes(download.content)
        return output_path

    def _poll_operation(self, operation_name: str) -> dict[str, Any]:
        deadline = time.time() + max(60, self.settings.google_video_timeout_seconds)
        poll_seconds = max(3, self.settings.google_video_poll_seconds)
        url = f"{self.settings.google_video_base_url}/{operation_name}"
        latest: dict[str, Any] = {}
        while time.time() < deadline:
            response = requests.get(url, headers=self._headers(), timeout=60)
            if response.status_code >= 400:
                raise GoogleVideoProviderError(_provider_error(response), status_code=response.status_code)
            latest = response.json()
            if latest.get("done") is True:
                if latest.get("error"):
                    raise GoogleVideoProviderError(f"Google Veo generation failed: {latest['error']}")
                return latest
            time.sleep(poll_seconds)
        raise GoogleVideoProviderError(f"Timed out waiting for Google Veo operation {operation_name}.")

    def _headers(self) -> dict[str, str]:
        return {
            "x-goog-api-key": self.settings.google_ai_api_key,
            "Content-Type": "application/json",
        }


def _extract_video_uri(value: Any) -> str | None:
    if isinstance(value, dict):
        video = value.get("video")
        if isinstance(video, dict) and isinstance(video.get("uri"), str):
            return video["uri"]
        if isinstance(value.get("uri"), str):
            return value["uri"]
        for key in ("response", "generateVideoResponse", "generatedSamples", "generatedVideos", "video"):
            if key in value:
                found = _extract_video_uri(value[key])
                if found:
                    return found
        for item in value.values():
            found = _extract_video_uri(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _extract_video_uri(item)
            if found:
                return found
    return None


def _extract_video_bytes(value: Any) -> bytes | None:
    if isinstance(value, dict):
        for key in ("videoBytes", "bytes", "data"):
            candidate = value.get(key)
            if isinstance(candidate, str) and len(candidate) > 1000:
                try:
                    return base64.b64decode(candidate)
                except Exception:
                    pass
        for item in value.values():
            found = _extract_video_bytes(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _extract_video_bytes(item)
            if found:
                return found
    return None


def _provider_error(response: requests.Response) -> str:
    text = response.text[:900] if response.text else response.reason
    return f"Google Veo provider returned {response.status_code}: {text}"
