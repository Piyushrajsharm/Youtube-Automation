from __future__ import annotations


RETENTION_EVENT_SEQUENCE = [
    "cold_open_impact",
    "camera_angle_change",
    "vfx_reveal",
    "pattern_interrupt",
    "sound_drop",
    "visual_metaphor_cutaway",
    "fast_montage",
    "hero_cta",
]


def retention_events_for(scene_index: int, purpose: str, duration: float, shot_types: list[str]) -> list[dict[str, float | str]]:
    events: list[dict[str, float | str]] = []
    if scene_index == 0:
        events.append({"time": 0.0, "event": "cold_open_impact"})

    if duration >= 2.4:
        events.append({"time": round(min(0.8, duration * 0.26), 2), "event": "camera_angle_change"})
    if duration >= 3.4:
        events.append({"time": round(duration * 0.52, 2), "event": _middle_event(purpose, scene_index)})
    if duration >= 4.6:
        events.append({"time": round(duration * 0.76, 2), "event": "visual_metaphor_cutaway"})

    if len(shot_types) >= 3:
        events.append({"time": round(min(duration - 0.35, 2.5), 2), "event": "pattern_interrupt"})
    if purpose == "cta":
        events.append({"time": round(max(0.0, duration - 1.1), 2), "event": "hero_cta"})
    return events


def _middle_event(purpose: str, scene_index: int) -> str:
    if purpose == "warning":
        return "sound_drop"
    if purpose == "reveal":
        return "vfx_reveal"
    if purpose == "payoff":
        return "fast_montage"
    return RETENTION_EVENT_SEQUENCE[(scene_index + 1) % len(RETENTION_EVENT_SEQUENCE)]
