from __future__ import annotations

from pathlib import Path

import requests

from .config import Settings
from .utils import write_json


def synthesize_nvidia_audio(text: str, output_dir: Path, settings: Settings) -> Path | None:
    """Try NVIDIA Speech NIM TTS over the documented HTTP endpoint.

    NVIDIA TTS NIM is normally a deployed speech microservice. The documented
    offline HTTP path is /v1/audio/synthesize and returns a WAV file. Hosted
    build.nvidia.com account keys do not automatically expose this unless a
    speech endpoint/container is configured.
    """
    report_path = output_dir / "nvidia_audio_report.json"
    report: dict[str, object] = {
        "enabled": bool(settings.nvidia_audio_enabled),
        "provider": "nvidia_speech_nim",
        "base_url": settings.nvidia_audio_base_url,
        "model": settings.nvidia_audio_model,
        "voice": settings.nvidia_audio_voice,
        "status": "skipped",
        "fallback_used": True,
    }
    if not settings.nvidia_audio_enabled:
        write_json(report_path, report)
        return None
    if not text.strip():
        report["status"] = "failed"
        report["error"] = "No narration text to synthesize."
        write_json(report_path, report)
        return None

    url = f"{settings.nvidia_audio_base_url.rstrip('/')}/v1/audio/synthesize"
    data = {
        "language": "en-US",
        "text": text,
        "voice": settings.nvidia_audio_voice,
    }
    headers = {}
    if settings.nvidia_api_key and settings.nvidia_audio_base_url.startswith("https://"):
        headers["Authorization"] = f"Bearer {settings.nvidia_api_key}"

    try:
        response = requests.post(url, data=data, headers=headers, timeout=180)
        if response.status_code >= 400:
            report["status"] = "provider_failed"
            report["status_code"] = response.status_code
            report["error"] = response.text[:700] if response.text else response.reason
            write_json(report_path, report)
            return None
        audio_path = output_dir / "nvidia_narration.wav"
        audio_path.write_bytes(response.content)
        if audio_path.stat().st_size < 128:
            report["status"] = "failed"
            report["error"] = "NVIDIA TTS response was too small to be a valid WAV file."
            write_json(report_path, report)
            return None
        report["status"] = "generated"
        report["fallback_used"] = False
        report["audio_path"] = str(audio_path)
        report["bytes"] = audio_path.stat().st_size
        write_json(report_path, report)
        return audio_path
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        write_json(report_path, report)
        return None
