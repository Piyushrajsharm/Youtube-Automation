from __future__ import annotations

import re
from pathlib import Path

from .config import Settings
from .pexels_client import PexelsClient, PexelsProviderError, PexelsVideoCandidate
from .utils import write_json


DEFAULT_PEXELS_QUERIES = [
    "AI technology office",
    "business team laptop",
    "cyber security server room",
    "software developer coding",
    "data center lights",
    "startup office meeting",
    "automation robot technology",
    "digital dashboard computer",
    "person working on laptop night",
    "business presentation screen",
    "futuristic technology",
    "team collaboration startup",
]


def prepare_pexels_broll(
    output_dir: Path,
    settings: Settings,
    *,
    queries: list[str] | None = None,
    max_clips: int | None = None,
) -> list[PexelsVideoCandidate]:
    report_path = output_dir / "pexels_report.json"
    report: dict[str, object] = {
        "enabled": bool(settings.pexels_enabled and settings.pexels_video_enabled),
        "provider": "pexels",
        "mode": "video_search",
        "orientation": settings.pexels_orientation,
        "size": settings.pexels_size,
        "locale": settings.pexels_locale,
        "queries": queries or DEFAULT_PEXELS_QUERIES,
        "selected_count": 0,
        "downloaded_count": 0,
        "license_summary": {
            "license": "Pexels License",
            "commercial_use": True,
            "attribution_required": False,
            "license_url": "https://www.pexels.com/license/",
            "risk_notes": [
                "Do not imply people, brands, or trademarks shown in footage endorse the video.",
                "Avoid using identifiable people in offensive or misleading contexts.",
                "Downloaded clips are transformed with edits, overlays, sound design, and narration.",
            ],
        },
        "searches": [],
        "selected": [],
        "errors": [],
    }
    if not settings.pexels_enabled or not settings.pexels_video_enabled:
        write_json(report_path, report)
        return []
    if not settings.pexels_api_key:
        report["errors"] = ["PEXELS_API_KEY is not configured."]
        write_json(report_path, report)
        return []

    client = PexelsClient(settings)
    clips_dir = output_dir / "pexels_clips"
    try:
        selected, searches = client.collect_ranked_videos(
            queries or DEFAULT_PEXELS_QUERIES,
            per_query=12,
            max_items=max_clips or settings.pexels_max_clips,
        )
        report["searches"] = searches
        report["selected_count"] = len(selected)
        downloaded = 0
        for candidate in selected:
            try:
                client.download_video(candidate, clips_dir)
                downloaded += 1
            except PexelsProviderError as exc:
                report["errors"].append(str(exc))
        report["downloaded_count"] = downloaded
        selected_with_files = [candidate for candidate in selected if candidate.local_path]
        if len(selected_with_files) < 2:
            cached = _cached_pexels_candidates(clips_dir, max_clips or settings.pexels_max_clips)
            if cached:
                report["errors"].append("Using cached Pexels clips because fresh downloads were insufficient.")
                selected_with_files = cached
        report["selected"] = [candidate.to_dict() for candidate in selected_with_files]
        report["selected_count"] = len(selected_with_files)
        write_json(report_path, report)
        return selected_with_files
    except Exception as exc:
        report["errors"] = [f"{type(exc).__name__}: {exc}"]
        cached = _cached_pexels_candidates(clips_dir, max_clips or settings.pexels_max_clips)
        if cached:
            report["errors"].append("Using cached Pexels clips because the provider request failed.")
            report["selected"] = [candidate.to_dict() for candidate in cached]
            report["selected_count"] = len(cached)
            write_json(report_path, report)
            return cached
        write_json(report_path, report)
        return []


def _cached_pexels_candidates(clips_dir: Path, max_items: int) -> list[PexelsVideoCandidate]:
    candidates: list[PexelsVideoCandidate] = []
    if not clips_dir.exists():
        return candidates
    for index, path in enumerate(sorted(clips_dir.glob("*.mp4"))):
        if len(candidates) >= max_items:
            break
        if not path.is_file() or path.stat().st_size <= 0:
            continue
        match = re.match(r"pexels_(\d+)_([^.]+)", path.name)
        video_id = int(match.group(1)) if match else index + 1
        query = match.group(2).replace("-", " ") if match else "cached pexels clip"
        candidates.append(
            PexelsVideoCandidate(
                id=video_id,
                url="",
                image="",
                duration=0,
                width=1080,
                height=1920,
                user_name="Pexels",
                user_url="https://www.pexels.com/",
                query=query,
                score=5.0 - index * 0.05,
                download_url="",
                download_quality="cached",
                download_width=1080,
                download_height=1920,
                local_path=path,
            )
        )
    return candidates
