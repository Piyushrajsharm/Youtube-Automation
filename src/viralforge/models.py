from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TrendItem:
    title: str
    url: str
    source: str
    published_at: str | None = None
    summary: str = ""
    score: float = 0.0
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchSource:
    title: str
    url: str
    source: str
    excerpt: str
    published_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchBundle:
    topic: str
    angle: str
    sources: list[ResearchSource]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "angle": self.angle,
            "sources": [source.to_dict() for source in self.sources],
            "notes": self.notes,
        }


@dataclass
class Scene:
    narration: str
    onscreen_text: str
    visual_style: str
    duration_seconds: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scene":
        return cls(
            narration=str(data.get("narration", "")).strip(),
            onscreen_text=str(data.get("onscreen_text", "")).strip(),
            visual_style=str(data.get("visual_style", "kinetic infographic")).strip(),
            duration_seconds=float(data.get("duration_seconds", 6.0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnimationEvent:
    time: float
    effect: str
    target: str = "scene"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScenePlan:
    scene_id: str
    start_time: float
    end_time: float
    purpose: str
    narration: str
    headline_text: str
    visual_description: str
    camera_motion: str
    animation_events: list[AnimationEvent] = field(default_factory=list)
    caption_words: list[str] = field(default_factory=list)
    voice_direction: str = "confident"
    sfx: list[str] = field(default_factory=list)
    music_intensity: float = 0.5
    transition: str = "whoosh"
    shot_types: list[str] = field(default_factory=list)
    emotion: str = "confident tension"
    location: str = "dark futuristic command room"
    foreground_elements: list[str] = field(default_factory=list)
    midground: str = "human presenter explaining beside holographic systems"
    background: str = "deep server architecture with moving light beams"
    atmosphere: str = "volumetric fog, floating dust, premium sci-fi depth"
    lighting: dict[str, str] = field(default_factory=dict)
    visual_metaphor: dict[str, Any] = field(default_factory=dict)
    character: dict[str, Any] = field(default_factory=dict)
    vfx: list[str] = field(default_factory=list)
    retention_events: list[dict[str, Any]] = field(default_factory=list)
    cinematic_prompt: str = ""
    scene_type: str = ""
    selected_skills: list[str] = field(default_factory=list)
    skill_profile: dict[str, Any] = field(default_factory=dict)
    shot_sequence: list[dict[str, Any]] = field(default_factory=list)
    broll_clips: list[dict[str, Any]] = field(default_factory=list)
    layers: list[dict[str, Any]] = field(default_factory=list)
    caption_plan: dict[str, Any] = field(default_factory=dict)
    camera_emotion: str = ""
    character_integration: dict[str, Any] = field(default_factory=dict)
    scene_quality_score: float = 0.0

    @property
    def duration_seconds(self) -> float:
        return max(0.01, self.end_time - self.start_time)

    @property
    def onscreen_text(self) -> str:
        return self.headline_text

    @property
    def visual_style(self) -> str:
        return self.visual_description

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_id": self.scene_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "purpose": self.purpose,
            "narration": self.narration,
            "headline_text": self.headline_text,
            "visual_description": self.visual_description,
            "camera_motion": self.camera_motion,
            "animation_events": [event.to_dict() for event in self.animation_events],
            "caption_words": self.caption_words,
            "voice_direction": self.voice_direction,
            "sfx": self.sfx,
            "music_intensity": self.music_intensity,
            "transition": self.transition,
            "shot_types": self.shot_types,
            "emotion": self.emotion,
            "location": self.location,
            "foreground_elements": self.foreground_elements,
            "midground": self.midground,
            "background": self.background,
            "atmosphere": self.atmosphere,
            "lighting": self.lighting,
            "visual_metaphor": self.visual_metaphor,
            "character": self.character,
            "vfx": self.vfx,
            "retention_events": self.retention_events,
            "cinematic_prompt": self.cinematic_prompt,
            "scene_type": self.scene_type,
            "selected_skills": self.selected_skills,
            "skill_profile": self.skill_profile,
            "shot_sequence": self.shot_sequence,
            "broll_clips": self.broll_clips,
            "layers": self.layers,
            "caption_plan": self.caption_plan,
            "camera_emotion": self.camera_emotion,
            "character_integration": self.character_integration,
            "scene_quality_score": self.scene_quality_score,
        }


@dataclass
class RetentionReport:
    passed: bool
    flags: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UploadMetadata:
    title: str
    description: str
    hashtags: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    category_id: str = "28"
    privacy_status: str = "private"
    contains_synthetic_media: bool = False
    made_for_kids: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UploadMetadata":
        return cls(
            title=str(data.get("title", "")).strip(),
            description=str(data.get("description", "")).strip(),
            hashtags=[str(item).strip() for item in data.get("hashtags", []) if str(item).strip()],
            tags=[str(item).strip() for item in data.get("tags", []) if str(item).strip()],
            category_id=str(data.get("category_id", "28")),
            privacy_status=str(data.get("privacy_status", "private")),
            contains_synthetic_media=bool(data.get("contains_synthetic_media", False)),
            made_for_kids=bool(data.get("made_for_kids", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VideoPlan:
    topic: str
    angle: str
    audience: str
    title: str
    scenes: list[Scene]
    metadata: UploadMetadata
    candidate_titles: list[str] = field(default_factory=list)
    copyright_notes: list[str] = field(default_factory=list)
    disclosure_notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VideoPlan":
        scenes = [Scene.from_dict(item) for item in data.get("scenes", [])]
        metadata = UploadMetadata.from_dict(data.get("metadata", {}))
        return cls(
            topic=str(data.get("topic", "")).strip(),
            angle=str(data.get("angle", "")).strip(),
            audience=str(data.get("audience", "curious viewers")).strip(),
            title=str(data.get("title", metadata.title)).strip(),
            scenes=scenes,
            metadata=metadata,
            candidate_titles=[str(item).strip() for item in data.get("candidate_titles", [])],
            copyright_notes=[str(item).strip() for item in data.get("copyright_notes", [])],
            disclosure_notes=[str(item).strip() for item in data.get("disclosure_notes", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "angle": self.angle,
            "audience": self.audience,
            "title": self.title,
            "scenes": [scene.to_dict() for scene in self.scenes],
            "metadata": self.metadata.to_dict(),
            "candidate_titles": self.candidate_titles,
            "copyright_notes": self.copyright_notes,
            "disclosure_notes": self.disclosure_notes,
        }


@dataclass
class ComplianceReport:
    passed: bool
    risk_score: float
    flags: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
