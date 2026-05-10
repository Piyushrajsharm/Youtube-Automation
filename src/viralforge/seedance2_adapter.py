from __future__ import annotations

from pathlib import Path

from .config import Settings
from .models import ScenePlan
from .utils import write_json


def seedance2_manifest(scene_plans: list[ScenePlan], output_dir: Path, settings: Settings) -> Path | None:
    jobs = []
    for scene in scene_plans:
        if not any(item.get("provider") == "seedance2" for item in scene.skill_profile.get("external_video", [])):
            continue
        jobs.append(
            {
                "scene_id": scene.scene_id,
                "provider": "seedance2",
                "enabled": settings.seedance2_enabled,
                "model": settings.seedance2_model,
                "base_url": settings.seedance2_base_url,
                "duration_seconds": min(settings.seedance2_duration_seconds, max(4, round(scene.duration_seconds))),
                "aspect_ratio": "9:16",
                "prompt": scene.cinematic_prompt,
                "negative_prompt": (
                    "copyrighted characters, celebrity likeness, real brand logos, copied movie scenes, "
                    "low quality, distorted hands, unreadable text, watermark"
                ),
                "continuity_notes": {
                    "character": scene.character,
                    "location": scene.location,
                    "lighting": scene.lighting,
                    "selected_skills": scene.selected_skills,
                },
            }
        )
    if not jobs:
        return None
    path = output_dir / "seedance2_jobs.json"
    write_json(
        path,
        {
            "status": "manifest_only" if not settings.seedance2_enabled else "ready_for_provider_adapter",
            "note": "No API key is written here. Wire this manifest to your chosen Seedance 2 provider endpoint.",
            "jobs": jobs,
        },
    )
    return path
