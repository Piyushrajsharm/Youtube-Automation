from __future__ import annotations

from typing import Any

from .models import AnimationEvent, ScenePlan
from .skill_registry import SKILL_REGISTRY


def expand_skills(skill_ids: list[str]) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "camera": None,
        "lighting": {},
        "vfx": [],
        "edit": [],
        "music": [],
        "voice": None,
        "sfx": [],
        "shot_types": [],
        "events": [],
        "story": [],
        "prompt_fragments": [],
        "external_video": [],
        "score_tags": {},
    }
    for skill_id in skill_ids:
        skill = SKILL_REGISTRY.get(skill_id)
        if not skill:
            continue
        if skill.get("camera") and profile["camera"] is None:
            profile["camera"] = skill["camera"]
        if skill.get("lighting"):
            profile["lighting"].update(skill["lighting"])
        for key in ("vfx", "sfx", "shot_types", "events", "music"):
            _extend_unique(profile[key], skill.get(key, []))
        if skill.get("edit"):
            _extend_unique(profile["edit"], [skill["edit"]])
        if skill.get("voice") and profile["voice"] is None:
            profile["voice"] = skill["voice"]
        if skill.get("story"):
            _extend_unique(profile["story"], [skill["story"]])
        if skill.get("prompt"):
            profile["prompt_fragments"].append(skill["prompt"])
        if skill.get("external_provider"):
            profile["external_video"].append({"provider": skill["external_provider"], "skill": skill_id})
        for score_key, value in skill.get("scores", {}).items():
            profile["score_tags"][score_key] = profile["score_tags"].get(score_key, 0) + value
    return profile


def apply_skill_profile(scene: ScenePlan, skill_ids: list[str], profile: dict[str, Any]) -> ScenePlan:
    scene.selected_skills = skill_ids
    scene.skill_profile = profile
    if profile.get("camera"):
        scene.camera_motion = str(profile["camera"])
    if profile.get("voice"):
        scene.voice_direction = str(profile["voice"])
    if profile.get("lighting"):
        scene.lighting.update(profile["lighting"])
    _merge_unique(scene.vfx, profile.get("vfx", []))
    _merge_unique(scene.sfx, profile.get("sfx", []))
    _prepend_unique(scene.shot_types, profile.get("shot_types", []))
    if profile.get("edit"):
        scene.transition = _transition_for_edit(profile["edit"][-1], scene.transition)
    _add_skill_events(scene, profile.get("events", []))
    return scene


def _add_skill_events(scene: ScenePlan, events: list[str]) -> None:
    existing = {event.effect for event in scene.animation_events}
    for index, event_name in enumerate(events):
        if event_name in existing:
            continue
        time = min(scene.duration_seconds - 0.2, max(0.1, scene.duration_seconds * (0.22 + index * 0.14)))
        scene.animation_events.append(AnimationEvent(round(time, 2), event_name, "skill"))


def _transition_for_edit(edit: str, fallback: str) -> str:
    return {
        "impact_cut": "flash_cut",
        "glitch_transition": "glitch_cut",
        "montage_burst": "whip_cut",
        "contrast_cut": "split_wipe",
        "beat_synced_text_reveal": fallback,
    }.get(edit, fallback)


def _extend_unique(target: list[Any], values: list[Any]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _merge_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def _prepend_unique(target: list[str], values: list[str]) -> None:
    for value in reversed(values):
        if value in target:
            target.remove(value)
        target.insert(0, value)
