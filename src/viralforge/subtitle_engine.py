from __future__ import annotations

import re

from .models import ScenePlan


HIGHLIGHT_WORDS = {
    "ai",
    "worker",
    "access",
    "risk",
    "keys",
    "human",
    "agent",
    "intern",
    "manager",
    "review",
    "task",
    "login",
}

CAPTION_STOP_WORDS = {
    "a",
    "an",
    "the",
    "with",
    "that",
    "this",
    "is",
    "be",
    "to",
    "of",
    "and",
    "or",
    "you",
    "your",
    "it",
    "its",
    "what",
}


def caption_for_time(scene: ScenePlan, local_time: float) -> tuple[list[tuple[str, bool]], float]:
    planned_groups = scene.caption_plan.get("kinetic_groups", []) if scene.caption_plan else []
    if planned_groups:
        duration = max(scene.duration_seconds, 0.1)
        group_count = max(1, len(planned_groups))
        group_index = min(group_count - 1, int(local_time / duration * group_count))
        group_progress = min(1.0, max(0.0, local_time / duration * group_count - group_index))
        words = [
            (str(item.get("word", "")), bool(item.get("highlight", False)))
            for item in planned_groups[group_index]
            if str(item.get("word", "")).strip()
        ]
        return words, group_progress
    words = scene.caption_words or _words(scene.narration)
    if not words:
        return [], 0.0
    duration = max(scene.duration_seconds, 0.1)
    words_per_group = 4
    group_count = max(1, (len(words) + words_per_group - 1) // words_per_group)
    group_index = min(group_count - 1, int(local_time / duration * group_count))
    start = group_index * words_per_group
    raw_group = words[start : start + words_per_group]
    group = [word for word in raw_group if word.lower().strip(".,:;!?") not in CAPTION_STOP_WORDS]
    if len(group) < 2:
        group = [word for word in words[start : start + words_per_group + 3] if word.lower().strip(".,:;!?") not in CAPTION_STOP_WORDS]
    group = group[:4] or raw_group[:3]
    group_start = group_index / group_count
    group_progress = min(1.0, max(0.0, local_time / duration * group_count - group_index))
    return [(word, word.lower().strip(".,:;!?") in HIGHLIGHT_WORDS) for word in group], group_progress


def keyword_chips(scene: ScenePlan) -> list[str]:
    labels = scene.caption_plan.get("ui_labels", []) if scene.caption_plan else []
    if labels:
        return [str(label).upper() for label in labels[:3]]
    text = f"{scene.headline_text} {scene.narration}".lower()
    priority = [
        ("agent", "AI AGENT"),
        ("intern", "AI AGENT"),
        ("browser", "BROWSER TAB"),
        ("login", "LOGIN"),
        ("worker", "WORKER"),
        ("task", "TASKS"),
        ("research", "RESEARCH"),
        ("admin", "ADMIN"),
        ("access", "ACCESS"),
        ("permission", "PERMISSIONS"),
        ("mistake", "MISTAKES"),
        ("review", "HUMAN REVIEW"),
        ("manager", "MANAGER"),
        ("keys", "THE KEYS"),
        ("clear", "CLEAR RULES"),
        ("boring", "BORING WORK"),
        ("hire", "HIRE ONE?"),
    ]
    result: list[str] = []
    for needle, label in priority:
        if needle in text and label not in result:
            result.append(label)
    blocked = {"YOUR", "THIS", "THAT", "WITH", "WHAT", "WHEN", "HUMAN", "NEW", "NOT"}
    for word in _words(scene.headline_text):
        upper = word.upper()
        if upper not in blocked and len(upper) > 3 and upper not in result:
            result.append(upper)
    return result[:3] or ["WATCH THIS", "FAST CONTEXT", "NO HYPE"]


def _words(value: str) -> list[str]:
    value = (value or "").replace("’", "'").replace("‘", "'")
    return [word for word in re.findall(r"[A-Za-z0-9']+", value) if word]
