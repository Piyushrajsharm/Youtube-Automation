from __future__ import annotations

import re
from typing import Any

from .models import ScenePlan


POWER_WORDS = {
    "ai",
    "agent",
    "intern",
    "worker",
    "access",
    "risk",
    "keys",
    "human",
    "review",
    "control",
    "guardrails",
    "chaos",
    "approve",
}

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "but",
    "for",
    "from",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "with",
    "you",
    "your",
    "here's",
    "there's",
    "they're",
    "we're",
    "i'm",
    "they",
    "them",
    "their",
}

DANGLING_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "but",
    "for",
    "from",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "the",
    "then",
    "to",
    "with",
    "will",
    "would",
    "your",
}

TRAILER_REWRITES = [
    (("intern", "breaks"), "Your intern never takes breaks"),
    (("intern", "human"), "Your intern is not human"),
    (("chatbot", "worker"), "Not a chatbot. A worker"),
    (("self", "taught", "ai"), "Self taught AI beats expectations"),
    (("draft", "onboard"), "AI agents handle real work"),
    (("onboarding", "employees"), "Treat AI like employees"),
    (("cost", "falling"), "Waiting has a real cost"),
    (("boring", "work"), "Boring work is next"),
    (("access",), "It will ask for access"),
    (("risk",), "The risk is access"),
    (("no", "guardrails"), "No guardrails means chaos"),
    (("guardrail",), "Guardrails stop the chaos"),
    (("review",), "A human must review"),
    (("keys",), "Who gets the keys?"),
    (("hire",), "Would you hire one?"),
    (("cost",), "Waiting has a cost"),
    (("train",), "Train it before chaos"),
]


def clean_headline(raw: str, narration: str, purpose: str, *, ellipsis_allowed: bool = False) -> tuple[str, bool]:
    text = _normalize(raw) or _first_sentence(narration)
    text = _rewrite_if_broken(text, narration, purpose)
    text = text.replace("AI interns", "AI intern")
    text = re.sub(r"\s*[:;]\s*", ": ", text)
    used_ellipsis = "..." in text or "…" in text
    if used_ellipsis and not ellipsis_allowed:
        text = _rewrite_if_broken("", narration, purpose)
        used_ellipsis = False
    text = re.sub(r"[.]{2,}|…", "", text).strip()
    text = _complete_phrase(text, narration, purpose)
    text = _limit_headline_words(text, narration, purpose)
    text = _complete_phrase(text, narration, purpose)
    if purpose == "cta" and "?" not in text:
        text = "Would you hire one?"
    return text, used_ellipsis


def caption_plan_for(scene: ScenePlan) -> dict[str, Any]:
    words = _words(scene.narration)
    kinetic_groups = _kinetic_groups(words)
    labels = _ui_labels(scene.headline_text, scene.narration, scene.visual_metaphor)
    return {
        "headline": scene.headline_text,
        "kinetic_groups": kinetic_groups,
        "ui_labels": labels,
        "safe_margin": 90,
        "rules": {
            "headline_words": "3-7",
            "kinetic_caption_words": "2-5",
            "max_ellipsis_headlines": 2,
            "label_limit": 3,
        },
    }


def _normalize(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    return value.strip(" -_")


def _first_sentence(text: str) -> str:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text or "") if part.strip()]
    return parts[0] if parts else text


def _rewrite_if_broken(text: str, narration: str, purpose: str) -> str:
    combined = f"{text} {narration}".lower()
    if purpose == "cta":
        return "Would you hire one?"
    forced = {
        ("no", "guardrails"),
        ("self", "taught", "ai"),
        ("intern", "breaks"),
        ("draft", "onboard"),
        ("onboarding", "employees"),
        ("cost", "falling"),
    }
    for needles, replacement in TRAILER_REWRITES:
        if needles in forced and all(
            needle in combined for needle in needles
        ):
            return replacement
    if not text or _looks_incomplete(text):
        for needles, replacement in TRAILER_REWRITES:
            if all(needle in combined for needle in needles):
                return replacement
    if len(_words(text)) > 9:
        for needles, replacement in TRAILER_REWRITES:
            if all(needle in combined for needle in needles):
                return replacement
    return text


def _looks_incomplete(text: str) -> bool:
    stripped = text.strip()
    if stripped.endswith(("...", "…", "-", ":", ";", ",")):
        return True
    words = _words(stripped)
    if not words:
        return True
    last = words[-1].lower()
    return last in DANGLING_WORDS or stripped.lower().endswith((" no", " no.", " or", " and", " will"))


def _complete_phrase(text: str, narration: str, purpose: str) -> str:
    words = _words(text)
    while words and words[-1].lower() in DANGLING_WORDS:
        words.pop()
    if not words:
        return _rewrite_if_broken("", narration, purpose)
    rebuilt = " ".join(words)
    if len(words) < 3 and purpose != "cta":
        fallback = _rewrite_if_broken("", narration, purpose)
        if fallback:
            return fallback
    if text.strip().endswith("?"):
        return rebuilt + "?"
    return rebuilt


def _limit_headline_words(text: str, narration: str, purpose: str) -> str:
    words = _words(text)
    if 3 <= len(words) <= 7:
        return _restore_question(text, words)
    fallback = _rewrite_if_broken("", narration, purpose)
    fallback_words = _words(fallback)
    if 3 <= len(fallback_words) <= 7:
        return fallback
    if len(words) > 7:
        words = words[:7]
        while words and words[-1].lower() in DANGLING_WORDS:
            words.pop()
    if len(words) < 3:
        words = (words + _words(narration))[:5]
    return _restore_question(text, words)


def _restore_question(source: str, words: list[str]) -> str:
    value = " ".join(words).strip()
    if source.strip().endswith("?") and value and not value.endswith("?"):
        value += "?"
    return value


def _kinetic_groups(words: list[str]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    cursor = 0
    while cursor < len(words):
        remaining = len(words) - cursor
        take = remaining if remaining <= 5 else 4
        if remaining == 6 and cursor + 2 < len(words) and words[cursor + 2].lower() in {"not", "no", "without"}:
            take = 4
        group_words = words[cursor : cursor + take]
        if len(group_words) == 1 and groups:
            groups[-1].append(
                {
                    "word": group_words[0],
                    "highlight": group_words[0].lower().strip(".,:;!?") in POWER_WORDS,
                }
            )
            cursor += take
            continue
        groups.append(
            [
                {
                    "word": word,
                    "highlight": word.lower().strip(".,:;!?") in POWER_WORDS,
                }
                for word in group_words[:5]
            ]
        )
        cursor += take
    return groups[:8]


def _ui_labels(headline: str, narration: str, metaphor: dict[str, Any]) -> list[str]:
    theme = str(metaphor.get("theme", ""))
    by_theme = {
        "ai_worker": ["AI BADGE", "TASK QUEUE", "ONBOARD"],
        "speed": ["TASKS", "DRAFT", "DONE"],
        "access": ["ACCESS", "KEY", "LOCK"],
        "risk": ["RISK", "ALERT", "VAULT"],
        "control": ["REVIEW", "APPROVE", "LOGS"],
        "question": ["HIRE?", "KEYS", "CONTROL"],
    }
    labels = list(by_theme.get(theme, []))
    for word in _words(f"{headline} {narration}"):
        upper = word.upper()
        if word.lower() in POWER_WORDS and upper not in labels:
            labels.append(upper)
    return labels[:3] or ["AI", "WORK", "CONTROL"]


def _words(value: str) -> list[str]:
    value = (value or "").replace("’", "'").replace("‘", "'")
    return [word for word in re.findall(r"[A-Za-z0-9']+", value or "") if word]
