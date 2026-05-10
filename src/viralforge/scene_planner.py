from __future__ import annotations

import math
import re

from .broll_engine import broll_for_scene
from .caption_cleaner import caption_plan_for, clean_headline
from .depth_compositor import character_integration_for_scene, layers_for_scene
from .models import AnimationEvent, Scene, ScenePlan, VideoPlan
from .character_director import character_for
from .prompt_builder import build_cinematic_prompt
from .retention_editor import retention_events_for
from .scene_classifier import classify_scene
from .scene_quality_checker import check_scene_quality
from .shot_director import build_shot_sequence, camera_emotion_for
from .skill_expander import apply_skill_profile, expand_skills
from .skill_selector import select_skills
from .vfx_layer_engine import vfx_for
from .visual_metaphor_engine import cinematic_prompt_for, visual_metaphor_for, world_for


PURPOSES = ["hook", "problem", "reveal", "warning", "control", "payoff", "cta"]

CAMERA_BY_PURPOSE = {
    "hook": "dolly_push_in",
    "problem": "over_shoulder_pan",
    "reveal": "orbit_reveal",
    "warning": "impact_shake",
    "control": "rack_focus_pan",
    "payoff": "crane_pullback",
    "cta": "final_hero_lock",
}

VOICE_BY_PURPOSE = {
    "hook": "mysterious",
    "problem": "serious",
    "reveal": "confident",
    "warning": "warning",
    "control": "confident",
    "payoff": "direct",
    "cta": "direct",
}

SFX_BY_PURPOSE = {
    "hook": ["low_boom", "digital_click"],
    "problem": ["whoosh", "ui_tick"],
    "reveal": ["soft_boom", "glow_burst"],
    "warning": ["bass_hit", "glitch"],
    "control": ["click_pop", "tech_scan"],
    "payoff": ["rising_hit"],
    "cta": ["final_hit", "soft_boom"],
}

TRANSITION_BY_PURPOSE = {
    "hook": "flash_cut",
    "problem": "whoosh",
    "reveal": "zoom_cut",
    "warning": "glitch_cut",
    "control": "wipe",
    "payoff": "light_sweep",
    "cta": "hold_glow",
}


def create_scene_plan(plan: VideoPlan, target_duration: float) -> list[ScenePlan]:
    scenes = _ensure_story_arc(plan.scenes, target_duration)
    current_duration = sum(max(1.0, scene.duration_seconds) for scene in scenes)
    factor = target_duration / current_duration if current_duration else 1.0

    scene_plans: list[ScenePlan] = []
    selected_so_far: list[str] = []
    start = 0.0
    ellipsis_used = 0
    for index, scene in enumerate(scenes):
        duration = max(3.2, round(scene.duration_seconds * factor, 2))
        if index == len(scenes) - 1:
            purpose = "cta"
        else:
            purpose = PURPOSES[min(index, len(PURPOSES) - 2)]
        end = start + duration
        narration = _tighten_narration(scene.narration, purpose)
        raw_headline = _headline(scene, purpose)
        headline, used_ellipsis = clean_headline(
            raw_headline,
            narration,
            purpose,
            ellipsis_allowed=ellipsis_used < 2,
        )
        if used_ellipsis:
            ellipsis_used += 1
        text_context = f"{narration} {headline} {scene.visual_style}"
        shot_types = _shot_types(scene, duration, purpose, index)
        primary_shot = shot_types[0] if shot_types else "hero_closeup"
        metaphor = visual_metaphor_for(text_context, purpose, index)
        world = world_for(purpose, metaphor)
        character = character_for(purpose, primary_shot, index)
        vfx = vfx_for(purpose, str(metaphor.get("theme", "")), primary_shot)
        foreground = list(world.get("foreground", []))
        for item in metaphor.get("objects", []):
            if item not in foreground:
                foreground.append(item)
        scene_plan = ScenePlan(
            scene_id=f"scene_{index + 1:02d}",
            start_time=round(start, 2),
            end_time=round(end, 2),
            purpose=purpose,
            narration=narration,
            headline_text=headline,
            visual_description=_visual_description(scene.visual_style, world, metaphor, primary_shot),
            camera_motion=CAMERA_BY_PURPOSE[purpose],
            animation_events=_animation_events(scene, duration, purpose),
            caption_words=_caption_words(narration),
            voice_direction=VOICE_BY_PURPOSE[purpose],
            sfx=SFX_BY_PURPOSE[purpose],
            music_intensity=_music_intensity(purpose, index),
            transition=TRANSITION_BY_PURPOSE[purpose],
            shot_types=shot_types,
            emotion=_emotion_for(purpose, metaphor),
            location=str(world.get("location", "")),
            foreground_elements=foreground,
            midground=str(world.get("midground", "")),
            background=str(world.get("background", "")),
            atmosphere=str(world.get("atmosphere", "")),
            lighting=dict(world.get("lighting", {})),
            visual_metaphor=metaphor,
            character=character,
            vfx=vfx,
            retention_events=retention_events_for(index, purpose, duration, shot_types),
            cinematic_prompt=cinematic_prompt_for(
                topic=plan.topic,
                purpose=purpose,
                narration=narration,
                world=world,
                metaphor=metaphor,
                shot_type=primary_shot,
            ),
        )
        scene_plan.scene_type = classify_scene(scene_plan, text_context)
        selected_skills = select_skills(scene_plan, scene_plan.scene_type, index, selected_so_far)
        selected_so_far.extend(selected_skills)
        scene_plan = apply_skill_profile(scene_plan, selected_skills, expand_skills(selected_skills))
        scene_plan.camera_emotion = camera_emotion_for(
            scene_plan.purpose,
            scene_plan.emotion,
            str(scene_plan.visual_metaphor.get("theme", "")),
        )
        scene_plan.shot_sequence = build_shot_sequence(
            scene_id=scene_plan.scene_id,
            duration=scene_plan.duration_seconds,
            purpose=scene_plan.purpose,
            camera_emotion=scene_plan.camera_emotion,
            theme=str(scene_plan.visual_metaphor.get("theme", "")),
            base_shots=scene_plan.shot_types,
            scene_index=index,
        )
        sequenced_shots = [str(shot.get("shot")) for shot in scene_plan.shot_sequence if shot.get("shot")]
        if sequenced_shots:
            scene_plan.shot_types = sequenced_shots
            primary_shot = sequenced_shots[0]
        scene_plan.broll_clips = broll_for_scene(scene_plan, scene_plan.shot_sequence)
        scene_plan.layers = layers_for_scene(scene_plan)
        scene_plan.caption_plan = caption_plan_for(scene_plan)
        scene_plan.character_integration = character_integration_for_scene(scene_plan)
        scene_plan.cinematic_prompt = build_cinematic_prompt(scene_plan, plan.topic)
        scene_plans.append(scene_plan)
        start = end

    if scene_plans:
        scene_plans[-1].end_time = round(target_duration, 2)
        _refresh_scene_end(scene_plans[-1])
    check_scene_quality(scene_plans)
    return scene_plans


def _refresh_scene_end(scene: ScenePlan) -> None:
    if not scene.shot_sequence:
        return
    scene.shot_sequence[-1]["end"] = round(scene.duration_seconds, 2)
    scene.broll_clips = broll_for_scene(scene, scene.shot_sequence)


def _ensure_story_arc(scenes: list[Scene], target_duration: float) -> list[Scene]:
    if not scenes:
        return []
    result = list(scenes)
    last_text = f"{result[-1].narration} {result[-1].onscreen_text}".lower()
    if "?" not in result[-1].onscreen_text and "hire" not in last_text and "would you" not in last_text:
        result.append(
            Scene(
                narration="So here is the real question. Would you hire an AI worker if you controlled exactly what it could touch?",
                onscreen_text="Would you hire one?",
                visual_style="centered CTA, glowing yes/no decision buttons, final cinematic hold",
                duration_seconds=max(4.0, min(7.0, target_duration * 0.1)),
            )
        )
    return result


def _tighten_narration(text: str, purpose: str = "") -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("That is", "That's").replace("It is", "It's").replace("do not", "don't")
    text = re.sub(r"^\s*(picture this|imagine this|here's the thing|look)\s*:\s*", "", text, flags=re.IGNORECASE)
    budget = {
        "hook": 20,
        "problem": 22,
        "reveal": 20,
        "warning": 22,
        "control": 22,
        "payoff": 20,
        "cta": 18,
    }.get(purpose, 20)

    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    candidate = sentences[0] if sentences else text
    if len(sentences) > 1:
        for extra in sentences[1:]:
            combined = f"{candidate} {extra}".strip()
            if len(combined.split()) <= budget:
                candidate = combined
            else:
                break
    if len(candidate.split()) > budget:
        fragments = [
            part.strip(" ,;:.")
            for part in re.split(r"\s*[-–—]\s*|:\s+|…|\.{3}|,\s+and\s+|\s+and\s+|,\s+but\s+|\s+but\s+", candidate)
            if part.strip(" ,;:.")
        ]
        strong = [fragment for fragment in fragments if 5 <= len(fragment.split()) <= budget]
        if strong:
            candidate = strong[0]
    words = candidate.split()
    if len(words) > budget:
        candidate = " ".join(words[:budget]).rstrip(",;:")
    dangling = {
        "a",
        "an",
        "and",
        "at",
        "before",
        "but",
        "for",
        "from",
        "in",
        "into",
        "its",
        "of",
        "on",
        "or",
        "the",
        "their",
        "to",
        "with",
        "your",
    }
    parts = candidate.split()
    while parts and (parts[-1].lower().strip(".,:;!?*'\"") in dangling or parts[-1].lower().endswith(("'s", "’s"))):
        parts.pop()
    candidate = " ".join(parts)
    candidate = candidate.strip()
    if candidate:
        candidate = candidate[0].upper() + candidate[1:]
    if candidate and candidate[-1] not in ".!?":
        candidate += "."
    return candidate


def _headline(scene: Scene, purpose: str) -> str:
    text = scene.onscreen_text.strip()
    if purpose == "cta" and "?" not in text:
        return "Would you hire one?"
    return text


def _animation_events(scene: Scene, duration: float, purpose: str) -> list[AnimationEvent]:
    base = [
        AnimationEvent(0.15, "text_punch_zoom", "headline"),
        AnimationEvent(min(duration * 0.26, duration - 0.2), "camera_angle_change", "camera"),
        AnimationEvent(min(duration * 0.38, duration - 0.2), "cursor_click", "ui"),
        AnimationEvent(min(duration * 0.56, duration - 0.2), "visual_metaphor_cutaway", "visual"),
        AnimationEvent(min(duration * 0.74, duration - 0.2), "glow_burst", "keyword"),
    ]
    if purpose == "warning":
        base.insert(1, AnimationEvent(min(0.8, duration * 0.2), "risk_warning_red_flash", "scene"))
        base.append(AnimationEvent(min(duration * 0.68, duration - 0.2), "screen_glitch", "scene"))
        base.append(AnimationEvent(min(duration * 0.45, duration - 0.2), "electric_arc", "vault"))
    if purpose == "reveal":
        base.append(AnimationEvent(min(duration * 0.48, duration - 0.2), "energy_pulse", "hologram"))
    if purpose == "cta":
        base.append(AnimationEvent(min(duration * 0.55, duration - 0.2), "checkmark_pop", "cta"))
    return base


def _caption_words(narration: str) -> list[str]:
    narration = narration.replace("’", "'").replace("‘", "'")
    return [word.strip(".,:;!?") for word in narration.split() if word.strip(".,:;!?")]


def _music_intensity(purpose: str, index: int) -> float:
    if purpose in {"hook", "warning", "cta"}:
        return 0.86
    if purpose == "reveal":
        return 0.74
    return 0.52 + (index % 2) * 0.1


def _shot_types(scene: Scene, duration: float, purpose: str, scene_index: int) -> list[str]:
    count = max(1, math.ceil(duration / 2.45))
    text = f"{scene.narration} {scene.onscreen_text} {scene.visual_style}".lower()
    if purpose == "hook":
        cycle = ["establishing", "hero_closeup", "ui_macro", "impact_reveal"]
    elif purpose == "warning" or any(word in text for word in ("risk", "access", "permission", "keys")):
        cycle = ["impact_reveal", "ui_macro", "over_shoulder", "text_impact", "vault_cutaway"]
    elif purpose == "cta":
        cycle = ["final_hero", "hero_closeup", "key_cutaway", "final_hero"]
    elif purpose == "control" or any(word in text for word in ("review", "approve", "control", "manager")):
        cycle = ["over_shoulder", "ui_macro", "hero_closeup", "shield_cutaway"]
    elif any(word in text for word in ("task", "boring", "admin", "research", "finished")):
        cycle = ["fast_montage", "ui_macro", "over_shoulder", "task_cutaway"]
    else:
        cycle = ["over_shoulder", "hero_closeup", "ui_macro", "text_impact"]
    if scene_index > 0 and cycle[0] == "establishing":
        cycle = ["over_shoulder", *cycle[1:]]
    return [cycle[index % len(cycle)] for index in range(count)]


def _visual_description(style: str, world: dict[str, object], metaphor: dict[str, object], shot_type: str) -> str:
    objects = ", ".join(str(item) for item in metaphor.get("objects", []))
    return (
        f"{shot_type} inside {world.get('location')}; {world.get('midground')}; "
        f"foreground metaphor: {objects}; original style note: {style}"
    )


def _emotion_for(purpose: str, metaphor: dict[str, object]) -> str:
    if metaphor.get("theme") == "risk":
        return "mysterious threat"
    if metaphor.get("theme") == "access":
        return "dangerous permission tension"
    if purpose == "cta":
        return "direct challenge"
    if purpose == "payoff":
        return "earned momentum"
    return {
        "hook": "mysterious confidence",
        "problem": "urgent pressure",
        "reveal": "trailer-style reveal",
        "control": "calm authority",
    }.get(purpose, "confident tension")
