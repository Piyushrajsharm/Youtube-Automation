from __future__ import annotations

from collections import Counter

from .models import ScenePlan
from .skill_registry import PURPOSE_SKILL_RULES, SKILL_REGISTRY


MAX_SKILLS_PER_SCENE = 5
MAX_EXTERNAL_VIDEO_SKILLS_PER_VIDEO = 3


def select_skills(
    scene: ScenePlan,
    scene_type: str,
    scene_index: int,
    selected_so_far: list[str] | None = None,
) -> list[str]:
    selected_so_far = selected_so_far or []
    candidates: list[str] = []
    candidates.extend(_scene_type_skills(scene_type))
    candidates.extend(PURPOSE_SKILL_RULES.get(scene.purpose, []))
    candidates.extend(_emotion_skills(scene.emotion))

    # Keep variety without losing consistency.
    if scene_index % 2 == 0 and scene.purpose not in {"warning", "cta"}:
        candidates.append("contrast_cut")
    if "seedance2_prompt_package" in candidates and selected_so_far.count("seedance2_prompt_package") >= MAX_EXTERNAL_VIDEO_SKILLS_PER_VIDEO:
        candidates = [skill for skill in candidates if skill != "seedance2_prompt_package"]

    return _compatible_first(candidates, selected_so_far)


def _scene_type_skills(scene_type: str) -> list[str]:
    return {
        "cold_open": ["cold_open", "hero_reveal"],
        "danger_reveal": ["danger_alert", "glitch_transition"],
        "safe_control": ["safe_control", "contrast_cut"],
        "hero_reveal": ["hero_reveal", "caption_punch"],
        "montage": ["montage_burst", "caption_punch"],
        "decision_cta": ["epic_cta", "caption_punch"],
    }.get(scene_type, ["cinematic_world_depth", "caption_punch"])


def _emotion_skills(emotion: str) -> list[str]:
    emotion = emotion.lower()
    if any(word in emotion for word in ("threat", "danger", "tension")):
        return ["danger_alert"]
    if any(word in emotion for word in ("hero", "reveal", "awe")):
        return ["hero_reveal"]
    if "authority" in emotion:
        return ["safe_control"]
    return []


def _compatible_first(candidates: list[str], selected_so_far: list[str]) -> list[str]:
    result: list[str] = []
    external_counts = Counter(skill for skill in selected_so_far if SKILL_REGISTRY.get(skill, {}).get("category") == "external_video")
    for skill_id in candidates:
        if skill_id not in SKILL_REGISTRY or skill_id in result:
            continue
        skill = SKILL_REGISTRY[skill_id]
        if any(blocked in result for blocked in skill.get("incompatible", [])):
            continue
        if skill.get("category") == "external_video" and external_counts[skill_id] >= int(skill.get("max_per_video", 99)):
            continue
        result.append(skill_id)
        if len(result) >= MAX_SKILLS_PER_SCENE:
            break
    if "caption_punch" not in result and len(result) < MAX_SKILLS_PER_SCENE:
        result.append("caption_punch")
    if "cinematic_world_depth" not in result and len(result) < MAX_SKILLS_PER_SCENE:
        result.append("cinematic_world_depth")
    return result[:MAX_SKILLS_PER_SCENE]
