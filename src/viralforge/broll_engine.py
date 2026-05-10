from __future__ import annotations

from typing import Any


BROLL_LIBRARY: dict[str, dict[str, Any]] = {
    "ai_office": {
        "environment": "futuristic office bay with floating task boards",
        "metaphor": "holographic employee badge",
        "objects": ["AI employee badge", "desk hologram", "self-updating checklist"],
        "motion": "subtle parallax office depth with cursor trails",
    },
    "task_montage": {
        "environment": "automation workflow tunnel",
        "metaphor": "task cards moving like a production line",
        "objects": ["research card", "draft card", "check card", "send card"],
        "motion": "fast lateral streaks and stamp-complete hits",
    },
    "vault_access": {
        "environment": "red-lit digital permission vault",
        "metaphor": "glowing key reaching a locked vault",
        "objects": ["digital key", "vault wheel", "permission gate"],
        "motion": "push-in with alarm pulse and sparks",
    },
    "human_review": {
        "environment": "secure human review cockpit",
        "metaphor": "manager approval screen",
        "objects": ["approve button", "audit log", "permission shield"],
        "motion": "steady review push with checkmark pop",
    },
    "chaos_dashboard": {
        "environment": "broken operations dashboard",
        "metaphor": "guardrails missing from a red alert system",
        "objects": ["red alert panel", "broken graph", "glitching access card"],
        "motion": "shake, glitch, and warning rings",
    },
    "server_room": {
        "environment": "deep server room with resolving signal paths",
        "metaphor": "safe workflow routes through a server vault",
        "objects": ["server aisles", "light paths", "green completion nodes"],
        "motion": "dolly through server rows with light beams",
    },
    "final_hero_system": {
        "environment": "hero hologram chamber",
        "metaphor": "human holding the keys to an AI system",
        "objects": ["floating key", "AI core", "decision gates"],
        "motion": "low-angle push with final light bloom",
    },
}


def broll_for_scene(scene: Any, shot_sequence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clips: list[dict[str, Any]] = []
    for shot in shot_sequence:
        broll_type = str(shot.get("broll_type") or "")
        if not broll_type:
            continue
        preset = BROLL_LIBRARY.get(broll_type)
        if not preset:
            continue
        clips.append(
            {
                "clip_id": f"{scene.scene_id}_{broll_type}_{len(clips) + 1:02d}",
                "type": broll_type,
                "start": shot.get("start", 0.0),
                "end": shot.get("end", 0.0),
                "duration": round(float(shot.get("end", 0.0)) - float(shot.get("start", 0.0)), 2),
                "visual_metaphor": preset["metaphor"],
                "environment": preset["environment"],
                "camera": shot.get("camera", preset["motion"]),
                "transition": shot.get("transition", "whip_cut"),
                "objects": list(preset["objects"]),
                "motion": preset["motion"],
                "prompt": _prompt_for(scene, broll_type, preset, shot),
            }
        )
    return clips


def _prompt_for(scene: Any, broll_type: str, preset: dict[str, Any], shot: dict[str, Any]) -> str:
    return (
        f"Vertical cinematic micro-clip: {preset['environment']}. "
        f"Visual metaphor: {preset['metaphor']}. Objects: {', '.join(preset['objects'])}. "
        f"Motion: {preset['motion']}. Camera: {shot.get('camera')}. "
        f"Scene headline: {getattr(scene, 'headline_text', '')}. Original, no logos, no copyrighted characters."
    )
