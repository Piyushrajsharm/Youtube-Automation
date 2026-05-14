from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .config import Settings
from .utils import ensure_dir


class PexelsProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class PexelsVideoCandidate:
    id: int
    url: str
    image: str
    duration: int
    width: int
    height: int
    user_name: str
    user_url: str
    query: str
    score: float
    download_url: str
    download_quality: str
    download_width: int
    download_height: int
    local_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "image": self.image,
            "duration": self.duration,
            "width": self.width,
            "height": self.height,
            "user_name": self.user_name,
            "user_url": self.user_url,
            "query": self.query,
            "score": round(self.score, 3),
            "download_url": self.download_url,
            "download_quality": self.download_quality,
            "download_width": self.download_width,
            "download_height": self.download_height,
            "local_path": str(self.local_path) if self.local_path else None,
            "license": "Pexels License",
            "license_url": "https://www.pexels.com/license/",
            "commercial_use": True,
            "attribution_required": False,
        }


class PexelsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = "https://api.pexels.com/v1"

    @property
    def available(self) -> bool:
        return bool(self.settings.pexels_api_key)

    def search_videos(
        self,
        query: str,
        *,
        per_page: int = 12,
        page: int = 1,
        orientation: str | None = None,
        size: str | None = None,
        locale: str | None = None,
    ) -> dict[str, Any]:
        if not self.available:
            raise PexelsProviderError("PEXELS_API_KEY is not configured.")
        params = {
            "query": query,
            "per_page": max(1, min(80, per_page)),
            "page": max(1, page),
            "orientation": orientation or self.settings.pexels_orientation,
            "size": size or self.settings.pexels_size,
            "locale": locale or self.settings.pexels_locale,
        }
        response = requests.get(
            f"{self.base_url}/videos/search",
            headers={"Authorization": self.settings.pexels_api_key},
            params=params,
            timeout=20,
        )
        if response.status_code >= 400:
            raise PexelsProviderError(_provider_error(response), status_code=response.status_code)
        return response.json()

    def collect_ranked_videos(
        self,
        queries: list[str],
        *,
        per_query: int = 12,
        max_items: int = 6,
        page_offset: int = 0,
        page_span: int = 3,
    ) -> tuple[list[PexelsVideoCandidate], list[dict[str, Any]]]:
        seen: set[int] = set()
        candidates: list[PexelsVideoCandidate] = []
        search_reports: list[dict[str, Any]] = []
        page_span = max(1, int(page_span))
        for query_index, query in enumerate(queries):
            page = 1 + ((max(0, page_offset) + query_index) % page_span)
            try:
                data = self.search_videos(query, per_page=per_query, page=page)
            except Exception as exc:
                search_reports.append(
                    {
                        "query": query,
                        "total_results": None,
                        "returned": 0,
                        "page": page,
                        "per_page": per_query,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            videos = data.get("videos", [])
            search_reports.append(
                {
                    "query": query,
                    "total_results": data.get("total_results"),
                    "returned": len(videos),
                    "page": data.get("page"),
                    "per_page": data.get("per_page"),
                }
            )
            for rank, raw in enumerate(videos):
                video_id = int(raw.get("id", 0) or 0)
                if not video_id or video_id in seen:
                    continue
                download = _best_video_file(raw.get("video_files", []))
                if not download:
                    continue
                seen.add(video_id)
                candidates.append(_candidate_from_raw(raw, query, query_index, rank, download))
        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[:max_items], search_reports

    def download_video(self, candidate: PexelsVideoCandidate, output_dir: Path) -> Path:
        ensure_dir(output_dir)
        path = output_dir / f"pexels_{candidate.id}_{_safe_name(candidate.query)}.mp4"
        if path.exists() and path.stat().st_size > 0:
            candidate.local_path = path
            return path
        response = requests.get(candidate.download_url, timeout=300)
        if response.status_code >= 400:
            raise PexelsProviderError(_provider_error(response), status_code=response.status_code)
        path.write_bytes(response.content)
        candidate.local_path = path
        return path


def _candidate_from_raw(
    raw: dict[str, Any],
    query: str,
    query_index: int,
    rank: int,
    download: dict[str, Any],
) -> PexelsVideoCandidate:
    width = int(raw.get("width", 0) or 0)
    height = int(raw.get("height", 0) or 0)
    duration = int(raw.get("duration", 0) or 0)
    portrait_bonus = 3.0 if height > width else 0.0
    duration_bonus = 2.0 if 5 <= duration <= 20 else 0.8 if duration <= 35 else -1.0
    quality_bonus = _quality_score(download)
    early_query_bonus = max(0.0, 2.4 - query_index * 0.22)
    rank_bonus = max(0.0, 1.2 - rank * 0.08)
    score = portrait_bonus + duration_bonus + quality_bonus + early_query_bonus + rank_bonus
    user = raw.get("user") or {}
    return PexelsVideoCandidate(
        id=int(raw.get("id", 0) or 0),
        url=str(raw.get("url", "")),
        image=str(raw.get("image", "")),
        duration=duration,
        width=width,
        height=height,
        user_name=str(user.get("name", "")),
        user_url=str(user.get("url", "")),
        query=query,
        score=score,
        download_url=str(download.get("link", "")),
        download_quality=str(download.get("quality", "")),
        download_width=int(download.get("width", 0) or 0),
        download_height=int(download.get("height", 0) or 0),
    )


def _best_video_file(files: list[dict[str, Any]]) -> dict[str, Any] | None:
    mp4s = [
        item
        for item in files
        if str(item.get("file_type", "")).lower() == "video/mp4"
        and item.get("link")
        and int(item.get("width", 0) or 0) >= 540
        and int(item.get("height", 0) or 0) >= 960
    ]
    if not mp4s:
        mp4s = [item for item in files if str(item.get("file_type", "")).lower() == "video/mp4" and item.get("link")]
    if not mp4s:
        return None
    return max(mp4s, key=_quality_score)


def _quality_score(item: dict[str, Any]) -> float:
    width = int(item.get("width", 0) or 0)
    height = int(item.get("height", 0) or 0)
    pixels = width * height
    quality = str(item.get("quality", "")).lower()
    score = min(3.0, pixels / (1080 * 1920) * 2.2)
    if quality in {"uhd", "hd"}:
        score += 0.6
    return score


def _safe_name(value: str) -> str:
    import re

    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value[:36] or "clip"


def _provider_error(response: requests.Response) -> str:
    text = response.text[:700] if response.text else response.reason
    return f"Pexels provider returned {response.status_code}: {text}"
