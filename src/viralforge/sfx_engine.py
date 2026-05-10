from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np

from .models import ScenePlan


def synthesize_sfx(scene_plans: list[ScenePlan], output_dir: Path, duration: float, sample_rate: int = 48000) -> Path | None:
    if not scene_plans:
        return None
    path = output_dir / "sound_design.wav"
    total = int(max(1.0, duration) * sample_rate)
    audio = np.zeros(total, dtype=np.float32)
    for scene in scene_plans:
        for sfx_name in scene.sfx:
            moment = scene.start_time + _sfx_offset(sfx_name, scene.duration_seconds)
            _add_sfx(audio, moment, sample_rate, sfx_name, scene.music_intensity)
        for event in scene.animation_events:
            if event.effect in {
                "text_punch_zoom",
                "glow_burst",
                "checkmark_pop",
                "cursor_click",
                "screen_glitch",
                "energy_pulse",
                "electric_arc",
                "visual_metaphor_cutaway",
                "camera_angle_change",
            }:
                _add_sfx(audio, scene.start_time + event.time, sample_rate, _event_to_sfx(event.effect), scene.music_intensity)
        for edit_event in scene.retention_events:
            name = str(edit_event.get("event", ""))
            moment = scene.start_time + float(edit_event.get("time", 0.0))
            if name:
                _add_sfx(audio, moment, sample_rate, _retention_to_sfx(name), scene.music_intensity)
    audio = np.tanh(audio * 1.2)
    stereo = np.stack([audio * 0.95, audio], axis=1)
    pcm = np.int16(np.clip(stereo, -1, 1) * 32767)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return path


def _sfx_offset(name: str, duration: float) -> float:
    if name in {"low_boom", "soft_boom", "bass_hit"}:
        return 0.12
    if name in {"whoosh", "glitch"}:
        return min(duration * 0.82, duration - 0.2)
    if name in {"final_hit", "rising_hit"}:
        return min(duration * 0.68, duration - 0.2)
    return min(duration * 0.38, duration - 0.2)


def _event_to_sfx(effect: str) -> str:
    return {
        "text_punch_zoom": "soft_boom",
        "glow_burst": "rising_hit",
        "checkmark_pop": "click_pop",
        "cursor_click": "digital_click",
        "screen_glitch": "glitch",
        "energy_pulse": "rising_hit",
        "electric_arc": "glitch",
        "visual_metaphor_cutaway": "whoosh",
        "camera_angle_change": "whoosh",
    }.get(effect, "ui_tick")


def _retention_to_sfx(event: str) -> str:
    return {
        "cold_open_impact": "bass_hit",
        "camera_angle_change": "whoosh",
        "vfx_reveal": "rising_hit",
        "pattern_interrupt": "glitch",
        "sound_drop": "bass_hit",
        "visual_metaphor_cutaway": "whoosh",
        "fast_montage": "tech_scan",
        "hero_cta": "final_hit",
    }.get(event, "ui_tick")


def _add_sfx(audio: np.ndarray, time_seconds: float, sample_rate: int, name: str, intensity: float) -> None:
    start = int(max(0, time_seconds) * sample_rate)
    if start >= len(audio):
        return
    if name in {"low_boom", "soft_boom", "bass_hit", "final_hit"}:
        _boom(audio, start, sample_rate, 0.24 + intensity * 0.22, 42 if name == "bass_hit" else 58)
    elif name in {"whoosh", "rising_hit", "tech_scan"}:
        _whoosh(audio, start, sample_rate, 0.35, intensity)
    elif name in {"digital_click", "ui_tick", "click_pop"}:
        _click(audio, start, sample_rate, intensity)
    elif name == "glitch":
        _glitch(audio, start, sample_rate, intensity)


def _boom(audio: np.ndarray, start: int, sample_rate: int, volume: float, base_freq: float) -> None:
    length = min(len(audio) - start, int(0.42 * sample_rate))
    if length <= 0:
        return
    x = np.arange(length, dtype=np.float32) / sample_rate
    signal = np.sin(2 * math.pi * base_freq * x) * np.exp(-x * 8)
    audio[start : start + length] += volume * signal


def _whoosh(audio: np.ndarray, start: int, sample_rate: int, seconds: float, intensity: float) -> None:
    length = min(len(audio) - start, int(seconds * sample_rate))
    if length <= 0:
        return
    rng = np.random.default_rng(start)
    x = np.linspace(0, 1, length, dtype=np.float32)
    noise = rng.uniform(-1, 1, length).astype(np.float32)
    sweep = np.sin(2 * math.pi * (220 + 920 * x) * x * seconds)
    audio[start : start + length] += (0.045 + intensity * 0.035) * (noise * 0.35 + sweep * 0.65) * np.sin(math.pi * x)


def _click(audio: np.ndarray, start: int, sample_rate: int, intensity: float) -> None:
    length = min(len(audio) - start, int(0.07 * sample_rate))
    if length <= 0:
        return
    x = np.arange(length, dtype=np.float32) / sample_rate
    signal = np.sin(2 * math.pi * 1300 * x) * np.exp(-x * 60)
    audio[start : start + length] += (0.08 + intensity * 0.04) * signal


def _glitch(audio: np.ndarray, start: int, sample_rate: int, intensity: float) -> None:
    length = min(len(audio) - start, int(0.16 * sample_rate))
    if length <= 0:
        return
    rng = np.random.default_rng(start + 44)
    signal = rng.uniform(-1, 1, length).astype(np.float32)
    gate = (np.arange(length) // max(1, int(sample_rate * 0.012))) % 2
    audio[start : start + length] += (0.05 + intensity * 0.05) * signal * gate
