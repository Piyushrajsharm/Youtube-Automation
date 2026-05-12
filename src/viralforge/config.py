from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .utils import read_json, truthy


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    project_root: Path
    nvidia_api_key: str
    nvidia_base_url: str
    nvidia_model: str
    nvidia_fallback_model: str
    nvidia_image_enabled: bool
    nvidia_image_model: str
    nvidia_video_enabled: bool
    nvidia_video_base_url: str
    nvidia_video_model: str
    nvidia_video_max_scenes: int
    nvidia_video_duration: int
    nvidia_video_cfg_scale: float
    nvidia_video_motion_bucket_id: int
    nvidia_audio_enabled: bool
    nvidia_audio_base_url: str
    nvidia_audio_model: str
    nvidia_audio_voice: str
    google_ai_api_key: str
    google_video_enabled: bool
    google_video_base_url: str
    google_video_model: str
    google_video_max_scenes: int
    google_video_duration_seconds: int
    google_video_aspect_ratio: str
    google_video_resolution: str
    google_video_mode: str
    google_video_poll_seconds: int
    google_video_timeout_seconds: int
    pexels_api_key: str
    pexels_enabled: bool
    pexels_video_enabled: bool
    pexels_max_clips: int
    pexels_orientation: str
    pexels_size: str
    pexels_locale: str
    trend_geo: str
    trend_language: str
    channel_niche: list[str]
    video_format: str
    video_width: int
    video_height: int
    video_duration_seconds: int
    video_fps: int
    video_bitrate: str
    audio_sample_rate: int
    audio_target_lufs: float
    voice_engine: str
    voice_name: str
    voice_rate: str
    voice_pitch: str
    music_enabled: bool
    music_volume: float
    sfx_enabled: bool
    presenter_enabled: bool
    presenter_style: str
    presenter_asset: Path
    seedance2_enabled: bool
    seedance2_api_key: str
    seedance2_base_url: str
    seedance2_model: str
    seedance2_duration_seconds: int
    youtube_upload_enabled: bool
    youtube_client_secrets: Path
    youtube_token_file: Path
    youtube_privacy_status: str
    youtube_category_id: str
    youtube_default_language: str
    youtube_made_for_kids: bool
    youtube_contains_synthetic_media: bool
    telegram_bot_token: str
    telegram_allowed_chat_ids: list[int]
    telegram_owner_chat_ids: list[int]
    telegram_admin_chat_ids: list[int]
    telegram_poll_timeout: int
    telegram_send_video_max_mb: int
    secure_bot_max_daily_renders: int
    secure_bot_max_daily_uploads: int
    secure_bot_require_upload_approval: bool
    secure_bot_fast_render: bool
    secure_bot_instance_lock_port: int
    strategy_path: Path
    advanced_rendering: bool
    cinematic_intensity: float
    particle_density: float

    @property
    def outputs_dir(self) -> Path:
        return self.project_root / "outputs"


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")

    def env_path(name: str, default: str) -> Path:
        raw = os.getenv(name, default)
        path = Path(raw)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    niche = os.getenv("CHANNEL_NICHE", "tech explainers,AI tools,science")
    return Settings(
        project_root=PROJECT_ROOT,
        nvidia_api_key=os.getenv("NVIDIA_API_KEY", "").strip(),
        nvidia_base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/"),
        nvidia_model=os.getenv("NVIDIA_MODEL", "mistralai/mistral-large-3-675b-instruct-2512").strip(),
        nvidia_fallback_model=os.getenv("NVIDIA_FALLBACK_MODEL", "nvidia/nemotron-3-super-120b-a12b").strip(),
        nvidia_image_enabled=truthy(os.getenv("NVIDIA_IMAGE_ENABLED"), default=False),
        nvidia_image_model=os.getenv("NVIDIA_IMAGE_MODEL", "black-forest-labs/flux-1-dev").strip(),
        nvidia_video_enabled=truthy(os.getenv("NVIDIA_VIDEO_ENABLED"), default=False),
        nvidia_video_base_url=os.getenv("NVIDIA_VIDEO_BASE_URL", "https://ai.api.nvidia.com/v1").strip().rstrip("/"),
        nvidia_video_model=os.getenv("NVIDIA_VIDEO_MODEL", "stabilityai/stable-video-diffusion").strip(),
        nvidia_video_max_scenes=int(os.getenv("NVIDIA_VIDEO_MAX_SCENES", "2")),
        nvidia_video_duration=int(os.getenv("NVIDIA_VIDEO_DURATION", "8")),
        nvidia_video_cfg_scale=float(os.getenv("NVIDIA_VIDEO_CFG_SCALE", "1.8")),
        nvidia_video_motion_bucket_id=int(os.getenv("NVIDIA_VIDEO_MOTION_BUCKET_ID", "127")),
        nvidia_audio_enabled=truthy(os.getenv("NVIDIA_AUDIO_ENABLED"), default=False),
        nvidia_audio_base_url=os.getenv("NVIDIA_AUDIO_BASE_URL", "http://localhost:9000").strip().rstrip("/"),
        nvidia_audio_model=os.getenv("NVIDIA_AUDIO_MODEL", "riva-tts").strip(),
        nvidia_audio_voice=os.getenv("NVIDIA_AUDIO_VOICE", "English-US.Female-1").strip(),
        google_ai_api_key=os.getenv("GOOGLE_AI_API_KEY", "").strip(),
        google_video_enabled=False,
        google_video_base_url=os.getenv("GOOGLE_VIDEO_BASE_URL", "https://generativelanguage.googleapis.com/v1beta").strip().rstrip("/"),
        google_video_model=os.getenv("GOOGLE_VIDEO_MODEL", "veo-3.1-generate-preview").strip(),
        google_video_max_scenes=int(os.getenv("GOOGLE_VIDEO_MAX_SCENES", "1")),
        google_video_duration_seconds=int(os.getenv("GOOGLE_VIDEO_DURATION_SECONDS", "8")),
        google_video_aspect_ratio=os.getenv("GOOGLE_VIDEO_ASPECT_RATIO", "9:16").strip(),
        google_video_resolution=os.getenv("GOOGLE_VIDEO_RESOLUTION", "720p").strip(),
        google_video_mode=os.getenv("GOOGLE_VIDEO_MODE", "text_to_video").strip().lower(),
        google_video_poll_seconds=int(os.getenv("GOOGLE_VIDEO_POLL_SECONDS", "10")),
        google_video_timeout_seconds=int(os.getenv("GOOGLE_VIDEO_TIMEOUT_SECONDS", "900")),
        pexels_api_key=os.getenv("PEXELS_API_KEY", "").strip(),
        pexels_enabled=truthy(os.getenv("PEXELS_ENABLED"), default=False),
        pexels_video_enabled=truthy(os.getenv("PEXELS_VIDEO_ENABLED"), default=True),
        pexels_max_clips=int(os.getenv("PEXELS_MAX_CLIPS", "6")),
        pexels_orientation=os.getenv("PEXELS_ORIENTATION", "portrait").strip().lower(),
        pexels_size=os.getenv("PEXELS_SIZE", "medium").strip().lower(),
        pexels_locale=os.getenv("PEXELS_LOCALE", "en-US").strip(),
        trend_geo=os.getenv("TREND_GEO", "US").strip().upper(),
        trend_language=os.getenv("TREND_LANGUAGE", "en").strip(),
        channel_niche=[item.strip() for item in niche.split(",") if item.strip()],
        video_format=os.getenv("VIDEO_FORMAT", "shorts").strip().lower(),
        video_width=int(os.getenv("VIDEO_WIDTH", "1080")),
        video_height=int(os.getenv("VIDEO_HEIGHT", "1920")),
        video_duration_seconds=int(os.getenv("VIDEO_DURATION_SECONDS", "58")),
        video_fps=int(os.getenv("VIDEO_FPS", "30")),
        video_bitrate=os.getenv("VIDEO_BITRATE", "15000k").strip(),
        audio_sample_rate=int(os.getenv("AUDIO_SAMPLE_RATE", "48000")),
        audio_target_lufs=float(os.getenv("AUDIO_TARGET_LUFS", "-14")),
        voice_engine=os.getenv("VOICE_ENGINE", "edge").strip().lower(),
        voice_name=os.getenv("VOICE_NAME", "en-US-GuyNeural").strip(),
        voice_rate=os.getenv("VOICE_RATE", "+7%").strip(),
        voice_pitch=os.getenv("VOICE_PITCH", "-2Hz").strip(),
        music_enabled=truthy(os.getenv("MUSIC_ENABLED"), default=True),
        music_volume=float(os.getenv("MUSIC_VOLUME", "0.18")),
        sfx_enabled=truthy(os.getenv("SFX_ENABLED"), default=True),
        presenter_enabled=truthy(os.getenv("PRESENTER_ENABLED"), default=True),
        presenter_style=os.getenv("PRESENTER_STYLE", "cinematic_host").strip(),
        presenter_asset=env_path("PRESENTER_ASSET", "assets/presenter-human.png"),
        seedance2_enabled=truthy(os.getenv("SEEDANCE2_ENABLED"), default=False),
        seedance2_api_key=os.getenv("SEEDANCE2_API_KEY", "").strip(),
        seedance2_base_url=os.getenv("SEEDANCE2_BASE_URL", "").strip(),
        seedance2_model=os.getenv("SEEDANCE2_MODEL", "seedance-2.0").strip(),
        seedance2_duration_seconds=int(os.getenv("SEEDANCE2_DURATION_SECONDS", "8")),
        youtube_upload_enabled=truthy(os.getenv("YOUTUBE_UPLOAD_ENABLED"), default=False),
        youtube_client_secrets=env_path("YOUTUBE_CLIENT_SECRETS", "credentials/client_secret.json"),
        youtube_token_file=env_path("YOUTUBE_TOKEN_FILE", "credentials/youtube_token.json"),
        youtube_privacy_status=os.getenv("YOUTUBE_PRIVACY_STATUS", "private").strip(),
        youtube_category_id=os.getenv("YOUTUBE_CATEGORY_ID", "28").strip(),
        youtube_default_language=os.getenv("YOUTUBE_DEFAULT_LANGUAGE", "en").strip(),
        youtube_made_for_kids=truthy(os.getenv("YOUTUBE_SELF_DECLARED_MADE_FOR_KIDS"), default=False),
        youtube_contains_synthetic_media=truthy(os.getenv("YOUTUBE_CONTAINS_SYNTHETIC_MEDIA"), default=False),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_allowed_chat_ids=_int_list(os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")),
        telegram_owner_chat_ids=_int_list(os.getenv("TELEGRAM_OWNER_CHAT_IDS", "")),
        telegram_admin_chat_ids=_int_list(os.getenv("TELEGRAM_ADMIN_CHAT_IDS", "")),
        telegram_poll_timeout=int(os.getenv("TELEGRAM_POLL_TIMEOUT", "25")),
        telegram_send_video_max_mb=int(os.getenv("TELEGRAM_SEND_VIDEO_MAX_MB", "45")),
        secure_bot_max_daily_renders=int(os.getenv("SECURE_BOT_MAX_DAILY_RENDERS", "6")),
        secure_bot_max_daily_uploads=int(os.getenv("SECURE_BOT_MAX_DAILY_UPLOADS", "3")),
        secure_bot_require_upload_approval=truthy(os.getenv("SECURE_BOT_REQUIRE_UPLOAD_APPROVAL"), default=True),
        secure_bot_fast_render=truthy(os.getenv("SECURE_BOT_FAST_RENDER"), default=True),
        secure_bot_instance_lock_port=int(os.getenv("SECURE_BOT_INSTANCE_LOCK_PORT", "48642")),
        strategy_path=env_path("STRATEGY_PATH", "config/strategy.json"),
        advanced_rendering=truthy(os.getenv("ADVANCED_RENDERING"), default=True),
        cinematic_intensity=float(os.getenv("CINEMATIC_INTENSITY", "0.85")),
        particle_density=float(os.getenv("PARTICLE_DENSITY", "1.0")),
    )


def load_strategy(settings: Settings) -> dict[str, Any]:
    if settings.strategy_path.exists():
        strategy = read_json(settings.strategy_path)
    else:
        strategy = {}
    strategy.setdefault("geo", settings.trend_geo)
    strategy.setdefault("language", settings.trend_language)
    strategy.setdefault("niches", settings.channel_niche)
    strategy.setdefault("google_news_queries", settings.channel_niche)
    strategy.setdefault("subreddits", [])
    strategy.setdefault("blocked_terms", [])
    strategy.setdefault("source_weights", {})
    strategy.setdefault("growth_strategy", {})
    return strategy


def _int_list(value: str) -> list[int]:
    result: list[int] = []
    for item in value.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.append(int(item))
        except ValueError:
            continue
    return result
