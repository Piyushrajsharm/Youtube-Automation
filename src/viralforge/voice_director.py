from __future__ import annotations

from .models import ScenePlan


VOICE_MODES = {
    "mysterious": {"rate": "+0%", "pitch": "-3Hz"},
    "serious": {"rate": "+1%", "pitch": "-4Hz"},
    "confident": {"rate": "+6%", "pitch": "+0Hz"},
    "warning": {"rate": "-1%", "pitch": "-5Hz"},
    "direct": {"rate": "+5%", "pitch": "-1Hz"},
}

PAUSE_AFTER = {
    "hook": " ",
    "warning": " ",
    "cta": " ",
}


def directed_script(scenes: list[ScenePlan]) -> str:
    parts: list[str] = []
    for scene in scenes:
        text = scene.narration.strip()
        text = _emphasize_power_phrases(text)
        parts.append(text)
        parts.append(PAUSE_AFTER.get(scene.purpose, " "))
    return " ".join(parts).strip()


def voice_params(scene: ScenePlan) -> dict[str, str]:
    return VOICE_MODES.get(scene.voice_direction, VOICE_MODES["confident"])


def _emphasize_power_phrases(text: str) -> str:
    replacements = {
        "not human": "not human.",
        "A worker": "A worker.",
        "The risk is access": "The risk is access.",
        "the keys": "the keys.",
    }
    for phrase, replacement in replacements.items():
        text = text.replace(phrase, replacement)
    return text
