from __future__ import annotations

from .models import RetentionReport, ScenePlan


RETENTION_RULES = {
    "visual_change_every_seconds": 2.5,
    "hook_must_appear_before": 1.0,
    "no_static_scene_longer_than": 2.5,
    "cta_required": True,
}


def check_retention(scene_plans: list[ScenePlan]) -> RetentionReport:
    flags: list[str] = []
    recommendations: list[str] = []
    if not scene_plans:
        return RetentionReport(False, ["No scene plan was generated."], ["Generate a timed scene plan first."])

    if scene_plans[0].start_time > RETENTION_RULES["hook_must_appear_before"]:
        flags.append("Hook starts too late.")
        recommendations.append("Move the hook before the first second.")

    for scene in scene_plans:
        if scene.duration_seconds > RETENTION_RULES["no_static_scene_longer_than"] and len(scene.shot_types) < 2:
            flags.append(f"{scene.scene_id} is too static for {scene.duration_seconds:.1f}s.")
            recommendations.append("Add cutaways, zooms, UI changes, or pattern interrupts.")
        if not scene.animation_events:
            flags.append(f"{scene.scene_id} has no animation events.")
        if not scene.retention_events:
            flags.append(f"{scene.scene_id} has no retention edit events.")
        if not scene.location or not scene.foreground_elements:
            flags.append(f"{scene.scene_id} has no cinematic world staging.")
        if scene.duration_seconds / max(1, len(scene.shot_types)) > RETENTION_RULES["visual_change_every_seconds"]:
            flags.append(f"{scene.scene_id} changes visuals too slowly.")

    if RETENTION_RULES["cta_required"] and scene_plans[-1].purpose != "cta":
        flags.append("Final scene is not marked as CTA.")
        recommendations.append("End with a direct question or action.")

    passed = not flags
    if passed:
        recommendations.append("Retention structure passed: hook, pattern interrupts, cutaways, and CTA are present.")
    return RetentionReport(passed, flags, recommendations)
