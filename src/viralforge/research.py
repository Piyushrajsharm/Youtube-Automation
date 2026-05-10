from __future__ import annotations

from typing import Iterable

import requests
from bs4 import BeautifulSoup

from .models import ResearchBundle, ResearchSource, TrendItem
from .trends import USER_AGENT
from .utils import clean_text


def build_research_bundle(topic: str, trend_items: Iterable[TrendItem], max_sources: int = 6) -> ResearchBundle:
    sources: list[ResearchSource] = []
    for item in list(trend_items)[:max_sources]:
        excerpt = item.summary or _fetch_excerpt(item.url)
        sources.append(
            ResearchSource(
                title=item.title,
                url=item.url,
                source=item.source,
                excerpt=clean_text(excerpt, 900),
                published_at=item.published_at,
            )
        )
    angle = _derive_angle(topic, sources)
    notes = [
        "Use these sources only for factual grounding; do not copy article wording.",
        "Do not scrape or reuse third-party images, clips, voices, music, or logos.",
    ]
    return ResearchBundle(topic=topic, angle=angle, sources=sources, notes=notes)


def _fetch_excerpt(url: str) -> str:
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
        if response.status_code >= 400:
            return ""
    except requests.RequestException:
        return ""

    soup = BeautifulSoup(response.text, "html.parser")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    meta = soup.find("meta", attrs={"name": "description"})
    parts: list[str] = []
    if meta and meta.get("content"):
        parts.append(str(meta["content"]))
    for paragraph in soup.find_all("p"):
        text = clean_text(paragraph.get_text(" "))
        if len(text) >= 60:
            parts.append(text)
        if len(" ".join(parts)) > 1100:
            break
    return clean_text(" ".join(parts), 1100)


def _derive_angle(topic: str, sources: list[ResearchSource]) -> str:
    source_names = ", ".join(sorted({source.source for source in sources})) or "trend sources"
    return f"Explain why '{topic}' is suddenly getting attention, using original animated analysis grounded by {source_names}."

