from __future__ import annotations


CHARACTER_ACTIONS: dict[str, list[str]] = {
    "hook": ["slow_head_turn", "eye_contact", "raise_hand"],
    "problem": ["checks_dashboard", "quick_glance", "controlled_energy"],
    "reveal": ["point_to_hologram", "confident_smile", "step_forward"],
    "warning": ["serious_face", "step_forward", "low_light_shadow"],
    "control": ["approval_gesture", "calm_eye_contact", "open_palm"],
    "payoff": ["relieved_confidence", "nod", "turn_to_results"],
    "cta": ["direct_eye_contact", "hand_forward", "final_hold"],
}


CHARACTER_EXPRESSIONS = {
    "hook": "serious confidence",
    "problem": "focused urgency",
    "reveal": "confident reveal",
    "warning": "controlled concern",
    "control": "calm authority",
    "payoff": "earned confidence",
    "cta": "direct challenge",
}


def character_for(purpose: str, shot_type: str, scene_index: int) -> dict[str, str | list[str]]:
    actions = CHARACTER_ACTIONS.get(purpose, CHARACTER_ACTIONS["reveal"])
    if shot_type in {"hero_closeup", "impact_reveal"}:
        pose = "close-up eye contact"
        blocking = "camera close, face rim-lit, shoulders partly cropped"
    elif shot_type == "over_shoulder":
        pose = "over-shoulder toward hologram"
        blocking = "presenter foreground silhouette with UI beyond"
    elif shot_type == "final_hero":
        pose = "low-angle hero stance"
        blocking = "presenter centered-right with digital key in foreground"
    elif shot_type == "ui_macro":
        pose = "off-screen reaction"
        blocking = "hands and reflected face only, UI dominates frame"
    else:
        pose = "medium explainer stance"
        blocking = "presenter stands beside active hologram panels"

    return {
        "pose": pose,
        "gesture": actions[scene_index % len(actions)],
        "secondary_gesture": actions[(scene_index + 1) % len(actions)],
        "expression": CHARACTER_EXPRESSIONS.get(purpose, "confident"),
        "eye_line": "direct to viewer" if purpose in {"hook", "cta", "warning"} else "between viewer and hologram",
        "movement": "micro head turn, shoulder shift, hand emphasis, simulated mouth movement",
        "blocking": blocking,
    }
