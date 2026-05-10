from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus

import feedparser
import requests

from .config import Settings
from .models import TrendItem
from .utils import clean_text, jaccard, token_set


USER_AGENT = "ViralForge/0.1 (+original-video-automation; contact=local)"

SENSITIVE_TREND_PATTERNS = (
    "treating",
    "diagnose",
    "dosage",
    "antibiotic",
    "panic attack",
    "depression",
    "eating disorder",
    "guaranteed profit",
    "stock pick",
    "crypto pump",
    "election fraud",
    "graphic",
    "leaked movie",
)

TECH_RELEVANCE_TERMS = {
    "ai",
    "agent",
    "app",
    "apple",
    "automation",
    "browser",
    "chip",
    "coding",
    "computer",
    "creator",
    "cyber",
    "data",
    "device",
    "digital",
    "gadget",
    "game",
    "gaming",
    "gemini",
    "google",
    "hacker",
    "hardware",
    "iphone",
    "laptop",
    "microsoft",
    "nvidia",
    "openai",
    "phone",
    "privacy",
    "robot",
    "science",
    "security",
    "software",
    "space",
    "startup",
    "tech",
    "technology",
    "tesla",
    "tool",
    "youtube",
}


def collect_trends(settings: Settings, strategy: dict[str, Any], limit: int = 20) -> list[TrendItem]:
    items: list[TrendItem] = []
    items.extend(_google_trends(settings, strategy))
    items.extend(_google_news(settings, strategy))
    items.extend(_reddit_hot(strategy))
    items.extend(_hacker_news())
    items = _filter_blocked(items, strategy.get("blocked_terms", []))
    items = _score_items(items, strategy)
    items = _dedupe_items(items)
    return sorted(items, key=lambda item: item.score, reverse=True)[:limit]


def collect_news_for_query(settings: Settings, query: str, limit: int = 6) -> list[TrendItem]:
    encoded = quote_plus(query)
    geo = settings.trend_geo
    language = settings.trend_language
    url = f"https://news.google.com/rss/search?q={encoded}&hl={language}-{geo}&gl={geo}&ceid={geo}:{language}"
    feed = _parse_feed(url)
    items = [
        TrendItem(
            title=clean_text(entry.get("title", "")),
            url=entry.get("link", url),
            source="google_news",
            published_at=_entry_date(entry),
            summary=clean_text(entry.get("summary", "")),
            tags=["news", query],
            score=4.0,
        )
        for entry in feed.entries[:limit]
        if entry.get("title")
    ]
    return items or [
        TrendItem(
            title=query,
            url=f"https://news.google.com/search?q={encoded}",
            source="manual_topic",
            summary="Manual topic supplied by the creator.",
            score=1.0,
        )
    ]


def _google_trends(settings: Settings, strategy: dict[str, Any]) -> list[TrendItem]:
    geo = str(strategy.get("geo") or settings.trend_geo).upper()
    url = f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo}"
    feed = _parse_feed(url)
    return [
        TrendItem(
            title=clean_text(entry.get("title", "")),
            url=entry.get("link", url),
            source="google_trends",
            published_at=_entry_date(entry),
            summary=clean_text(entry.get("summary", "")),
            tags=["trend", geo],
        )
        for entry in feed.entries
        if entry.get("title")
    ]


def _google_news(settings: Settings, strategy: dict[str, Any]) -> list[TrendItem]:
    geo = str(strategy.get("geo") or settings.trend_geo).upper()
    language = str(strategy.get("language") or settings.trend_language)
    queries = (
        list(strategy.get("google_news_queries") or strategy.get("niches") or settings.channel_niche)
        + list(strategy.get("format_queries", []))
    )
    results: list[TrendItem] = []
    for query in queries[:8]:
        encoded = quote_plus(str(query))
        url = f"https://news.google.com/rss/search?q={encoded}&hl={language}-{geo}&gl={geo}&ceid={geo}:{language}"
        feed = _parse_feed(url)
        for entry in feed.entries[:8]:
            if entry.get("title"):
                results.append(
                    TrendItem(
                        title=clean_text(entry.get("title", "")),
                        url=entry.get("link", url),
                        source="google_news",
                        published_at=_entry_date(entry),
                        summary=clean_text(entry.get("summary", "")),
                        tags=["news", str(query)],
                    )
                )
    return results


def _reddit_hot(strategy: dict[str, Any]) -> list[TrendItem]:
    results: list[TrendItem] = []
    for subreddit in strategy.get("subreddits", [])[:10]:
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=12"
        try:
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
            if response.status_code >= 400:
                continue
            payload = response.json()
        except (requests.RequestException, ValueError):
            continue
        for child in payload.get("data", {}).get("children", []):
            data = child.get("data", {})
            if data.get("stickied") or not data.get("title"):
                continue
            results.append(
                TrendItem(
                    title=clean_text(data.get("title", "")),
                    url=f"https://www.reddit.com{data.get('permalink', '')}",
                    source="reddit",
                    published_at=_timestamp_to_iso(data.get("created_utc")),
                    summary=clean_text(data.get("selftext", ""), 280),
                    score=float(data.get("score") or 0) / 1000.0,
                    tags=["reddit", f"r/{subreddit}"],
                )
            )
    return results


def _hacker_news() -> list[TrendItem]:
    url = "https://hn.algolia.com/api/v1/search?tags=front_page"
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return []
    results: list[TrendItem] = []
    for item in payload.get("hits", [])[:20]:
        title = clean_text(item.get("title") or item.get("story_title") or "")
        link = item.get("url") or f"https://news.ycombinator.com/item?id={item.get('objectID')}"
        if title and link:
            results.append(
                TrendItem(
                    title=title,
                    url=link,
                    source="hacker_news",
                    published_at=item.get("created_at"),
                    summary="",
                    score=float(item.get("points") or 0) / 100.0,
                    tags=["hacker_news"],
                )
            )
    return results


def _parse_feed(url: str) -> Any:
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
        if response.status_code >= 400:
            return feedparser.parse("")
        return feedparser.parse(response.content)
    except requests.RequestException:
        return feedparser.parse("")


def _entry_date(entry: Any) -> str | None:
    for key in ("published", "updated"):
        value = entry.get(key)
        if not value:
            continue
        try:
            return parsedate_to_datetime(value).astimezone(UTC).isoformat()
        except (TypeError, ValueError, AttributeError):
            return str(value)
    return None


def _timestamp_to_iso(value: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(value), tz=UTC).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _filter_blocked(items: list[TrendItem], blocked_terms: list[str]) -> list[TrendItem]:
    blocked = [term.lower() for term in blocked_terms] + list(SENSITIVE_TREND_PATTERNS)
    filtered = []
    for item in items:
        haystack = f"{item.title} {item.summary}".lower()
        if any(term in haystack for term in blocked):
            continue
        filtered.append(item)
    return filtered


def _score_items(items: list[TrendItem], strategy: dict[str, Any]) -> list[TrendItem]:
    weights = strategy.get("source_weights", {})
    niches = [str(niche) for niche in strategy.get("niches", [])]
    niche_tokens = set().union(*(token_set(niche) for niche in niches)) if niches else set()
    title_counts: dict[str, int] = {}
    for item in items:
        key = " ".join(sorted(token_set(item.title))[:8])
        title_counts[key] = title_counts.get(key, 0) + 1

    for item in items:
        source_weight = float(weights.get(item.source, 1.0))
        overlap = len(token_set(item.title) & niche_tokens)
        relevance = _tech_relevance(item)
        title_key = " ".join(sorted(token_set(item.title))[:8])
        cross_source_bonus = min(3.0, title_counts.get(title_key, 1) * 0.6)
        raw_attention = min(float(item.score), 3.0)
        niche_penalty = -1.25 if niche_tokens and overlap == 0 else 0.0
        tech_penalty = -4.0 if relevance == 0 else 0.0
        format_bonus = _format_bonus(item)
        item.score = round(
            source_weight
            + raw_attention
            + overlap * 0.9
            + relevance * 0.85
            + cross_source_bonus
            + format_bonus
            + niche_penalty
            + tech_penalty,
            3,
        )
    return items


def _tech_relevance(item: TrendItem) -> int:
    haystack = token_set(f"{item.title} {item.summary} {' '.join(item.tags)}")
    return len(haystack & TECH_RELEVANCE_TERMS)


def _format_bonus(item: TrendItem) -> float:
    text = f"{item.title} {item.summary} {' '.join(item.tags)}".lower()
    bonus = 0.0
    if any(word in text for word in ("quiz", "test", "guess", "challenge")):
        bonus += 0.55
    if any(word in text for word in ("funny", "comedy", "meme", "joke")):
        bonus += 0.45
    if any(word in text for word in ("breaking", "launch", "announces", "released", "update")):
        bonus += 0.35
    return bonus


def _dedupe_items(items: list[TrendItem]) -> list[TrendItem]:
    deduped: list[TrendItem] = []
    for item in sorted(items, key=lambda candidate: candidate.score, reverse=True):
        if any(jaccard(item.title, existing.title) > 0.62 for existing in deduped):
            continue
        deduped.append(item)
    return deduped
