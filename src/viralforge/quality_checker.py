from __future__ import annotations

from .models import ScenePlan


def check_skill_quality(scene_plans: list[ScenePlan]) -> dict[str, object]:
    flags: list[str] = []
    scene_reports: list[dict[str, object]] = []
    for scene in scene_plans:
        scene_flags: list[str] = []
        if not (3 <= len(scene.selected_skills) <= 5):
            scene_flags.append("Scene should use 3-5 cinematic skills.")
        if not scene.skill_profile.get("vfx"):
            scene_flags.append("No skill VFX expansion.")
        if not scene.skill_profile.get("prompt_fragments"):
            scene_flags.append("No expanded skill prompt fragments.")
        if not scene.camera_motion:
            scene_flags.append("No camera skill applied.")
        if not scene.lighting:
            scene_flags.append("No lighting skill applied.")
        if len(scene.shot_types) < 2 and scene.duration_seconds > 2.5:
            scene_flags.append("Scene can still feel flat because shot variety is too low.")
        if scene_flags:
            flags.append(f"{scene.scene_id}: " + "; ".join(scene_flags))
        scene_reports.append(
            {
                "scene_id": scene.scene_id,
                "scene_type": scene.scene_type,
                "selected_skills": scene.selected_skills,
                "passed": not scene_flags,
                "flags": scene_flags,
            }
        )

    return {
        "passed": not flags,
        "flags": flags,
        "scene_reports": scene_reports,
    }
