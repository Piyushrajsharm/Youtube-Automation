from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .growth import finalize_metadata
from .llm import NvidiaChatClient
from .models import ComplianceReport, TrendItem, UploadMetadata, VideoPlan
from .policy import evaluate_plan
from .renderer import render_video
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
        rendered = render_video(plan, output_dir, settings)
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


def upload_existing_package(
    settings: Settings,
    video_path: Path,
    metadata_path: Path,
) -> dict[str, Any]:
    metadata = UploadMetadata.from_dict(read_json(metadata_path))
    settings.youtube_upload_enabled = True
    return upload_video(video_path, metadata, settings)
