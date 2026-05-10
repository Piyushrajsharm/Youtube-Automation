from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from .config import Settings
from .google_video_client import GoogleVeoClient, GoogleVideoProviderError
from .models import ScenePlan
from .utils import write_json


SeedFrameBuilder = Callable[[ScenePlan, int], np.ndarray]


def generate_google_videos(
    scene_plans: list[ScenePlan],
    output_dir: Path,
    settings: Settings,
    seed_frame_builder: SeedFrameBuilder | None = None,
) -> dict[str, Path]:
    report_path = output_dir / "google_video_report.json"
    report: dict[str, object] = {
        "enabled": bool(settings.google_video_enabled),
        "provider": "google_veo",
        "model": settings.google_video_model,
        "mode": settings.google_video_mode,
        "aspect_ratio": settings.google_video_aspect_ratio,
        "duration_seconds": settings.google_video_duration_seconds,
        "resolution": settings.google_video_resolution,
        "requested_scenes": 0,
        "generated_scenes": 0,
        "fallback_used": False,
        "items": [],
    }
    if not settings.google_video_enabled:
        write_json(report_path, report)
        return {}
    if not settings.google_ai_api_key:
        report["fallback_used"] = True
        report["items"] = [{"status": "skipped", "reason": "GOOGLE_AI_API_KEY is not configured."}]
        write_json(report_path, report)
        return {}

    eligible = _eligible_scenes(scene_plans, settings.google_video_max_scenes)
    report["requested_scenes"] = len(eligible)
    if not eligible:
        report["items"] = [{"status": "skipped", "reason": "No eligible cinematic scenes."}]
        write_json(report_path, report)
        return {}

    client = GoogleVeoClient(settings)
    results: dict[str, Path] = {}
    items: list[dict[str, object]] = []
    for index, scene in enumerate(eligible):
        prompt = _veo_prompt(scene)
        item: dict[str, object] = {
            "scene_id": scene.scene_id,
            "status": "pending",
            "prompt": prompt,
        }
        try:
            output_path = output_dir / f"{scene.scene_id}_google_veo.mp4"
            if settings.google_video_mode in {"image_to_video", "image"}:
                frame = (
                    seed_frame_builder(scene, index)
                    if seed_frame_builder
                    else _fallback_seed_frame(settings.video_width, settings.video_height)
                )
                image_bytes = _jpeg_seed_bytes(frame)
                seed_path = output_dir / f"{scene.scene_id}_google_seed.jpg"
                seed_path.write_bytes(image_bytes)
                item["seed_frame"] = str(seed_path)
                item["seed_frame_bytes"] = len(image_bytes)
                client.generate_image_video(
                    prompt,
                    image_bytes=image_bytes,
                    mime_type="image/jpeg",
                    output_path=output_path,
                )
            else:
                client.generate_text_video(prompt, output_path=output_path)
            item["status"] = "generated"
            item["video_path"] = str(output_path)
            item["video_bytes"] = output_path.stat().st_size
            results[scene.scene_id] = output_path
        except GoogleVideoProviderError as exc:
            item["status"] = "provider_failed"
            item["status_code"] = exc.status_code
            item["error"] = str(exc)
            items.append(item)
            if exc.status_code in {400, 401, 403, 404, 429}:
                break
            continue
        except Exception as exc:
            item["status"] = "failed"
            item["error"] = f"{type(exc).__name__}: {exc}"
        items.append(item)

    report["generated_scenes"] = len(results)
    report["fallback_used"] = len(results) < len(eligible)
    report["items"] = items
    write_json(report_path, report)
    return results


def _eligible_scenes(scene_plans: list[ScenePlan], limit: int) -> list[ScenePlan]:
    priority = {"hook": 0, "warning": 1, "reveal": 2, "cta": 3}
    ranked = sorted(
        scene_plans,
        key=lambda scene: (
            priority.get(scene.purpose, 9),
            -len(scene.broll_clips),
            scene.start_time,
        ),
    )
    return ranked[: max(0, limit)]


def _veo_prompt(scene: ScenePlan) -> str:
    human_action = _human_action(scene)
    no_text = (
        "Do not show readable on-screen text, logos, watermarks, subtitles, UI brand names, "
        "celebrity likenesses, or copied movie scenes."
    )
    return (
        f"Create an original vertical 9:16 cinematic social video shot with native audio.\n"
        f"Scene purpose: {scene.purpose}. Emotion: {scene.emotion}.\n"
        f"Main subject: a realistic adult tech founder presenter inside {scene.location}.\n"
        f"Action: {human_action} The presenter uses full-body movement, head turns, natural hand gestures, "
        f"eye contact, subtle walking/weight shifts, and expressive facial performance while explaining: "
        f"\"{scene.narration}\"\n"
        f"Environment: {scene.background}; {scene.atmosphere}.\n"
        f"Visual metaphor: {', '.join(str(item) for item in scene.visual_metaphor.get('objects', [])[:5])}.\n"
        f"Camera: {scene.camera_motion}; include push-in, parallax, depth of field, and a clear camera angle change.\n"
        f"Lighting: {scene.lighting}. VFX: {', '.join(scene.vfx[:8])}.\n"
        f"Audio: energetic cinematic tech trailer bed, crisp human voice, subtle whooshes and UI hits synced to motion.\n"
        f"Style: premium realistic AI video generation, high-retention YouTube Short, cinematic but copyright-safe. {no_text}"
    )


def _human_action(scene: ScenePlan) -> str:
    if scene.purpose == "warning":
        return "The presenter steps forward as red permission warnings pulse around a digital vault."
    if scene.purpose == "cta":
        return "The presenter turns toward camera, raises one hand toward a floating digital key, and ends in a hero stance."
    if scene.purpose == "reveal":
        return "The presenter walks beside a holographic task wall while cards animate and transform into completed work."
    return "The presenter enters frame from the side, turns to camera, and gestures toward a holographic AI employee badge."


def _jpeg_seed_bytes(frame: np.ndarray) -> bytes:
    image = Image.fromarray(np.asarray(frame, dtype=np.uint8)).convert("RGB")
    image.thumbnail((768, 1365), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=86, optimize=True)
    return buffer.getvalue()


def _fallback_seed_frame(width: int, height: int) -> np.ndarray:
    image = Image.new("RGB", (width, height), (5, 9, 18))
    return np.asarray(image)
