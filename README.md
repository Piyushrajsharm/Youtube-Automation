---
title: Youtube Automation Bot
emoji: 🎥
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
---

# ViralForge

ViralForge is a local automation pipeline for creating original animated YouTube videos from current trend signals. It discovers trend candidates, researches source snippets, uses NVIDIA NIM for strategy/script generation when configured, renders a stylized animated video, prepares YouTube metadata, runs a compliance audit, and can upload through the YouTube Data API.

It is intentionally private-by-default. Uploads are disabled unless you configure OAuth and pass `--upload`.

## What It Does

- Finds trend candidates from Google Trends RSS, Google News RSS, Reddit hot feeds, and Hacker News.
- Uses NVIDIA's OpenAI-compatible NIM chat endpoint for topic angle, script, scene, and metadata generation.
- Can attempt NVIDIA Visual GenAI image-to-video through Stable Video Diffusion when the account has access to that endpoint; otherwise it writes `nvidia_provider_report.json` and falls back to the local renderer.
- Can attempt NVIDIA Speech NIM TTS through a configured `/v1/audio/synthesize` endpoint; otherwise it writes `nvidia_audio_report.json` and falls back to the configured local/Edge voice engine.
- Can attempt Google AI Studio / Gemini API Veo video generation through `predictLongRunning`, poll the async operation, download the returned MP4, and composite successful clips into the final render.
- Can search and download Pexels commercial-use stock videos for cinematic B-roll, score clips by relevance/resolution/orientation/duration, and write a `pexels_report.json` source/license manifest.
- Produces original cinematic animated visuals with generated worlds, visual metaphors, motion, captions, and optional local text-to-speech narration.
- Converts scripts into a timed `scene_plan.json` with purpose, location, foreground/midground/background staging, `shot_sequence`, B-roll clips, camera emotion, caption plan, character integration, VFX layers, voice direction, SFX cues, transitions, and quality scores.
- Selects 3-5 modular cinematic skills per scene, expands them into camera/lighting/VFX/edit/voice/audio instructions, and writes `skill_quality.json`.
- Adds cinematic camera presets, kinetic captions, procedural B-roll micro-scenes, depth compositing, sound design, music, retention edit events, `seedance2_jobs.json` manifests, `scene_quality.json`, and a `cinematic_score.json` gate that must pass before rendering.
- Avoids scraped third-party clips, images, music, logos, celebrity likeness, and cloned voices.
- Writes a full package per video: trends, research notes, plan, metadata, compliance report, thumbnail, MP4, and upload result.
- Uploads with YouTube OAuth, `privacyStatus`, `selfDeclaredMadeForKids`, and `containsSyntheticMedia` fields.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -e .
Copy-Item .env.example .env
```

Open `.env` and set:

```ini
NVIDIA_API_KEY=your_rotated_key_here
```

The NVIDIA key pasted in chat should be rotated because it is now exposed. Do not commit `.env`.

The default planning model is:

```ini
NVIDIA_MODEL=mistralai/mistral-large-3-675b-instruct-2512
```

Other powerful models your NVIDIA endpoint may expose include `qwen/qwen3.5-397b-a17b`, `deepseek-ai/deepseek-v4-pro`, and `nvidia/nemotron-3-super-120b-a12b`. Prefer a model that is both high quality and responsive; very large models can time out during automation runs.

Rendering now supports a stylized animated presenter:

```ini
PRESENTER_ENABLED=true
PRESENTER_STYLE=cinematic_host
PRESENTER_ASSET=assets/presenter-human.png
VOICE_ENGINE=edge
MUSIC_ENABLED=true
```

The presenter can use a generated original photoreal human asset, not a real person or cloned likeness. The renderer adds a local presenter rig with head turns, breathing, blink frames, eye highlights, and mouth motion during narrated lines. Background scenes now react to script intent with cinematic worlds such as command rooms, vaults, review cockpits, hologram chambers, keys, shields, task lanes, particles, fog, light beams, glitches, and impact flashes. The full script is voiceover-only; the video shows center-screen keywords instead of a bottom transcript box.

Narration is generated as a timed scene track (`narration_timed.wav`) so voice lines are placed at their scene timestamps instead of ending early while the video continues.

The cinematic skill registry lives in `src/viralforge/skill_registry.py`. Skills are concrete behavior packs such as `cold_open`, `hero_reveal`, `danger_alert`, `montage_burst`, `safe_control`, `epic_cta`, and `seedance2_prompt_package`; they are selected by `skill_selector.py` and expanded by `skill_expander.py`.

The AI-video-level shot system lives in `shot_director.py`, `broll_engine.py`, `caption_cleaner.py`, `depth_compositor.py`, and `scene_quality_checker.py`. It enforces a visible scene change every four seconds, inserts procedural micro-scenes such as AI offices, vault access, human review, chaos dashboards, server rooms, and final hero systems, cleans headlines to short trailer lines, and rejects scenes below an 80 quality score.

Optional Seedance 2 style video-generation manifests:

```ini
SEEDANCE2_ENABLED=false
SEEDANCE2_API_KEY=
SEEDANCE2_BASE_URL=
SEEDANCE2_MODEL=seedance-2.0
SEEDANCE2_DURATION_SECONDS=8
```

When Seedance skills are selected, ViralForge writes `seedance2_jobs.json` with per-scene prompts, continuity notes, negative prompts, aspect ratio, and duration. It does not store or print the API key.

Optional NVIDIA image-to-video:

```ini
NVIDIA_VIDEO_ENABLED=true
NVIDIA_VIDEO_BASE_URL=https://ai.api.nvidia.com/v1
NVIDIA_VIDEO_MODEL=stabilityai/stable-video-diffusion
NVIDIA_VIDEO_MAX_SCENES=2
NVIDIA_VIDEO_CFG_SCALE=1.8
NVIDIA_VIDEO_MOTION_BUCKET_ID=127
```

This path uses the documented image-to-video endpoint, not `chat/completions`. ViralForge creates a seed frame for each eligible cinematic scene, compresses it under NVIDIA's inline image limit, sends it to the provider, and composites successful returned clips into the final MP4. If the NVIDIA account is not entitled to the visual endpoint, the render continues locally and the provider error is recorded.

Optional NVIDIA Speech NIM TTS:

```ini
NVIDIA_AUDIO_ENABLED=true
NVIDIA_AUDIO_BASE_URL=http://localhost:9000
NVIDIA_AUDIO_MODEL=magpie-tts-multilingual
NVIDIA_AUDIO_VOICE=Magpie-Multilingual.EN-US.Aria
```

Speech NIM TTS is typically a deployed NVIDIA NIM container or endpoint. The hosted LLM key alone may not expose TTS in `/v1/models`.

Optional Google AI Studio Veo video generation:

```ini
GOOGLE_AI_API_KEY=
GOOGLE_VIDEO_ENABLED=true
GOOGLE_VIDEO_MODEL=veo-3.1-generate-preview
GOOGLE_VIDEO_MAX_SCENES=1
GOOGLE_VIDEO_DURATION_SECONDS=8
GOOGLE_VIDEO_ASPECT_RATIO=9:16
GOOGLE_VIDEO_RESOLUTION=720p
GOOGLE_VIDEO_MODE=text_to_video
```

ViralForge uses the Gemini API `models/{model}:predictLongRunning` route, polls the operation until completion, and downloads the generated video URI with the API key. Use `GOOGLE_VIDEO_MODE=text_to_video` when you want the provider to create a moving presenter and scene from scratch.

Optional Pexels B-roll:

```ini
PEXELS_API_KEY=
PEXELS_ENABLED=true
PEXELS_VIDEO_ENABLED=true
PEXELS_MAX_CLIPS=6
PEXELS_ORIENTATION=portrait
PEXELS_SIZE=medium
PEXELS_LOCALE=en-US
```

Pexels footage is searched through the official `/v1/videos/search` API, downloaded into the output package, and transformed with original narration, captions, music, sound design, color, and edits. The output package includes every selected Pexels URL, creator profile, download quality, and license note.

Production export defaults:

```ini
VIDEO_WIDTH=1080
VIDEO_HEIGHT=1920
VIDEO_FPS=30
VIDEO_BITRATE=15000k
AUDIO_SAMPLE_RATE=48000
AUDIO_TARGET_LUFS=-14
SFX_ENABLED=true
```

Set `VIDEO_FPS=60` for smoother motion if render time is acceptable.

## Create A Video Package

Discover trends:

```powershell
.\.venv\Scripts\viralforge discover --limit 12
```

Create a video from the top trend:

```powershell
.\.venv\Scripts\viralforge run
```

Create a video for a specific topic:

```powershell
.\.venv\Scripts\viralforge run --topic "AI agents in small businesses"
```

Generate plan and metadata only:

```powershell
.\.venv\Scripts\viralforge run --no-render
```

Each run creates a folder under `outputs/`.

## Full Autopilot

Run the full trend-to-video automation once:

```powershell
.\.venv\Scripts\viralforge autopilot
```

Run multiple private-first packages in one session:

```powershell
.\.venv\Scripts\viralforge autopilot --count 3 --interval-minutes 45
```

The autopilot command:

- Discovers current tech-related trends across news, Reddit, Hacker News, and format queries.
- Skips topics already recorded in `outputs/automation_state.json`.
- Builds research notes, a copyright-safe script, cinematic scene plan, metadata, hashtags, compliance report, thumbnail, and MP4.
- Blocks upload when compliance fails unless you intentionally pass `--force-upload`.
- Keeps upload off unless you pass `--upload` and YouTube OAuth is linked.

Convenience wrapper:

```powershell
.\scripts\run_autopilot.ps1 -Count 1
```

Install a daily Windows Task Scheduler job:

```powershell
.\scripts\install_windows_autopilot_task.ps1 -DailyTime "09:00"
```

Add `-Upload` only after OAuth is linked and you are comfortable with private uploads:

```powershell
.\scripts\install_windows_autopilot_task.ps1 -DailyTime "09:00" -Upload
```

For true 24/7 operation while your laptop is shut down, deploy this project on an always-on VPS or server. Use the Docker/systemd guide in [docs/24_7_DEPLOYMENT.md](docs/24_7_DEPLOYMENT.md).

## Telegram Control

Create a private Telegram control bot so you can trigger automation from your phone:

```powershell
.\.venv\Scripts\python.exe -m viralforge.cli telegram-bot
```

Available commands include `/discover`, `/plan [topic]`, `/run [topic]`, `/run_upload [topic]`, `/upload_latest`, `/status`, and `/id`.

Setup guide: [docs/TELEGRAM_CONTROL.md](docs/TELEGRAM_CONTROL.md).

For the separate production-grade bot with roles, queued jobs, approval buttons, rate limits, and audit logs, use:

```powershell
.\.venv\Scripts\python.exe -m viralforge.cli secure-bot
```

Secure bot guide: [docs/SECURE_BOT.md](docs/SECURE_BOT.md).

## Hugging Face Space Deployment

This repository is configured as a Docker Space. The Space starts a FastAPI health endpoint and launches exactly one secure Telegram bot supervisor in the background.

Set these Hugging Face Space Secrets before relying on the hosted bot:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_OWNER_CHAT_IDS
NVIDIA_API_KEY
PEXELS_API_KEY
YOUTUBE_CLIENT_SECRETS_JSON
YOUTUBE_TOKEN_JSON
YOUTUBE_UPLOAD_ENABLED=true
SECURE_BOT_REQUIRE_UPLOAD_APPROVAL=false
```

Use `YOUTUBE_CLIENT_SECRETS_JSON` for the full contents of `credentials/client_secret.json` and `YOUTUBE_TOKEN_JSON` for the full contents of `credentials/youtube_token.json`. Do not commit either JSON file.

After deploying to the Space, stop any local `secure-bot` process. Telegram long polling must have only one active bot instance, otherwise Telegram returns `409 Conflict` and messages can go to the wrong process.

## YouTube Upload Setup

1. In Google Cloud Console, create an OAuth Desktop Client for the YouTube Data API.
2. Download its JSON and save it as `credentials/client_secret.json`.
3. Keep `YOUTUBE_PRIVACY_STATUS=private` until you have manually reviewed videos.
4. Link OAuth once:

```powershell
.\.venv\Scripts\python.exe -m viralforge.cli youtube-auth
```

5. Create and upload a private video:

```powershell
.\.venv\Scripts\python.exe -m viralforge.cli run --upload
```

The OAuth flow opens a browser for consent and stores `credentials/youtube_token.json`.

## Safety And Monetization Notes

No automation can guarantee monetization approval. This project reduces risk by making the default output original, source-grounded, and private-first. Before publishing, review the generated `compliance.json`, watch the MP4, verify sources, and make sure the video matches YouTube's current policies.

Important defaults:

- No third-party media is downloaded or reused.
- The renderer uses abstract animation, not realistic fake footage.
- Hashtags are limited and factual.
- Compliance flags block uploads unless you intentionally pass `--force-upload`.
- If you add realistic synthetic scenes, cloned voices, synthetic music, or altered real-world footage, set `YOUTUBE_CONTAINS_SYNTHETIC_MEDIA=true`.

## Useful References

- NVIDIA NIM hosted LLM endpoint: https://docs.api.nvidia.com/nim/reference/llm-apis
- NVIDIA Stable Video Diffusion endpoint: https://docs.api.nvidia.com/nim/reference/stabilityai-stable-video-diffusion-infer
- NVIDIA Speech NIM TTS deployment and HTTP synthesis: https://docs.nvidia.com/nim/speech/latest/tts/deploy-tts-model.html
- Google Gemini API Veo video generation: https://ai.google.dev/gemini-api/docs/video
- Pexels API documentation: https://www.pexels.com/api/documentation/
- Pexels license: https://www.pexels.com/license/
- YouTube channel monetization and reused content policy: https://support.google.com/youtube/answer/1311392
- YouTube altered or synthetic content disclosure: https://support.google.com/youtube/answer/14328491
- YouTube video upload guide: https://developers.google.com/youtube/v3/guides/uploading_a_video
- YouTube `containsSyntheticMedia` field: https://developers.google.com/youtube/v3/docs/videos
