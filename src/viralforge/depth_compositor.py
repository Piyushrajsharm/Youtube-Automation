from __future__ import annotations

from typing import Any


def layers_for_scene(scene: Any) -> list[dict[str, Any]]:
    theme = str(scene.visual_metaphor.get("theme", "ai_worker"))
    label_limit = 3
    return [
        {
            "type": "background",
            "name": str(scene.location),
            "motion": "slow_pan",
            "blur": 1.6,
            "parallax": -0.34,
        },
        {
            "type": "midground",
            "name": _midground_subject(theme),
            "motion": "depth_drift",
            "blur": 0.35,
            "parallax": -0.12,
        },
        {
            "type": "character",
            "name": "consistent presenter identity",
            "motion": "subtle_scale_pose_variation",
            "shadow": True,
            "rim_light": True,
            "depth_blur_behind": True,
            "parallax": 0.0,
        },
        {
            "type": "foreground_ui",
            "name": "readable holographic controls",
            "motion": "parallax_opposite",
            "label_limit": label_limit,
            "occludes_character": True,
            "parallax": 0.28,
        },
        {
            "type": "particles",
            "name": "drifting dust and sparks",
            "motion": "depth_drift",
            "parallax": 0.42,
        },
        {
            "type": "lens_light",
            "name": "light sweep and flare",
            "motion": "screen_space_sweep",
            "parallax": 0.55,
        },
    ]


def character_integration_for_scene(scene: Any) -> dict[str, Any]:
    theme = str(scene.visual_metaphor.get("theme", "ai_worker"))
    rim = {
        "risk": "cyan rim against red alarm light",
        "access": "cyan rim with gold key bounce",
        "control": "gold approval edge with teal UI wash",
        "question": "hero cyan outline and warm key light",
    }.get(theme, "cyan edge light matched to hologram")
    return {
        "rim_light": rim,
        "contact_shadow": True,
        "foreground_occlusion": True,
        "background_depth_blur": True,
        "pose_variation": ["closeup", "side_explain", "over_shoulder", "silhouette", "final_hero"],
        "repetition_rule": "do not use identical presenter framing for more than one shot",
    }


def _midground_subject(theme: str) -> str:
    return {
        "ai_worker": "AI employee badge and office task board",
        "speed": "fast workflow card lanes",
        "access": "permission vault and glowing key",
        "risk": "broken dashboard and alarm gate",
        "control": "approval console and audit shield",
        "question": "AI core with decision gates",
    }.get(theme, "holographic AI system")
