from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .growth import finalize_metadata
from .llm import NvidiaChatClient
from .models import ComplianceReport, TrendItem, UploadMetadata, VideoPlan
from .pexels_demo_renderer import render_pexels_demo
from .policy import evaluate_plan
from .renderer import finalize_raw_render, render_video
from .research import build_research_bundle
from .scriptwriter import create_video_plan
from .trends import collect_news_for_query, collect_trends
from .utils import ensure_dir, jaccard, read_json, slugify, utc_now_slug, write_json
from .youtube import upload_video


AUTOMATION_STATE_FILE = "automation_state.json"
TOPIC_REPEAT_THRESHOLD = 0.72


@dataclass
class AutomationPackage:
    output_dir: Path
    topic: str
    plan: VideoPlan
    compliance: ComplianceReport
    rendered: dict[str, Path | None]
    upload_result: dict[str, Any] | None
    trends: list[TrendItem]

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "topic": self.topic,
            "plan": self.plan.to_dict(),
            "compliance": self.compliance.to_dict(),
            "rendered": {key: str(value) if value else None for key, value in self.rendered.items()},
            "upload_result": self.upload_result,
            "trends": [trend.to_dict() for trend in self.trends],
        }


def run_once(
    settings: Settings,
    strategy: dict[str, Any],
    *,
    topic: str = "",
    trend_limit: int = 20,
    render: bool = True,
    upload: bool = False,
    force_upload: bool = False,
) -> AutomationPackage:
    topic = topic.strip()
    if topic:
        trends = collect_news_for_query(settings, topic, limit=6)
        related = trends
    else:
        trends = collect_trends(settings, strategy, limit=trend_limit)
        topic = choose_fresh_topic(trends, _load_state(settings))
        related = _related_items(topic, trends)

    if not topic:
        topic = "AI tools changing how people work"
    if not related:
        related = [_manual_topic(topic)]

    output_dir = settings.outputs_dir / f"{utc_now_slug()}_{slugify(topic)}"
    ensure_dir(output_dir)

    bundle = build_research_bundle(topic, related)
    llm = NvidiaChatClient(settings)
    plan = create_video_plan(settings, llm, bundle, strategy)
    plan.metadata = finalize_metadata(plan, bundle, settings, strategy)
    compliance = evaluate_plan(plan, bundle, strategy)

    write_json(output_dir / "trends.json", [trend.to_dict() for trend in trends])
    write_json(output_dir / "research.json", bundle.to_dict())
    write_json(output_dir / "plan.json", plan.to_dict())
    write_json(output_dir / "metadata.json", plan.metadata.to_dict())
    write_json(output_dir / "compliance.json", compliance.to_dict())

    rendered: dict[str, Path | None] = {"video": None, "thumbnail": None, "audio": None}
    if render:
        rendered = _render_for_automation(plan, output_dir, settings)
        write_json(output_dir / "rendered.json", rendered)

    upload_result: dict[str, Any] | None = None
    if upload:
        video_path = rendered.get("video")
        if not video_path:
            raise RuntimeError("Cannot upload because rendering is disabled or no video was produced.")
        if not compliance.passed and not force_upload:
            raise RuntimeError("Compliance audit has flags. Review compliance.json or pass --force-upload intentionally.")
        settings.youtube_upload_enabled = True
        upload_result = upload_video(Path(str(video_path)), plan.metadata, settings)
        write_json(output_dir / "upload.json", upload_result)

    package = AutomationPackage(
        output_dir=output_dir,
        topic=topic,
        plan=plan,
        compliance=compliance,
        rendered=rendered,
        upload_result=upload_result,
        trends=trends,
    )
    _remember_package(settings, package)
    write_json(output_dir / "automation_package.json", package.to_dict())
    return package


def _render_for_automation(plan: VideoPlan, output_dir: Path, settings: Settings) -> dict[str, Path | None]:
    if bool(getattr(settings, "pexels_enabled", False) and getattr(settings, "pexels_video_enabled", False)):
        if not getattr(settings, "pexels_api_key", ""):
            raise RuntimeError("PEXELS_ENABLED is true, but PEXELS_API_KEY is not configured.")
        try:
            rendered = render_pexels_demo(plan, output_dir, settings)
            return {key: Path(str(value)) if value else None for key, value in rendered.items()}
        except Exception as exc:
            write_json(output_dir / "pexels_render_error.json", {"error": f"{type(exc).__name__}: {exc}"})
            raise RuntimeError("Pexels render failed; refusing to upload a non-Pexels fallback video.") from exc
    return render_video(plan, output_dir, settings)


def choose_fresh_topic(trends: list[TrendItem], state: dict[str, Any]) -> str:
    if not trends:
        return ""
    seen = [str(item.get("topic", "")) for item in state.get("history", []) if item.get("topic")]
    for trend in trends:
        if not any(jaccard(trend.title, prior) >= TOPIC_REPEAT_THRESHOLD for prior in seen):
            return trend.title
    return trends[0].title


def _related_items(topic: str, trends: list[TrendItem]) -> list[TrendItem]:
    if not trends:
        return []
    ranked = sorted(trends, key=lambda item: jaccard(topic, item.title) + item.score / 20, reverse=True)
    selected = [item for item in ranked if jaccard(topic, item.title) > 0.08]
    if not selected and ranked:
        selected = ranked[:4]
    return selected[:6]


def _manual_topic(topic: str) -> TrendItem:
    return TrendItem(
        title=topic,
        url=f"https://news.google.com/search?q={slugify(topic).replace('-', '+')}",
        source="manual_topic",
        summary="Manual topic supplied by the creator.",
    )


def _load_state(settings: Settings) -> dict[str, Any]:
    path = settings.outputs_dir / AUTOMATION_STATE_FILE
    if not path.exists():
        return {"history": []}
    try:
        data = read_json(path)
    except Exception:
        return {"history": []}
    history = data.get("history")
    if not isinstance(history, list):
        data["history"] = []
    return data


def _remember_package(settings: Settings, package: AutomationPackage) -> None:
    ensure_dir(settings.outputs_dir)
    state = _load_state(settings)
    history = state.setdefault("history", [])
    if not isinstance(history, list):
        history = []
        state["history"] = history
    history.insert(
        0,
        {
            "created_at": utc_now_slug(),
            "topic": package.topic,
            "output_dir": str(package.output_dir),
            "video": str(package.rendered.get("video")) if package.rendered.get("video") else None,
            "uploaded": bool(package.upload_result),
            "youtube_url": package.upload_result.get("url") if package.upload_result else None,
            "hashtags": package.plan.metadata.hashtags,
        },
    )
    state["history"] = history[:100]
    write_json(settings.outputs_dir / AUTOMATION_STATE_FILE, state)


def _remember_recovered_render(settings: Settings, output_dir: Path, video_path: Path, metadata_path: Path) -> None:
    ensure_dir(settings.outputs_dir)
    state = _load_state(settings)
    history = state.setdefault("history", [])
    if not isinstance(history, list):
        history = []
        state["history"] = history

    try:
        metadata = UploadMetadata.from_dict(read_json(metadata_path))
    except Exception:
        metadata = UploadMetadata(title=output_dir.name, description="", hashtags=[], tags=[])

    topic = metadata.title
    plan_path = output_dir / "plan.json"
    if plan_path.exists():
        try:
            topic = str(read_json(plan_path).get("topic") or topic)
        except Exception:
            pass

    entry = {
        "created_at": output_dir.name[:15],
        "topic": topic,
        "output_dir": str(output_dir),
        "video": str(video_path),
        "uploaded": False,
        "youtube_url": None,
        "hashtags": metadata.hashtags,
    }
    for item in history:
        if str(item.get("output_dir") or "") == str(output_dir):
            if item.get("uploaded"):
                entry["uploaded"] = True
                entry["youtube_url"] = item.get("youtube_url")
            item.update(entry)
            break
    else:
        history.insert(0, entry)

    history.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    state["history"] = history[:100]
    write_json(settings.outputs_dir / AUTOMATION_STATE_FILE, state)


def upload_existing_package(
    settings: Settings,
    video_path: Path,
    metadata_path: Path,
) -> dict[str, Any]:
    metadata = UploadMetadata.from_dict(read_json(metadata_path))
    settings.youtube_upload_enabled = True
    return upload_video(video_path, metadata, settings)


def recover_incomplete_render_packages(settings: Settings) -> list[dict[str, str]]:
    """Repair output folders where rendering produced raw MP4 output but packaging was interrupted."""
    if not settings.outputs_dir.exists():
        return []

    recovered: list[dict[str, str]] = []
    output_dirs = [path for path in settings.outputs_dir.iterdir() if path.is_dir()]
    for output_dir in sorted(output_dirs, key=lambda path: path.stat().st_mtime, reverse=True):
        metadata_path = output_dir / "metadata.json"
        if not metadata_path.exists():
            continue

        had_video = (output_dir / "video.mp4").exists()
        had_rendered_json = (output_dir / "rendered.json").exists()
        video_path = finalize_raw_render(output_dir, settings)
        if not video_path:
            continue

        rendered_path = output_dir / "rendered.json"
        if not rendered_path.exists():
            thumbnail_path = output_dir / "thumbnail.jpg"
            contact_sheet_path = output_dir / "contact_sheet.jpg"
            audio_path = output_dir / "narration_timed.wav"
            music_path = output_dir / "original_music.wav"
            sfx_path = output_dir / "sound_design.wav"
            write_json(
                rendered_path,
                {
                    "video": video_path,
                    "thumbnail": thumbnail_path if thumbnail_path.exists() else None,
                    "contact_sheet": contact_sheet_path if contact_sheet_path.exists() else None,
                    "audio": audio_path if audio_path.exists() else None,
                    "music": music_path if music_path.exists() else None,
                    "sfx": sfx_path if sfx_path.exists() else None,
                },
            )

        _remember_recovered_render(settings, output_dir, video_path, metadata_path)
        if not had_video or not had_rendered_json:
            recovered.append({"output_dir": str(output_dir), "video": str(video_path), "metadata": str(metadata_path)})
    return recovered
