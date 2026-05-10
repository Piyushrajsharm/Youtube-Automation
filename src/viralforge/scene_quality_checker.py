from __future__ import annotations

import re
from typing import Any

from .models import ScenePlan


def check_scene_quality(scene_plans: list[ScenePlan]) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    flags: list[str] = []
    previous: ScenePlan | None = None
    for scene in scene_plans:
        report = score_scene_quality(scene, previous)
        scene.scene_quality_score = float(report["score"])
        reports.append(report)
        if not report["passed"]:
            flags.append(f"{scene.scene_id}: " + "; ".join(str(item) for item in report["flags"]))
        previous = scene
    minimum = min((float(report["score"]) for report in reports), default=0.0)
    return {
        "passed": minimum >= 80 and not flags,
        "minimum_score": minimum,
        "flags": flags,
        "scene_reports": reports,
    }


def score_scene_quality(scene: ScenePlan, previous_scene: ScenePlan | None = None) -> dict[str, Any]:
    flags: list[str] = []
    layers = scene.layers or []
    layer_types = {str(layer.get("type")) for layer in layers}
    headline_words = _words(scene.headline_text)
    labels = scene.caption_plan.get("ui_labels", []) if scene.caption_plan else []
    similarity = _similarity(scene, previous_scene)
    checks = {
        "has_camera_motion": bool(scene.camera_motion or scene.camera_emotion),
        "has_visual_metaphor": bool(scene.visual_metaphor.get("objects")),
        "has_foreground_layer": "foreground_ui" in layer_types,
        "has_midground_layer": "midground" in layer_types or "character" in layer_types,
        "has_background_layer": "background" in layer_types,
        "has_sound_cue": bool(scene.sfx),
        "text_is_short": 3 <= len(headline_words) <= 7,
        "has_depth": len(layers) >= 5 and {"background", "foreground_ui", "particles"} <= layer_types,
        "not_repeating_previous": similarity < 0.75,
        "has_visual_change": _has_visual_change(scene),
        "presenter_integrated": _presenter_integrated(scene),
        "labels_readable": 1 <= len(labels) <= 3,
    }
    weights = {
        "has_camera_motion": 8,
        "has_visual_metaphor": 10,
        "has_foreground_layer": 8,
        "has_midground_layer": 8,
        "has_background_layer": 8,
        "has_sound_cue": 8,
        "text_is_short": 10,
        "has_depth": 12,
        "not_repeating_previous": 8,
        "has_visual_change": 10,
        "presenter_integrated": 6,
        "labels_readable": 4,
    }
    messages = {
        "has_camera_motion": "No camera emotion or motion.",
        "has_visual_metaphor": "No dedicated visual metaphor.",
        "has_foreground_layer": "No foreground UI depth layer.",
        "has_midground_layer": "No midground/character depth layer.",
        "has_background_layer": "No background depth layer.",
        "has_sound_cue": "No scene sound cue.",
        "text_is_short": "Headline is outside 3-7 word rule.",
        "has_depth": "Depth layer stack is incomplete.",
        "not_repeating_previous": "Scene is too visually similar to the previous scene.",
        "has_visual_change": "No B-roll, macro, angle, closeup, or metaphor change within 4 seconds.",
        "presenter_integrated": "Presenter lacks rim/shadow/depth integration.",
        "labels_readable": "UI labels are missing or cluttered.",
    }
    score = 0
    for key, passed in checks.items():
        if passed:
            score += weights[key]
        else:
            flags.append(messages[key])
    return {
        "scene_id": scene.scene_id,
        "score": min(100, score),
        "passed": score >= 80 and not flags,
        "flags": flags,
        "checks": checks,
        "similarity_to_previous": similarity,
        "shot_count": len(scene.shot_sequence),
        "broll_count": len(scene.broll_clips),
    }


def _has_visual_change(scene: ScenePlan) -> bool:
    if scene.duration_seconds <= 4.0:
        return len(scene.shot_sequence) >= 2
    changes = [
        float(shot.get("start", 0.0))
        for shot in scene.shot_sequence
        if shot.get("type") in {"new_angle", "broll", "macro_ui", "character_closeup", "visual_metaphor"}
    ]
    if not changes:
        return False
    points = [0.0, *changes, scene.duration_seconds]
    return all((points[idx + 1] - points[idx]) <= 4.05 for idx in range(len(points) - 1))


def _presenter_integrated(scene: ScenePlan) -> bool:
    if any(shot.get("type") == "broll" for shot in scene.shot_sequence) and not any(
        shot.get("type") in {"character_closeup", "new_angle", "presenter"} for shot in scene.shot_sequence
    ):
        return True
    integration = scene.character_integration or {}
    return bool(integration.get("contact_shadow") and integration.get("foreground_occlusion") and integration.get("rim_light"))


def _similarity(scene: ScenePlan, previous_scene: ScenePlan | None) -> float:
    if previous_scene is None:
        return 0.0
    score = 0.0
    if scene.location == previous_scene.location:
        score += 0.25
    if scene.visual_metaphor.get("theme") == previous_scene.visual_metaphor.get("theme"):
        score += 0.25
    current_shots = {str(shot.get("shot")) for shot in scene.shot_sequence[:3]}
    previous_shots = {str(shot.get("shot")) for shot in previous_scene.shot_sequence[:3]}
    if current_shots and previous_shots:
        score += 0.25 * (len(current_shots & previous_shots) / max(1, len(current_shots | previous_shots)))
    current_words = set(word.lower() for word in _words(scene.headline_text))
    previous_words = set(word.lower() for word in _words(previous_scene.headline_text))
    if current_words and previous_words:
        score += 0.25 * (len(current_words & previous_words) / max(1, len(current_words | previous_words)))
    return round(score, 3)


def _words(value: str) -> list[str]:
    return [word for word in re.findall(r"[A-Za-z0-9']+", value or "") if word]
