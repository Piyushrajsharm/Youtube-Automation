from __future__ import annotations

import re
from typing import Any


VISUAL_METAPHORS: dict[str, dict[str, Any]] = {
    "access": {
        "theme": "access",
        "objects": ["glowing digital vault", "permission gate", "floating security key", "locked approval rails"],
        "action": "vault door pulses while a key waits for human approval",
        "color_bias": "red and gold warning glow",
    },
    "ai_worker": {
        "theme": "ai_worker",
        "objects": ["holographic employee badge", "task queue wall", "autonomous workflow nodes", "agent command badge"],
        "action": "AI worker badge assembles from moving data shards",
        "color_bias": "cyan and amber productivity glow",
    },
    "risk": {
        "theme": "risk",
        "objects": ["red warning light", "firewall crack", "alarm particles", "glitching permission screen"],
        "action": "firewall fractures for one frame before snapping back",
        "color_bias": "red danger flash with cold cyan edges",
    },
    "control": {
        "theme": "control",
        "objects": ["human approval button", "audit log tower", "permission shield", "review console"],
        "action": "approval shield locks around the system after a human click",
        "color_bias": "teal, white, and gold trust glow",
    },
    "speed": {
        "theme": "speed",
        "objects": ["fast task lanes", "progress rails", "flying report cards", "automation conveyor"],
        "action": "tasks streak across the room and stamp complete",
        "color_bias": "cyan speed lines with warm impact sparks",
    },
    "question": {
        "theme": "question",
        "objects": ["digital key between human hand and AI system", "yes/no decision gates", "final hiring badge"],
        "action": "key floats toward the viewer, waiting for a decision",
        "color_bias": "hero gold with cyan rim light",
    },
}


WORLD_PRESETS: dict[str, dict[str, Any]] = {
    "hook": {
        "location": "dark futuristic AI command room",
        "foreground": ["transparent holographic UI panel", "AI employee badge", "slow cursor blink"],
        "midground": "presenter in rim light making direct eye contact",
        "background": "server cores stacked like skyscrapers with moving blue light beams",
        "atmosphere": "volumetric fog, drifting dust, subtle smoke layers",
        "lighting": {
            "key_light": "soft teal from hologram",
            "rim_light": "strong cyan edge light",
            "background_light": "slow moving server glow",
        },
    },
    "problem": {
        "location": "automation operations floor",
        "foreground": ["task cards flying past camera", "progress rails", "scan lines"],
        "midground": "agent dashboard executing repetitive work",
        "background": "rows of dark workstations fading into haze",
        "atmosphere": "motion dust, thin fog, quick light streaks",
        "lighting": {
            "key_light": "cool overhead grid",
            "rim_light": "thin amber task-line highlights",
            "background_light": "moving conveyor glow",
        },
    },
    "reveal": {
        "location": "hologram chamber",
        "foreground": ["floating workflow graph", "agent badge shards", "approval cursor"],
        "midground": "presenter points toward a huge holographic worker profile",
        "background": "circular AI core with rotating rings",
        "atmosphere": "dense particles and shallow depth haze",
        "lighting": {
            "key_light": "bright cyan hologram wash",
            "rim_light": "white rim on shoulders",
            "background_light": "gold reveal pulse",
        },
    },
    "warning": {
        "location": "red-lit digital vault",
        "foreground": ["glowing security key", "alarm particles", "cracked permission glass"],
        "midground": "vault door and permission warning screen",
        "background": "black server vault with red emergency strobes",
        "atmosphere": "smoke, sparks, glitch distortion, hard shadows",
        "lighting": {
            "key_light": "low red alarm flash",
            "rim_light": "cyan edge light through smoke",
            "background_light": "strobing vault warning",
        },
    },
    "control": {
        "location": "human review cockpit",
        "foreground": ["approval button", "audit log ribbon", "permission shield"],
        "midground": "manager console with narrow task permissions",
        "background": "glass review walls and secured data lanes",
        "atmosphere": "clean haze, controlled particles, premium trust glow",
        "lighting": {
            "key_light": "balanced teal UI glow",
            "rim_light": "gold approval edge",
            "background_light": "white audit trail shimmer",
        },
    },
    "payoff": {
        "location": "server vault opening into daylight",
        "foreground": ["finished task cards", "safe-control rails", "speed streaks"],
        "midground": "AI workflow completing under human supervision",
        "background": "massive system map resolving into clean green signals",
        "atmosphere": "light fog, gold dust, soft lens flare",
        "lighting": {
            "key_light": "warm payoff glow",
            "rim_light": "cyan technical edge",
            "background_light": "rising gold beams",
        },
    },
    "cta": {
        "location": "final hero hologram chamber",
        "foreground": ["digital key floating toward camera", "yes/no decision gates", "hiring badge"],
        "midground": "human manager faces the viewer beside the AI system",
        "background": "massive holographic AI core and deep command-room architecture",
        "atmosphere": "hero particles, volumetric beams, cinematic fog",
        "lighting": {
            "key_light": "gold key light on face",
            "rim_light": "strong cyan heroic outline",
            "background_light": "epic final beam sweep",
        },
    },
}


def visual_metaphor_for(text: str, purpose: str, scene_index: int) -> dict[str, Any]:
    value = text.lower()
    if any(word in value for word in ("risk", "danger", "mistake", "wrong", "wide access", "alarm")):
        return dict(VISUAL_METAPHORS["risk"])
    if any(word in value for word in ("access", "permission", "key", "keys", "login", "touch")):
        return dict(VISUAL_METAPHORS["access"])
    if any(word in value for word in ("review", "approve", "manager", "control", "rules", "safe")):
        return dict(VISUAL_METAPHORS["control"])
    if any(word in value for word in ("boring", "task", "admin", "research", "finished", "reports")):
        return dict(VISUAL_METAPHORS["speed"])
    if purpose == "cta" or "?" in value or "hire" in value:
        return dict(VISUAL_METAPHORS["question"])
    if any(word in value for word in ("agent", "intern", "worker", "chatbot", "employee")):
        return dict(VISUAL_METAPHORS["ai_worker"])

    cycle = ["ai_worker", "speed", "control", "access"]
    return dict(VISUAL_METAPHORS[cycle[scene_index % len(cycle)]])


def world_for(purpose: str, metaphor: dict[str, Any]) -> dict[str, Any]:
    if purpose == "hook" and metaphor.get("theme") != "risk":
        return dict(WORLD_PRESETS["hook"])
    if metaphor.get("theme") == "risk":
        return dict(WORLD_PRESETS["warning"])
    if metaphor.get("theme") == "access":
        return dict(WORLD_PRESETS["warning"])
    if metaphor.get("theme") == "control":
        return dict(WORLD_PRESETS["control"])
    if metaphor.get("theme") == "speed":
        return dict(WORLD_PRESETS["problem"])
    if metaphor.get("theme") == "question":
        return dict(WORLD_PRESETS["cta"])
    return dict(WORLD_PRESETS.get(purpose, WORLD_PRESETS["hook"]))


def cinematic_prompt_for(
    *,
    topic: str,
    purpose: str,
    narration: str,
    world: dict[str, Any],
    metaphor: dict[str, Any],
    shot_type: str,
) -> str:
    objects = ", ".join(metaphor.get("objects", []))
    lighting = world.get("lighting", {})
    lighting_text = ", ".join(str(value) for value in lighting.values())
    clean_narration = re.sub(r"\s+", " ", narration).strip()
    return (
        f"Vertical cinematic frame about {topic}. {world.get('location')}, {world.get('atmosphere')}, "
        f"{world.get('midground')}, {world.get('background')}. Foreground: {objects}. "
        f"Shot type: {shot_type}. Lighting: {lighting_text}. Mood: {purpose}, premium sci-fi commercial, "
        f"high contrast, shallow depth of field, dynamic composition. Narration beat: {clean_narration}"
    )
