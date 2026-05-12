from __future__ import annotations

import base64
import time
from typing import Any

import requests

from .config import Settings


class NvidiaProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class NvidiaUnifiedClient:
    """Single client for all NVIDIA NIM services with 40 req/min rate limiting."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._last_request_time: float = 0.0

    @property
    def available(self) -> bool:
        return bool(self.settings.nvidia_api_key)

    def _throttle(self) -> None:
        """Ensure we don't exceed 40 requests per minute."""
        min_interval = 1.6  # seconds between requests
        elapsed = time.time() - self._last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()

    def _headers(self, *, accept: str = "application/json") -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.nvidia_api_key}",
            "Accept": accept,
            "Content-Type": "application/json",
        }

    def _post(self, endpoint: str, payload: dict[str, Any], *, retries: int = 3) -> dict[str, Any]:
        url = f"{self.settings.nvidia_base_url.rstrip('/')}{endpoint}"
        last_exc: Exception | None = None
        for attempt in range(retries):
            self._throttle()
            try:
                response = requests.post(url, headers=self._headers(), json=payload, timeout=(15, 120))
                response.raise_for_status()
                return response.json()
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                last_exc = exc
                wait = 2 ** attempt
                print(f"NVIDIA API attempt {attempt+1}/{retries} failed: {exc}. Retrying in {wait}s...", flush=True)
                time.sleep(wait)
        raise NvidiaProviderError(f"NVIDIA API failed after {retries} attempts: {last_exc}")

    def list_models(self) -> list[str]:
        self._throttle()
        url = f"{self.settings.nvidia_base_url.rstrip('/')}/models"
        response = requests.get(url, headers=self._headers(), timeout=60)
        response.raise_for_status()
        data = response.json().get("data", [])
        return sorted(str(item.get("id", "")) for item in data if item.get("id"))

    # ---- Chat (existing) ----
    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.45,
        max_tokens: int = 1800,
    ) -> str:
        payload = {
            "model": self.settings.nvidia_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        result = self._post("/chat/completions", payload)
        return result["choices"][0]["message"]["content"]

    # ---- Video Generation ----
    def generate_video(
        self,
        prompt: str,
        *,
        negative_prompt: str = "",
        duration: int = 8,
        fps: int = 24,
    ) -> bytes:
        raise NvidiaProviderError(
            "Text-to-video is not exposed by the configured NVIDIA hosted endpoint. "
            "Use generate_video_from_image() for the documented Stable Video Diffusion image-to-video API."
        )

    def generate_video_from_image(
        self,
        image_data_uri: str,
        *,
        prompt: str = "",
        seed: int = 0,
        cfg_scale: float = 1.8,
        motion_bucket_id: int = 127,
    ) -> bytes:
        """Generate image-to-video through NVIDIA's hosted visual model endpoint.

        NVIDIA's public Stable Video Diffusion endpoint accepts an initial image
        and returns either a video payload immediately or an async NVCF request
        id that must be polled.
        """
        endpoint = _video_endpoint_for(self.settings.nvidia_video_model)
        url = f"{self.settings.nvidia_video_base_url.rstrip('/')}{endpoint}"
        payload: dict[str, Any] = {
            "image": image_data_uri,
            "seed": int(seed),
            "cfg_scale": float(cfg_scale),
            "motion_bucket_id": int(motion_bucket_id),
        }
        if prompt and "prompt" in self.settings.nvidia_video_model.lower():
            payload["prompt"] = prompt
        response = self._post_video(url, payload)
        return _extract_video_bytes(response)

    def _post_video(self, url: str, payload: dict[str, Any]) -> Any:
        self._throttle()
        try:
            response = requests.post(url, headers=self._headers(), json=payload, timeout=300)
        except requests.RequestException as exc:
            raise NvidiaProviderError(f"NVIDIA video request failed: {exc}") from exc
        if response.status_code == 202:
            request_id = response.headers.get("NVCF-REQID") or response.headers.get("nvcf-reqid")
            if not request_id:
                try:
                    request_id = response.json().get("requestId") or response.json().get("id")
                except Exception:
                    request_id = None
            if not request_id:
                raise NvidiaProviderError("NVIDIA returned 202 but did not include a request id.", status_code=202)
            return self._poll_nvcf_result(str(request_id))
        if response.status_code == 302 and response.headers.get("Location"):
            return self._download_location(response.headers["Location"])
        if response.status_code >= 400:
            raise NvidiaProviderError(_provider_error(response), status_code=response.status_code)
        content_type = response.headers.get("Content-Type", "")
        if "video/" in content_type or response.content[:8].startswith(b"\x00\x00\x00"):
            return response.content
        try:
            return response.json()
        except ValueError:
            return response.content

    def _poll_nvcf_result(self, request_id: str) -> Any:
        status_url = (
            self.settings.nvidia_video_base_url.rstrip("/")
            + f"/v2/nvcf/pexec/status/{request_id}"
        )
        headers = self._headers()
        headers["NVCF-POLL-SECONDS"] = "5"
        deadline = time.time() + 900
        while time.time() < deadline:
            self._throttle()
            response = requests.get(status_url, headers=headers, timeout=120)
            if response.status_code == 202:
                time.sleep(5)
                continue
            if response.status_code == 302 and response.headers.get("Location"):
                return self._download_location(response.headers["Location"])
            if response.status_code >= 400:
                raise NvidiaProviderError(_provider_error(response), status_code=response.status_code)
            content_type = response.headers.get("Content-Type", "")
            if "video/" in content_type or response.content[:8].startswith(b"\x00\x00\x00"):
                return response.content
            return response.json()
        raise NvidiaProviderError("Timed out waiting for NVIDIA video generation.", status_code=202)

    def _download_location(self, url: str) -> bytes:
        response = requests.get(url, headers={"Authorization": f"Bearer {self.settings.nvidia_api_key}"}, timeout=300)
        if response.status_code >= 400:
            raise NvidiaProviderError(_provider_error(response), status_code=response.status_code)
        return response.content

    # ---- Image Generation ----
    def generate_image(self, prompt: str, *, size: str = "1024x1024") -> bytes:
        payload = {
            "model": self.settings.nvidia_image_model,
            "prompt": prompt,
            "n": 1,
            "size": size,
        }
        result = self._post("/images/generations", payload)
        return base64.b64decode(result["data"][0]["b64_json"])


def _video_endpoint_for(model: str) -> str:
    normalized = model.strip().lower()
    endpoints = {
        "stabilityai/stable-video-diffusion": "/genai/stabilityai/stable-video-diffusion",
        "stable-video-diffusion": "/genai/stabilityai/stable-video-diffusion",
    }
    return endpoints.get(normalized, f"/genai/{normalized}")


def _provider_error(response: requests.Response) -> str:
    text = response.text[:700] if response.text else response.reason
    return f"NVIDIA provider returned {response.status_code}: {text}"


def _extract_video_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    b64 = _find_video_b64(value)
    if not b64:
        raise NvidiaProviderError("NVIDIA response did not contain video bytes or base64 video data.")
    if ";base64," in b64:
        b64 = b64.split(";base64,", 1)[1]
    return base64.b64decode(b64)


def _find_video_b64(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("data:video") or len(stripped) > 1000:
            return stripped
        return None
    if isinstance(value, list):
        for item in value:
            found = _find_video_b64(item)
            if found:
                return found
        return None
    if isinstance(value, dict):
        priority = [
            "video",
            "video_base64",
            "b64_video",
            "b64_json",
            "mp4",
            "output",
            "outputs",
            "artifacts",
            "data",
            "result",
        ]
        for key in priority:
            if key in value:
                found = _find_video_b64(value[key])
                if found:
                    return found
        for item in value.values():
            found = _find_video_b64(item)
            if found:
                return found
    return None
