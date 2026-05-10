from __future__ import annotations

import math

from .models import ScenePlan


CAMERA_PRESETS = {
    "slow_push_in": {"scale_start": 1.0, "scale_end": 1.08, "x_shift": 0, "y_shift": -26},
    "dramatic_zoom": {"scale_start": 1.0, "scale_end": 1.18, "x_shift": 0, "y_shift": -18},
    "parallax_left": {"scale_start": 1.04, "scale_end": 1.08, "x_shift": -46, "y_shift": 0},
    "impact_shake": {"scale_start": 1.05, "scale_end": 1.08, "x_shift": 0, "y_shift": 0, "strength": 10},
    "smooth_pan": {"scale_start": 1.04, "scale_end": 1.08, "x_shift": 34, "y_shift": -10},
    "center_lock_glow": {"scale_start": 1.03, "scale_end": 1.03, "x_shift": 0, "y_shift": 0},
    "dolly_push_in": {"scale_start": 1.0, "scale_end": 1.11, "x_shift": 0, "y_shift": -34},
    "over_shoulder_pan": {"scale_start": 1.05, "scale_end": 1.1, "x_shift": -54, "y_shift": -8},
    "orbit_reveal": {"scale_start": 1.03, "scale_end": 1.15, "x_shift": 42, "y_shift": -26},
    "rack_focus_pan": {"scale_start": 1.06, "scale_end": 1.1, "x_shift": 30, "y_shift": -14},
    "crane_pullback": {"scale_start": 1.13, "scale_end": 1.02, "x_shift": 0, "y_shift": 36},
    "final_hero_lock": {"scale_start": 1.05, "scale_end": 1.09, "x_shift": 0, "y_shift": -22},
    "subtle_parallax": {"scale_start": 1.03, "scale_end": 1.06, "x_shift": -28, "y_shift": -8},
    "crash_zoom": {"scale_start": 1.02, "scale_end": 1.2, "x_shift": 0, "y_shift": -24, "strength": 9},
    "micro_shake": {"scale_start": 1.04, "scale_end": 1.08, "x_shift": 0, "y_shift": 0, "strength": 5},
    "red_flash": {"scale_start": 1.05, "scale_end": 1.09, "x_shift": 0, "y_shift": -8},
    "dolly_push": {"scale_start": 1.0, "scale_end": 1.12, "x_shift": 0, "y_shift": -32},
    "light_sweep": {"scale_start": 1.02, "scale_end": 1.08, "x_shift": 18, "y_shift": -18},
    "fast_pan": {"scale_start": 1.08, "scale_end": 1.12, "x_shift": 74, "y_shift": -8},
    "glitch_cut": {"scale_start": 1.05, "scale_end": 1.11, "x_shift": 16, "y_shift": 0, "strength": 7},
    "motion_blur": {"scale_start": 1.04, "scale_end": 1.1, "x_shift": -62, "y_shift": 6},
    "low_angle_push": {"scale_start": 1.04, "scale_end": 1.12, "x_shift": 0, "y_shift": -46},
    "center_lock": {"scale_start": 1.03, "scale_end": 1.04, "x_shift": 0, "y_shift": -8},
    "stable_frame": {"scale_start": 1.0, "scale_end": 1.025, "x_shift": 0, "y_shift": 0},
    "soft_push": {"scale_start": 1.0, "scale_end": 1.055, "x_shift": 0, "y_shift": -12},
}


def camera_state(scene: ScenePlan, progress: float, local_time: float, scene_index: int) -> tuple[float, float, float]:
    shot_entry = current_shot_entry(scene, local_time)
    camera_name = str(shot_entry.get("camera") or scene.camera_motion)
    preset = CAMERA_PRESETS.get(camera_name, CAMERA_PRESETS.get(scene.camera_motion, CAMERA_PRESETS["slow_push_in"]))
    eased = _ease_in_out(progress)
    scale = preset["scale_start"] + (preset["scale_end"] - preset["scale_start"]) * eased
    dx = preset.get("x_shift", 0) * eased
    dy = preset.get("y_shift", 0) * eased
    if camera_name == "orbit_reveal":
        dx += math.sin(progress * math.tau * 0.7 + scene_index) * 24
        dy += math.cos(progress * math.tau * 0.55 + scene_index) * 10
    if camera_name == "final_hero_lock":
        dx += math.sin(local_time * 2.0) * 4
    if camera_name in {"impact_shake", "micro_shake", "crash_zoom", "glitch_cut"} and local_time < 0.55:
        strength = preset.get("strength", 8) * max(0.0, 1 - local_time / 0.45)
        dx += math.sin(local_time * 90 + scene_index) * strength
        dy += math.cos(local_time * 84 + scene_index) * strength
    return scale, dx, dy


def current_shot_entry(scene: ScenePlan, local_time: float) -> dict[str, object]:
    if scene.shot_sequence:
        fallback = scene.shot_sequence[-1]
        for shot in scene.shot_sequence:
            start = float(shot.get("start", 0.0))
            end = float(shot.get("end", scene.duration_seconds))
            if start <= local_time < end:
                return shot
        return fallback
    return {}


def current_shot(scene: ScenePlan, local_time: float) -> str:
    entry = current_shot_entry(scene, local_time)
    if entry.get("shot"):
        return str(entry["shot"])
    if not scene.shot_types:
        return "hero_closeup"
    index = min(len(scene.shot_types) - 1, int(local_time / 2.45))
    return scene.shot_types[index]


def should_flash(scene: ScenePlan, local_time: float) -> bool:
    flash_events = {"risk_warning_red_flash", "screen_glitch", "energy_pulse", "electric_arc"}
    return any(event.effect in flash_events and abs(local_time - event.time) < 0.12 for event in scene.animation_events)


def event_intensity(scene: ScenePlan, local_time: float, effect: str, window: float = 0.3) -> float:
    value = 0.0
    for event in scene.animation_events:
        if event.effect != effect:
            continue
        distance = abs(local_time - event.time)
        if distance < window:
            value = max(value, 1 - distance / window)
    return value


def _ease_in_out(x: float) -> float:
    return x * x * (3 - 2 * x)
