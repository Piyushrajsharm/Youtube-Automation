from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from .config import Settings
from .pexels_client import PexelsClient, PexelsProviderError, PexelsVideoCandidate
from .utils import read_json, write_json


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

PEXELS_USAGE_HISTORY = "pexels_usage_history.json"
RECENT_PEXELS_ID_LIMIT = 80
MAX_QUERY_COUNT = 16


def prepare_pexels_broll(
    output_dir: Path,
    settings: Settings,
    *,
    queries: list[str] | None = None,
    max_clips: int | None = None,
) -> list[PexelsVideoCandidate]:
    query_list = _dedupe_queries(queries or DEFAULT_PEXELS_QUERIES)
    target_count = max(1, int(max_clips or settings.pexels_max_clips))
    recent_ids = _recent_pexels_ids(settings.outputs_dir, output_dir)
    report_path = output_dir / "pexels_report.json"
    report: dict[str, object] = {
        "enabled": bool(settings.pexels_enabled and settings.pexels_video_enabled),
        "provider": "pexels",
        "mode": "video_search",
        "orientation": settings.pexels_orientation,
        "size": settings.pexels_size,
        "locale": settings.pexels_locale,
        "queries": query_list,
        "freshness": {
            "recent_id_count": len(recent_ids),
            "recent_ids_blocked": sorted(recent_ids)[-25:],
            "page_offset": _page_offset(output_dir),
            "max_query_count": MAX_QUERY_COUNT,
        },
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
        ranked_limit = max(target_count * 5, target_count + 10, 18)
        ranked_candidates, searches = client.collect_ranked_videos(
            query_list,
            per_query=14,
            max_items=ranked_limit,
            page_offset=_page_offset(output_dir),
            page_span=4,
        )
        selected = _select_fresh_candidates(ranked_candidates, recent_ids, target_count)
        report["searches"] = searches
        report["freshness"]["ranked_candidate_count"] = len(ranked_candidates)
        report["freshness"]["fresh_candidate_count"] = len([item for item in ranked_candidates if item.id not in recent_ids])
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
            cached = _cached_pexels_candidates(clips_dir, target_count)
            if cached:
                report["errors"].append("Using cached Pexels clips because fresh downloads were insufficient.")
                selected_with_files = cached
        report["selected"] = [candidate.to_dict() for candidate in selected_with_files]
        report["selected_count"] = len(selected_with_files)
        _update_pexels_usage(settings.outputs_dir, output_dir, selected_with_files)
        write_json(report_path, report)
        return selected_with_files
    except Exception as exc:
        report["errors"] = [f"{type(exc).__name__}: {exc}"]
        cached = _cached_pexels_candidates(clips_dir, target_count)
        if cached:
            report["errors"].append("Using cached Pexels clips because the provider request failed.")
            report["selected"] = [candidate.to_dict() for candidate in cached]
            report["selected_count"] = len(cached)
            write_json(report_path, report)
            return cached
        write_json(report_path, report)
        return []


def _dedupe_queries(queries: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for query in queries:
        normalized = re.sub(r"\s+", " ", query).strip()
        key = normalized.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
        if len(result) >= MAX_QUERY_COUNT:
            break
    return result or DEFAULT_PEXELS_QUERIES[:MAX_QUERY_COUNT]


def _page_offset(output_dir: Path) -> int:
    digest = hashlib.sha256(output_dir.name.encode("utf-8")).hexdigest()
    return int(digest[:6], 16) % 4


def _select_fresh_candidates(
    candidates: list[PexelsVideoCandidate],
    recent_ids: set[int],
    max_items: int,
) -> list[PexelsVideoCandidate]:
    selected: list[PexelsVideoCandidate] = []
    selected_ids: set[int] = set()
    query_counts: dict[str, int] = {}

    def add_from(pool: list[PexelsVideoCandidate], *, query_cap: int | None) -> None:
        for candidate in pool:
            if len(selected) >= max_items:
                return
            if candidate.id in selected_ids:
                continue
            if query_cap is not None and query_counts.get(candidate.query, 0) >= query_cap:
                continue
            selected.append(candidate)
            selected_ids.add(candidate.id)
            query_counts[candidate.query] = query_counts.get(candidate.query, 0) + 1

    fresh = [candidate for candidate in candidates if candidate.id not in recent_ids]
    reused = [candidate for candidate in candidates if candidate.id in recent_ids]
    add_from(fresh, query_cap=1)
    add_from(fresh, query_cap=2)
    add_from(fresh, query_cap=None)
    add_from(reused, query_cap=1)
    add_from(reused, query_cap=None)
    return selected[:max_items]


def _recent_pexels_ids(outputs_dir: Path, current_output_dir: Path) -> set[int]:
    recent: list[int] = []
    history_path = outputs_dir / PEXELS_USAGE_HISTORY
    if history_path.exists():
        try:
            data = read_json(history_path)
            for entry in data.get("entries", []):
                video_id = int(entry.get("id", 0) or 0)
                if video_id:
                    recent.append(video_id)
        except Exception:
            pass

    if outputs_dir.exists():
        reports = sorted(outputs_dir.glob("*/pexels_report.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for report_path in reports:
            if report_path.parent == current_output_dir:
                continue
            try:
                report = read_json(report_path)
            except Exception:
                continue
            for item in report.get("selected", []):
                video_id = int(item.get("id", 0) or 0)
                if video_id:
                    recent.append(video_id)
            if len(recent) >= RECENT_PEXELS_ID_LIMIT:
                break
    return set(recent[-RECENT_PEXELS_ID_LIMIT:])


def _update_pexels_usage(outputs_dir: Path, output_dir: Path, selected: list[PexelsVideoCandidate]) -> None:
    if not selected:
        return
    history_path = outputs_dir / PEXELS_USAGE_HISTORY
    entries: list[dict[str, object]] = []
    if history_path.exists():
        try:
            existing = read_json(history_path)
            raw_entries = existing.get("entries", [])
            if isinstance(raw_entries, list):
                entries = [entry for entry in raw_entries if isinstance(entry, dict)]
        except Exception:
            entries = []
    now = int(time.time())
    for candidate in selected:
        entries.append(
            {
                "id": candidate.id,
                "query": candidate.query,
                "url": candidate.url,
                "output_dir": str(output_dir),
                "used_at": now,
            }
        )
    write_json(history_path, {"entries": entries[-200:]})


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
