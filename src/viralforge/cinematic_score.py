from __future__ import annotations

from .models import ScenePlan


def cinematic_score(scene_plans: list[ScenePlan]) -> dict[str, object]:
    score = 0
    flags: list[str] = []

    shot_names = {shot for scene in scene_plans for shot in scene.shot_types}
    has_establishing = "establishing" in shot_names
    has_closeups = bool({"hero_closeup", "character_closeup", "ui_macro", "macro_ui", "impact_reveal"} & shot_names)
    has_camera_motion_every_scene = all(scene.camera_motion for scene in scene_plans)
    has_visual_metaphors = all(scene.visual_metaphor.get("objects") for scene in scene_plans)
    has_vfx_layers = all(len(scene.vfx) >= 4 for scene in scene_plans)
    has_character_performance = all(scene.character.get("gesture") and scene.character.get("expression") for scene in scene_plans)
    has_sound_design = all(scene.sfx for scene in scene_plans)
    has_pattern_interrupts = all(scene.retention_events for scene in scene_plans)
    has_worlds = all(scene.location and scene.foreground_elements and scene.background and scene.atmosphere for scene in scene_plans)
    has_skill_selection = all(3 <= len(scene.selected_skills) <= 5 for scene in scene_plans)
    has_skill_expansion = all(scene.skill_profile.get("prompt_fragments") and scene.skill_profile.get("vfx") for scene in scene_plans)
    has_shot_sequences = all(len(scene.shot_sequence) >= 2 for scene in scene_plans)
    has_broll = all(scene.broll_clips or scene.duration_seconds <= 4.0 for scene in scene_plans)
    has_depth_layers = all({"background", "foreground_ui", "particles"} <= {str(layer.get("type")) for layer in scene.layers} for scene in scene_plans)
    has_caption_plan = all(scene.caption_plan.get("headline") and len(scene.caption_plan.get("ui_labels", [])) <= 3 for scene in scene_plans)
    has_scene_quality = all(scene.scene_quality_score >= 80 for scene in scene_plans)

    checks = [
        ("has_establishing_shot", has_establishing, 10, "Add a wide establishing shot."),
        ("has_closeups", has_closeups, 10, "Add hero close-ups or UI macro shots."),
        ("has_camera_motion_every_scene", has_camera_motion_every_scene, 15, "Add camera motion to every scene."),
        ("has_visual_metaphors", has_visual_metaphors, 15, "Add metaphor objects such as vaults, keys, shields, and badges."),
        ("has_vfx_layers", has_vfx_layers, 10, "Add VFX layers to every scene."),
        ("has_character_performance", has_character_performance, 15, "Add character pose, gesture, and expression direction."),
        ("has_sound_design", has_sound_design, 15, "Add scene-level sound design."),
        ("has_pattern_interrupts", has_pattern_interrupts, 10, "Add pattern interrupts and cutaways."),
        ("has_cinematic_worlds", has_worlds, 10, "Add location, atmosphere, foreground, and background staging."),
        ("has_skill_selection", has_skill_selection, 10, "Select 3-5 compatible cinematic skills per scene."),
        ("has_skill_expansion", has_skill_expansion, 10, "Expand selected skills into renderer/prompt instructions."),
        ("has_shot_sequences", has_shot_sequences, 10, "Add shot-level sequencing to every scene."),
        ("has_broll_micro_scenes", has_broll, 10, "Insert B-roll or metaphor cutaways into longer scenes."),
        ("has_depth_layers", has_depth_layers, 10, "Add explicit background, foreground, particles, and light layers."),
        ("has_caption_plan", has_caption_plan, 10, "Add cleaned captions and readable label limits."),
        ("has_scene_quality_gate", has_scene_quality, 10, "Pass scene quality score >= 80 for every scene."),
    ]

    details: dict[str, bool] = {}
    for name, passed, points, message in checks:
        details[name] = passed
        if passed:
            score += points
        else:
            flags.append(message)

    # Preserve the user's 80+ render gate while allowing the expanded world check
    # to make excellent plans visibly score above the older 100-point checklist.
    normalized_score = min(100, score)
    return {
        "score": normalized_score,
        "raw_score": score,
        "passed": normalized_score >= 80,
        "flags": flags,
        "details": details,
    }
