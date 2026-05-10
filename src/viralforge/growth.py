from __future__ import annotations

import re
from typing import Any

from .config import Settings
from .models import ResearchBundle, UploadMetadata, VideoPlan
from .utils import clean_text, dedupe_strings


def finalize_metadata(plan: VideoPlan, bundle: ResearchBundle, settings: Settings, strategy: dict[str, Any]) -> UploadMetadata:
    growth = strategy.get("growth_strategy", {})
    title_max = int(growth.get("title_max_chars", 78))
    max_hashtags = int(growth.get("max_hashtags", 5))

    title = _sanitize_title(plan.metadata.title or plan.title or bundle.topic, title_max)
    hashtags = _normalize_hashtags(
        plan.metadata.hashtags + _trend_hashtags(plan, bundle, strategy) + list(growth.get("default_hashtags", [])),
        max_hashtags=max_hashtags,
    )
    tags = _limit_tags(plan.metadata.tags + [bundle.topic] + list(strategy.get("niches", [])))
    description = _build_description(plan, bundle, hashtags, growth)

    return UploadMetadata(
        title=title,
        description=description,
        hashtags=hashtags,
        tags=tags,
        category_id=settings.youtube_category_id,
        privacy_status=settings.youtube_privacy_status,
        contains_synthetic_media=settings.youtube_contains_synthetic_media or plan.metadata.contains_synthetic_media,
        made_for_kids=settings.youtube_made_for_kids or plan.metadata.made_for_kids,
    )


def _sanitize_title(title: str, max_chars: int) -> str:
    title = re.sub(r"[<>]", "", clean_text(title))
    if len(title) > max_chars:
        title = title[: max_chars - 1].rstrip(" -:|") + "..."
    return title or "A Trend Explained in 60 Seconds"


def _normalize_hashtags(values: list[str], max_hashtags: int) -> list[str]:
    normalized: list[str] = []
    for value in values:
        tag = re.sub(r"[^A-Za-z0-9_]", "", value.replace("#", ""))
        if tag:
            normalized.append(f"#{tag[:40]}")
    return dedupe_strings(normalized)[:max_hashtags]


def _trend_hashtags(plan: VideoPlan, bundle: ResearchBundle, strategy: dict[str, Any]) -> list[str]:
    text = " ".join(
        [
            plan.topic,
            plan.angle,
            plan.title,
            bundle.topic,
            bundle.angle,
            " ".join(source.title for source in bundle.sources),
        ]
    ).lower()
    tags = ["#TrendingTech", "#TechNews"]
    taxonomy = [
        (("ai", "agent", "automation", "chatbot", "openai", "gemini", "nvidia", "machine learning"), "#AI"),
        (("startup", "founder", "business", "work", "office", "employee", "intern"), "#FutureOfWork"),
        (("phone", "iphone", "android", "samsung", "apple", "gadget", "device", "wearable"), "#Gadgets"),
        (("security", "hack", "breach", "password", "privacy", "malware", "cyber"), "#Cybersecurity"),
        (("quiz", "test", "guess", "challenge", "question"), "#TechQuiz"),
        (("funny", "comedy", "meme", "joke", "roast"), "#TechComedy"),
        (("science", "space", "robot", "chip", "semiconductor", "quantum"), "#ScienceTech"),
    ]
    for needles, hashtag in taxonomy:
        if any(needle in text for needle in needles):
            tags.append(hashtag)
    for niche in strategy.get("niches", []):
        niche_text = str(niche).lower()
        if "creator" in niche_text:
            tags.append("#CreatorTools")
        if "tool" in niche_text:
            tags.append("#AITools")
    return tags


def _limit_tags(values: list[str]) -> list[str]:
    tags = [clean_text(re.sub(r"[<>]", "", value), 45) for value in values if clean_text(value)]
    limited: list[str] = []
    total = 0
    for tag in dedupe_strings(tags):
        projected = total + len(tag) + (1 if limited else 0)
        if projected > 450:
            break
        limited.append(tag)
        total = projected
    return limited


def _build_description(
    plan: VideoPlan,
    bundle: ResearchBundle,
    hashtags: list[str],
    growth: dict[str, Any],
) -> str:
    # Line 1-2: Primary keyword + hook (YouTube indexes these heavily)
    topic_line = clean_text(plan.angle or bundle.angle, 360)

    # Source citations
    source_lines = []
    for index, source in enumerate(bundle.sources[:6], start=1):
        source_lines.append(f"{index}. {source.title} - {source.url}")

    # AI disclosure
    disclosure = "Original animated explainer. No third-party footage, images, music, or cloned voices are used by this automation."
    if plan.metadata.contains_synthetic_media:
        disclosure += " Synthetic/altered media disclosure should remain enabled for this upload."

    # Build SEO-optimized description
    body = "\n".join(
        [
            # First 2 lines = most important for SEO (visible above "Show more")
            f"{bundle.topic} — {topic_line}",
            "",
            # CTA + engagement hook
            "🔔 Subscribe for daily tech in 60 seconds!",
            "💬 Drop a comment: Would you use this?",
            "",
            # Value summary for search indexing
            f"In this Short, we break down why {bundle.topic} matters right now and what it means for you.",
            "",
            # Disclosure
            disclosure,
            "",
            # Sources (builds trust + E-E-A-T signals)
            "📚 Sources:",
            *source_lines,
            "",
            # Hashtags at the end (YouTube surfaces these in search)
            " ".join(hashtags),
        ]
    ).strip()

    max_chars = int(growth.get("description_max_chars", 4500))
    if len(body) > max_chars:
        body = body[: max_chars - 1].rstrip() + "..."
    return body

