from __future__ import annotations

import re
from typing import Any

from .models import ComplianceReport, ResearchBundle, VideoPlan


SENSITIVE_PATTERNS = {
    "medical advice": r"\b(cure|diagnose|dosage|doctor says|miracle health|treat (cancer|diabetes|depression|disease|illness|infection|pain|patients?|symptoms?))\b",
    "financial promise": r"\b(guaranteed profit|get rich|double your money|investment advice)\b",
    "deceptive synthetic realism": r"\b(real footage|caught on camera|leaked audio|secret recording)\b",
    "defamation risk": r"\b(criminal|arrested|stole|fraudster|confessed)\b",
    "shock bait": r"\b(you won't believe|they don't want you to know|destroyed|exposed)\b",
}


def evaluate_plan(plan: VideoPlan, bundle: ResearchBundle, strategy: dict[str, Any]) -> ComplianceReport:
    flags: list[str] = []
    recommendations: list[str] = []
    risk = 0.0

    text = " ".join(
        [plan.topic, plan.angle, plan.title, plan.metadata.title, plan.metadata.description]
        + [scene.narration for scene in plan.scenes]
        + [scene.onscreen_text for scene in plan.scenes]
    ).lower()

    if len(plan.scenes) < 4:
        flags.append("Video has fewer than four scenes, which can look templated or low-effort.")
        recommendations.append("Add more original narrative beats and visual variety.")
        risk += 0.18

    if len({scene.visual_style.lower() for scene in plan.scenes}) < max(2, len(plan.scenes) // 3):
        flags.append("Visual styles are too repetitive for a monetization-safe original channel.")
        recommendations.append("Use distinct animated infographics, metaphors, charts, and transitions.")
        risk += 0.16

    for label, pattern in SENSITIVE_PATTERNS.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            flags.append(f"Potential {label} language detected.")
            risk += 0.22

    for blocked in strategy.get("blocked_terms", []):
        if str(blocked).lower() in text:
            flags.append(f"Blocked strategy term found: {blocked}")
            risk += 0.3

    copied = _find_source_overlap(plan, bundle)
    if copied:
        flags.append("Possible copied source wording detected in narration.")
        recommendations.append("Rewrite these lines in your own voice: " + "; ".join(copied[:2]))
        risk += 0.35

    if len(plan.metadata.hashtags) > 8:
        flags.append("Too many hashtags can look spammy.")
        recommendations.append("Keep hashtags focused, usually three to five.")
        risk += 0.08

    if not bundle.sources:
        flags.append("No source list is attached for factual grounding.")
        recommendations.append("Add source links to support factual claims.")
        risk += 0.2

    if not plan.copyright_notes:
        recommendations.append("Keep a per-video note that visuals, narration, and music are original or properly licensed.")

    passed = risk < 0.55 and not any("Blocked strategy term" in flag for flag in flags)
    if passed:
        recommendations.insert(0, "Ready for manual review or private upload.")
    else:
        recommendations.insert(0, "Review before upload; keep the video private until flags are cleared.")

    return ComplianceReport(
        passed=passed,
        risk_score=round(min(risk, 1.0), 2),
        flags=flags,
        recommendations=recommendations,
    )


def _find_source_overlap(plan: VideoPlan, bundle: ResearchBundle) -> list[str]:
    narration = " ".join(scene.narration for scene in plan.scenes).lower()
    matches: list[str] = []
    for source in bundle.sources:
        sentences = re.split(r"(?<=[.!?])\s+", source.excerpt)
        for sentence in sentences:
            sentence = re.sub(r"\s+", " ", sentence).strip()
            if len(sentence.split()) < 10:
                continue
            if sentence.lower() in narration:
                matches.append(sentence[:140])
    return matches
