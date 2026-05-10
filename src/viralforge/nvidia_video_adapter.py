from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .config import Settings
from .models import ScenePlan
from .nvidia_client import NvidiaProviderError, NvidiaUnifiedClient
from .utils import write_json


SeedFrameBuilder = Callable[[ScenePlan, int], np.ndarray]


def generate_nvidia_videos(
    scene_plans: list[ScenePlan],
    output_dir: Path,
    settings: Settings,
    seed_frame_builder: SeedFrameBuilder | None = None,
) -> dict[str, Path]:
    """Generate NVIDIA image-to-video clips for eligible scenes.

    This adapter intentionally uses NVIDIA's visual GenAI image-to-video
    endpoint. It never routes video prompts through a chat/completions model.
    When the account lacks entitlement to the visual endpoint, the caller gets a
    report and the local cinematic renderer continues as fallback.
    """
    report_path = output_dir / "nvidia_provider_report.json"
    report: dict[str, object] = {
        "enabled": bool(settings.nvidia_video_enabled),
        "provider": "nvidia",
        "model": settings.nvidia_video_model,
        "base_url": settings.nvidia_video_base_url,
        "mode": "image_to_video",
        "requested_scenes": 0,
        "generated_scenes": 0,
        "fallback_used": False,
        "access_blocked": False,
        "items": [],
    }

    if not settings.nvidia_video_enabled:
        write_json(report_path, report)
        return {}
    if not settings.nvidia_api_key:
        report["fallback_used"] = True
        report["items"] = [{"status": "skipped", "reason": "NVIDIA_API_KEY is not configured."}]
        write_json(report_path, report)
        return {}

    eligible = _eligible_scenes(scene_plans, settings.nvidia_video_max_scenes)
    report["requested_scenes"] = len(eligible)
    if not eligible:
        report["items"] = [{"status": "skipped", "reason": "No eligible scenes in the plan."}]
        write_json(report_path, report)
        return {}

    client = NvidiaUnifiedClient(settings)
    results: dict[str, Path] = {}
    items: list[dict[str, object]] = []

    for index, scene in enumerate(eligible):
        item: dict[str, object] = {
            "scene_id": scene.scene_id,
            "status": "pending",
            "model": settings.nvidia_video_model,
            "prompt": scene.cinematic_prompt,
        }
        try:
            seed_frame = (
                seed_frame_builder(scene, index)
                if seed_frame_builder
                else _fallback_seed_frame(scene, settings.video_width, settings.video_height)
            )
            seed_path = output_dir / f"{scene.scene_id}_nvidia_seed.jpg"
            image_data_uri = image_data_uri_from_frame(seed_frame, seed_path)
            item["seed_frame"] = str(seed_path)
            item["seed_frame_bytes"] = seed_path.stat().st_size if seed_path.exists() else 0

            video_bytes = client.generate_video_from_image(
                image_data_uri,
                prompt=scene.cinematic_prompt,
                seed=_stable_seed(scene.scene_id, scene.cinematic_prompt),
                cfg_scale=settings.nvidia_video_cfg_scale,
                motion_bucket_id=settings.nvidia_video_motion_bucket_id,
            )
            output_path = output_dir / f"{scene.scene_id}_nvidia.mp4"
            output_path.write_bytes(video_bytes)
            item["status"] = "generated"
            item["video_path"] = str(output_path)
            item["video_bytes"] = output_path.stat().st_size
            results[scene.scene_id] = output_path
        except NvidiaProviderError as exc:
            item["status"] = "provider_failed"
            item["status_code"] = exc.status_code
            item["error"] = str(exc)
            if exc.status_code in {401, 403, 404}:
                report["access_blocked"] = True
                items.append(item)
                break
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
    eligible = [
        scene
        for scene in scene_plans
        if any(
            item.get("provider") == "nvidia"
            for item in scene.skill_profile.get("external_video", [])
        )
    ]
    if not eligible:
        eligible = [
            scene
            for scene in scene_plans
            if scene.purpose in {"hook", "reveal", "warning", "cta"} or scene.broll_clips
        ]
    return eligible[: max(0, limit)]


def image_data_uri_from_frame(frame: np.ndarray, output_path: Path, *, max_bytes: int = 198_000) -> str:
    """Save a NVIDIA-compatible seed JPEG and return a data URI.

    NVIDIA's hosted Stable Video Diffusion API documents inline image payloads
    below 200KB. The input frame is adapted to a 16:9 1024x576 seed by keeping
    the vertical frame intact in the center over a blurred fill background.
    """
    image = Image.fromarray(np.asarray(frame, dtype=np.uint8)).convert("RGB")
    seed = _compose_svd_seed(image)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    encoded = b""
    for quality in (78, 72, 66, 60, 54, 48, 42):
        buffer = BytesIO()
        seed.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
        encoded = buffer.getvalue()
        if len(encoded) <= max_bytes:
            break
    output_path.write_bytes(encoded)
    return "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii")


def _compose_svd_seed(image: Image.Image) -> Image.Image:
    target_w, target_h = 1024, 576
    return _fit_vertical_frame_for_svd(image, target_w, target_h)


def _fit_vertical_frame_for_svd(image: Image.Image, target_w: int, target_h: int) -> Image.Image:
    background = image.copy()
    background.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
    scale = max(target_w / max(1, background.width), target_h / max(1, background.height))
    background = background.resize(
        (int(background.width * scale), int(background.height * scale)),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (background.width - target_w) // 2)
    top = max(0, (background.height - target_h) // 2)
    background = background.crop((left, top, left + target_w, top + target_h))
    background = background.filter(ImageFilter.GaussianBlur(18))

    foreground = image.copy()
    foreground.thumbnail((int(target_w * 0.42), target_h), Image.Resampling.LANCZOS)
    canvas = background.convert("RGBA")
    shadow = Image.new("RGBA", foreground.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow, "RGBA")
    shadow_draw.rounded_rectangle(
        (0, 0, foreground.width, foreground.height),
        radius=28,
        fill=(0, 0, 0, 92),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    x = (target_w - foreground.width) // 2
    y = (target_h - foreground.height) // 2
    canvas.alpha_composite(shadow, (x + 6, y + 8))
    canvas.paste(foreground.convert("RGBA"), (x, y))
    return canvas.convert("RGB")


def _fallback_seed_frame(scene: ScenePlan, width: int, height: int) -> np.ndarray:
    image = Image.new("RGB", (width, height), (6, 10, 20))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, height), fill=(5, 9, 19))
    for step in range(0, height, 90):
        color = (0, 220, 210) if step % 180 else (255, 190, 70)
        draw.line((0, step, width, step + width * 0.12), fill=(*color, 42), width=3)
    draw.rounded_rectangle((width * 0.1, height * 0.28, width * 0.9, height * 0.58), radius=42, outline=(0, 245, 212), width=4)
    draw.text((width * 0.14, height * 0.35), scene.headline_text[:54], fill=(255, 255, 255))
    return np.asarray(image)


def _stable_seed(scene_id: str, prompt: str) -> int:
    digest = hashlib.sha256(f"{scene_id}:{prompt}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 2_147_483_647
