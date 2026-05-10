from __future__ import annotations

from .models import ScenePlan


def classify_scene(scene: ScenePlan, text_context: str = "") -> str:
    text = f"{scene.purpose} {scene.emotion} {scene.headline_text} {scene.narration} {text_context}".lower()
    theme = str(scene.visual_metaphor.get("theme", "")).lower()
    if scene.purpose == "hook":
        return "cold_open"
    if scene.purpose == "cta":
        return "decision_cta"
    if scene.purpose == "warning" or theme in {"risk", "access"} or any(word in text for word in ("risk", "danger", "access", "keys", "guardrail")):
        return "danger_reveal"
    if scene.purpose == "control" or theme == "control" or any(word in text for word in ("review", "approve", "control", "audit", "permission")):
        return "safe_control"
    if scene.purpose == "reveal" or any(word in text for word in ("not just", "reveal", "suddenly", "becoming")):
        return "hero_reveal"
    if theme == "speed" or any(word in text for word in ("task", "boring", "speed", "deadline", "research")):
        return "montage"
    return "cinematic_explain"
