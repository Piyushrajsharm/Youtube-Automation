from __future__ import annotations

from typing import Any


CAMERA_EMOTION_MAP: dict[str, list[str]] = {
    "mystery": ["slow_push_in", "subtle_parallax"],
    "danger": ["micro_shake", "crash_zoom", "red_flash"],
    "reveal": ["dolly_push", "light_sweep"],
    "chaos": ["fast_pan", "glitch_cut", "motion_blur"],
    "authority": ["low_angle_push", "center_lock"],
    "trust": ["stable_frame", "soft_push"],
}

SHOT_LIBRARY: dict[str, list[str]] = {
    "hook": ["hero_closeup", "new_angle", "ai_office", "macro_ui"],
    "problem": ["task_montage", "new_angle", "macro_ui", "ai_office"],
    "reveal": ["over_shoulder", "task_montage", "visual_metaphor", "hero_closeup"],
    "warning": ["vault_access", "character_closeup", "macro_ui", "chaos_dashboard"],
    "control": ["human_review", "over_shoulder", "macro_ui", "visual_metaphor"],
    "payoff": ["server_room", "task_montage", "new_angle", "human_review"],
    "cta": ["final_hero_system", "character_closeup", "visual_metaphor", "final_hero"],
}

BROLL_SHOTS = {
    "ai_office",
    "task_montage",
    "vault_access",
    "human_review",
    "chaos_dashboard",
    "server_room",
    "final_hero_system",
}

VISUAL_CHANGE_TYPES = {"new_angle", "broll", "macro_ui", "character_closeup", "visual_metaphor"}


def camera_emotion_for(purpose: str, emotion: str, theme: str) -> str:
    text = f"{purpose} {emotion} {theme}".lower()
    if any(word in text for word in ("warning", "danger", "risk", "access", "alarm")):
        return "danger"
    if any(word in text for word in ("reveal", "payoff", "hero")):
        return "reveal"
    if any(word in text for word in ("chaos", "speed", "task", "problem")):
        return "chaos"
    if any(word in text for word in ("control", "manager", "review", "authority")):
        return "authority"
    if any(word in text for word in ("trust", "safe", "cta")):
        return "trust"
    return "mystery"


def build_shot_sequence(
    *,
    scene_id: str,
    duration: float,
    purpose: str,
    camera_emotion: str,
    theme: str,
    base_shots: list[str],
    scene_index: int,
) -> list[dict[str, Any]]:
    duration = max(0.4, float(duration))
    desired_count = max(2, int(duration / 1.85 + 0.999))
    cycle = list(SHOT_LIBRARY.get(purpose, [])) or list(base_shots) or ["hero_closeup", "macro_ui"]
    if purpose == "hook":
        cycle = ["establishing", "hero_closeup", "ai_office", "macro_ui"]
    elif theme == "access":
        cycle = ["vault_access", "macro_ui", "character_closeup", "human_review"]
    elif theme == "risk":
        cycle = ["chaos_dashboard", "vault_access", "macro_ui", "character_closeup"]
    elif theme == "speed":
        cycle = ["task_montage", "ai_office", "macro_ui", "new_angle"]
    elif theme == "control":
        cycle = ["human_review", "over_shoulder", "macro_ui", "visual_metaphor"]
    elif theme == "question":
        cycle = ["final_hero_system", "character_closeup", "visual_metaphor", "final_hero"]

    sequence: list[dict[str, Any]] = []
    cursor = 0.0
    for idx in range(desired_count):
        remaining = duration - cursor
        remaining_slots = desired_count - idx
        length = min(2.35, max(1.15, remaining / remaining_slots))
        if remaining <= 0.45:
            break
        shot_name = cycle[(idx + scene_index) % len(cycle)]
        change_type = _change_type_for_shot(shot_name, idx)
        camera = _camera_for(camera_emotion, idx, shot_name)
        entry = {
            "shot_id": f"{scene_id}_shot_{idx + 1:02d}",
            "start": round(cursor, 2),
            "end": round(min(duration, cursor + length), 2),
            "type": change_type,
            "shot": shot_name,
            "focus": _focus_for(shot_name, purpose, theme),
            "camera": camera,
            "camera_emotion": camera_emotion,
            "transition": _transition_for(change_type, idx),
        }
        if shot_name in BROLL_SHOTS:
            entry["type"] = "broll"
            entry["broll_type"] = shot_name
        sequence.append(entry)
        cursor += length

    if sequence:
        sequence[-1]["end"] = round(duration, 2)
    _enforce_visual_change_rule(sequence, duration, purpose, theme)
    return sequence


def _change_type_for_shot(shot: str, index: int) -> str:
    if shot in BROLL_SHOTS:
        return "broll"
    if shot in {"ui_macro", "macro_ui"}:
        return "macro_ui"
    if shot in {"hero_closeup", "character_closeup", "impact_reveal"}:
        return "character_closeup"
    if shot in {"vault_cutaway", "key_cutaway", "shield_cutaway", "visual_metaphor"}:
        return "visual_metaphor"
    return "new_angle" if index else "presenter"


def _camera_for(camera_emotion: str, index: int, shot: str) -> str:
    options = CAMERA_EMOTION_MAP.get(camera_emotion, CAMERA_EMOTION_MAP["mystery"])
    if shot in BROLL_SHOTS:
        return {
            "vault_access": "crash_zoom",
            "chaos_dashboard": "fast_pan",
            "task_montage": "fast_pan",
            "human_review": "soft_push",
            "server_room": "dolly_push",
            "final_hero_system": "low_angle_push",
            "ai_office": "subtle_parallax",
        }.get(shot, options[index % len(options)])
    return options[index % len(options)]


def _focus_for(shot: str, purpose: str, theme: str) -> str:
    if shot == "ai_office":
        return "AI intern inside a futuristic office workflow"
    if shot == "task_montage":
        return "task queue cards flying through the room"
    if shot == "vault_access":
        return "glowing key and locked permission vault"
    if shot == "human_review":
        return "manager approval console and audit trail"
    if shot == "chaos_dashboard":
        return "broken dashboard with red alerts and guardrails missing"
    if shot == "server_room":
        return "deep server vault resolving into safe signals"
    if shot == "final_hero_system":
        return "human manager facing the viewer with AI system behind"
    if shot == "macro_ui":
        return "large readable interface action"
    if shot == "character_closeup":
        return "presenter expression and gesture synced to narration"
    return f"{purpose} beat with {theme} metaphor"


def _transition_for(change_type: str, index: int) -> str:
    if index == 0:
        return "cold_open"
    return {
        "broll": "whip_cut",
        "macro_ui": "scan_cut",
        "character_closeup": "punch_in",
        "visual_metaphor": "glitch_reveal",
        "new_angle": "match_cut",
    }.get(change_type, "whoosh")


def _enforce_visual_change_rule(sequence: list[dict[str, Any]], duration: float, purpose: str, theme: str) -> None:
    if not sequence:
        return
    last_change = 0.0
    for idx, shot in enumerate(sequence):
        if shot.get("type") in VISUAL_CHANGE_TYPES:
            last_change = float(shot.get("start", last_change))
        if float(shot.get("end", 0.0)) - last_change > 4.0:
            shot["type"] = "broll"
            shot["shot"] = _fallback_broll(purpose, theme, idx)
            shot["broll_type"] = shot["shot"]
            shot["camera"] = _camera_for(str(shot.get("camera_emotion", "mystery")), idx, shot["shot"])
            shot["focus"] = _focus_for(shot["shot"], purpose, theme)
            last_change = float(shot.get("start", 0.0))
    if duration > 4.0 and not any(shot.get("type") in {"broll", "visual_metaphor", "macro_ui"} for shot in sequence):
        target = sequence[min(1, len(sequence) - 1)]
        target["type"] = "broll"
        target["shot"] = _fallback_broll(purpose, theme, 0)
        target["broll_type"] = target["shot"]
        target["focus"] = _focus_for(target["shot"], purpose, theme)


def _fallback_broll(purpose: str, theme: str, index: int) -> str:
    by_theme = {
        "access": "vault_access",
        "risk": "chaos_dashboard",
        "speed": "task_montage",
        "control": "human_review",
        "question": "final_hero_system",
        "ai_worker": "ai_office",
    }
    if theme in by_theme:
        return by_theme[theme]
    return ["ai_office", "task_montage", "server_room", "human_review"][index % 4]
