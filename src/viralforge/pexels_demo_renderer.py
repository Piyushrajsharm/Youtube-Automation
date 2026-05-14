from __future__ import annotations

import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

from .cinematic_score import cinematic_score
from .config import Settings
from .models import Scene, ScenePlan, UploadMetadata, VideoPlan
from .pexels_broll_adapter import DEFAULT_PEXELS_QUERIES, prepare_pexels_broll
from .quality_checker import check_skill_quality
from .renderer import synthesize_music, synthesize_voice
from .scene_planner import create_scene_plan
from .scene_quality_checker import check_scene_quality
from .sfx_engine import synthesize_sfx
from .subtitle_engine import keyword_chips
from .retention_checker import check_retention
from .utils import ensure_dir, write_json


def render_pexels_demo(plan: VideoPlan, output_dir: Path, settings: Settings) -> dict[str, str]:
    ensure_dir(output_dir)
    segments_dir = ensure_dir(output_dir / "segments")
    scene_plans = create_scene_plan(plan, settings.video_duration_seconds)
    selected = prepare_pexels_broll(
        output_dir,
        settings,
        queries=_queries_for_plan(plan),
        max_clips=max(settings.pexels_max_clips, min(len(scene_plans), 6)),
    )
    if len(selected) < 2:
        raise RuntimeError("Pexels did not return enough usable portrait clips for the demo render.")

    write_json(output_dir / "plan.json", plan.to_dict())
    write_json(output_dir / "scene_plan.json", [scene.to_dict() for scene in scene_plans])
    write_json(output_dir / "retention.json", check_retention(scene_plans).to_dict())
    write_json(output_dir / "scene_quality.json", check_scene_quality(scene_plans))
    write_json(output_dir / "cinematic_score.json", cinematic_score(scene_plans))
    write_json(output_dir / "skill_quality.json", check_skill_quality(scene_plans))

    voice_path = synthesize_voice(plan, output_dir, settings, scene_plans)
    music_path = synthesize_music(plan, output_dir, settings.video_duration_seconds, settings) if settings.music_enabled else None
    sfx_path = (
        synthesize_sfx(scene_plans, output_dir, settings.video_duration_seconds, settings.audio_sample_rate)
        if settings.sfx_enabled
        else None
    )

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    segment_paths: list[Path] = []
    for index, scene in enumerate(scene_plans):
        clip_path = Path(str(selected[index % len(selected)].local_path))
        segment_path = segments_dir / f"segment_{index:02d}.mp4"
        _render_segment(ffmpeg, clip_path, scene.duration_seconds, segment_path, settings)
        segment_paths.append(segment_path)

    concat_path = output_dir / "concat.txt"
    concat_path.write_text("".join(f"file '{path.resolve().as_posix()}'\n" for path in segment_paths), encoding="utf-8")
    base_path = output_dir / "pexels_base.mp4"
    subprocess.run(
        [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-c", "copy", str(base_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    ass_path = output_dir / "captions.ass"
    ass_path.write_text(_ass_script(scene_plans), encoding="utf-8")
    video_path = output_dir / "video.mp4"
    _render_final_video(ffmpeg, base_path, ass_path, video_path, voice_path, music_path, sfx_path, settings)

    thumbnail_path = output_dir / "thumbnail.jpg"
    subprocess.run(
        [ffmpeg, "-y", "-ss", "0.8", "-i", str(video_path), "-frames:v", "1", str(thumbnail_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    contact_sheet_path = output_dir / "contact_sheet.jpg"
    subprocess.run(
        [ffmpeg, "-y", "-i", str(video_path), "-vf", "fps=1/5,scale=270:480,tile=7x1", "-frames:v", "1", str(contact_sheet_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    rendered = {
        "video": str(video_path),
        "thumbnail": str(thumbnail_path),
        "contact_sheet": str(contact_sheet_path),
        "audio": str(voice_path) if voice_path else "",
        "music": str(music_path) if music_path else "",
        "sfx": str(sfx_path) if sfx_path else "",
    }
    write_json(output_dir / "rendered.json", rendered)
    return rendered


def _render_segment(ffmpeg: str, clip_path: Path, duration_seconds: float, segment_path: Path, settings: Settings) -> None:
    width = int(settings.video_width)
    height = int(settings.video_height)
    fps = int(settings.video_fps)
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps={fps},"
        "eq=contrast=1.08:saturation=1.08:brightness=-0.035,"
        "vignette=PI/5:0.45,format=yuv420p"
    )
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(clip_path),
            "-t",
            f"{duration_seconds:.2f}",
            "-vf",
            video_filter,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-b:v",
            settings.video_bitrate,
            str(segment_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _render_final_video(
    ffmpeg: str,
    base_path: Path,
    ass_path: Path,
    video_path: Path,
    voice_path: Path | None,
    music_path: Path | None,
    sfx_path: Path | None,
    settings: Settings,
) -> None:
    ass_filter_path = ass_path.resolve().as_posix().replace(":", r"\:")
    inputs = ["-i", str(base_path)]
    filter_parts = [f"[0:v]ass='{ass_filter_path}',format=yuv420p[v]"]
    map_args = ["-map", "[v]"]
    audio_labels: list[str] = []
    input_index = 1
    for path, volume in ((voice_path, 1.08), (music_path, settings.music_volume), (sfx_path, 0.86)):
        if path and path.exists() and path.stat().st_size > 0:
            inputs += ["-i", str(path)]
            label = f"a{input_index}"
            filter_parts.append(f"[{input_index}:a]volume={volume}[{label}]")
            audio_labels.append(f"[{label}]")
            input_index += 1
    if audio_labels:
        filter_parts.append(
            "".join(audio_labels)
            + f"amix=inputs={len(audio_labels)}:duration=longest:dropout_transition=0,loudnorm=I={settings.audio_target_lufs}:TP=-1.5:LRA=9[a]"
        )
        map_args += ["-map", "[a]"]
    subprocess.run(
        [
            ffmpeg,
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(filter_parts),
            *map_args,
            "-t",
            str(settings.video_duration_seconds),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-b:v",
            settings.video_bitrate,
            "-c:a",
            "aac",
            "-ar",
            str(settings.audio_sample_rate),
            "-movflags",
            "+faststart",
            str(video_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _ass_script(scene_plans: list[ScenePlan]) -> str:
    script = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Headline, Segoe UI Black, 92, &H00FFFFFF, &H0036D6FF, &HCC000000, &H99000000, -1, 0, 0, 0, 100, 100, 0, 0, 1, 6, 3, 5, 50, 50, 0, 1
Style: Kinetic, Segoe UI Black, 68, &H00FFFFFF, &H0036D6FF, &HCC000000, &H99000000, -1, 0, 0, 0, 100, 100, 0, 0, 1, 6, 3, 5, 60, 60, 0, 1
Style: Subscribe, Segoe UI Semibold, 32, &H00FFFFFF, &H0036D6FF, &HAA000000, &H88000000, -1, 0, 0, 0, 100, 100, 1, 0, 1, 3, 1, 3, 50, 54, 78, 1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    for scene in scene_plans:
        headline = _ass_escape(scene.headline_text.upper().replace(" ", "\\N", 1))
        headline_end = min(scene.end_time - 0.2, scene.start_time + 1.35)
        script += f"Dialogue: 1,{_ass_time(scene.start_time + 0.05)},{_ass_time(headline_end)},Headline,,0,0,0,,{{\\fad(90,130)\\t(0,180,\\fscx108\\fscy108)\\pos(540,640)}}{headline}\n"
        for index, (start, end, phrase) in enumerate(_caption_timing(scene)):
            y0 = 1225 if index % 2 == 0 else 1168
            y1 = y0 - 38
            script += (
                f"Dialogue: 2,{_ass_time(start)},{_ass_time(end)},Kinetic,,0,0,0,,"
                f"{{\\fad(55,85)\\t(0,150,\\fscx112\\fscy112)\\move(540,{y0},540,{y1})}}{_ass_escape(phrase)}\n"
            )
    if scene_plans:
        script += (
            f"Dialogue: 3,{_ass_time(2.0)},{_ass_time(scene_plans[-1].end_time)},Subscribe,,0,0,0,,"
            "{\\fad(300,250)\\pos(902,1810)}SUBSCRIBE FOR TECH\n"
        )
    return script


def _caption_timing(scene: ScenePlan) -> list[tuple[float, float, str]]:
    groups = _caption_groups(scene.narration)
    if not groups:
        return []
    start = scene.start_time + 1.05
    end = max(start + 0.7, scene.end_time - 0.35)
    step = max(0.42, (end - start) / len(groups))
    timings: list[tuple[float, float, str]] = []
    for index, group in enumerate(groups):
        group_start = start + index * step
        group_end = min(end, group_start + max(0.38, step * 0.86))
        if group_end - group_start < 0.2:
            continue
        timings.append((group_start, group_end, group))
    return timings


def _caption_groups(text: str) -> list[str]:
    groups: list[str] = []
    clauses = [part.strip() for part in re.split(r"(?<=[.!?])\s+|,\s+", text) if part.strip()]
    for clause in clauses:
        words = [word.upper() for word in re.findall(r"[A-Za-z0-9']+", clause)]
        cursor = 0
        while cursor < len(words):
            remaining = len(words) - cursor
            if remaining <= 5:
                take = remaining
            elif remaining == 6:
                take = 4 if words[cursor + 2] in {"NOT", "NO", "WITHOUT"} else 3
            else:
                take = 4
            group_words = words[cursor : cursor + take]
            if len(group_words) == 1 and groups:
                groups[-1] = f"{groups[-1]} {group_words[0]}"
            elif group_words:
                groups.append(" ".join(group_words))
            cursor += take
    return groups[:7]


def _queries_for_plan(plan: VideoPlan) -> list[str]:
    text = " ".join(
        [
            plan.topic,
            plan.angle,
            plan.title,
            " ".join(scene.narration for scene in plan.scenes),
            " ".join(str(getattr(scene, "visual", getattr(scene, "visual_style", ""))) for scene in plan.scenes),
        ]
    ).lower()
    queries: list[str] = []
    if any(token in text for token in ["creator", "influencer", "youtube", "shorts", "social", "content"]):
        queries.extend(
            [
                "content creator workspace",
                "video editor computer",
                "social media creator filming",
                "podcast studio technology",
                "creator desk setup",
            ]
        )
    if any(token in text for token in ["science", "research", "lab", "biology", "space", "quantum"]):
        queries.extend(
            [
                "science laboratory technology",
                "researcher computer lab",
                "space technology control room",
                "engineer technology screen",
            ]
        )
    if any(token in text for token in ["cyber", "security", "privacy", "hack", "access", "permission", "vault"]):
        queries.extend(
            [
                "cyber security server room",
                "security operations center",
                "digital lock technology",
                "data center warning lights",
            ]
        )
    if any(token in text for token in ["gadget", "phone", "laptop", "device", "hardware", "chip"]):
        queries.extend(
            [
                "new technology gadgets",
                "smartphone hands close up",
                "electronics desk setup",
                "computer chip technology",
            ]
        )
    if any(token in text for token in ["ai", "agent", "automation", "robot", "machine learning", "software"]):
        queries.extend(
            [
                "artificial intelligence technology",
                "software developer coding",
                "automation technology office",
                "data visualization computer",
                "futuristic technology interface",
            ]
        )
    queries.extend(DEFAULT_PEXELS_QUERIES)
    return _dedupe_queries(queries)


def _dedupe_queries(queries: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for query in queries:
        cleaned = re.sub(r"\s+", " ", query).strip()
        key = cleaned.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if len(result) >= 16:
            break
    return result or DEFAULT_PEXELS_QUERIES[:16]


def _ass_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def _ass_escape(value: str) -> str:
    return value.replace("{", r"\{").replace("}", r"\}")


def default_pexels_demo_plan() -> VideoPlan:
    return VideoPlan(
        topic="AI agents as the new interns",
        angle="Founders can move faster with AI agents only if access is controlled.",
        audience="founders, creators, students, AI builders",
        title="Your next intern is not human",
        scenes=[
            Scene("Your next intern will not sleep. It will not ask for breaks. It will ask for access.", "Your next intern is not human", "premium technology office b-roll, cold open, employee badge metaphor", 5.3),
            Scene("That sounds powerful, until one agent touches the wrong account or sends the wrong file.", "Access is the danger", "cybersecurity warning, permissions, vault and key metaphor", 5.5),
            Scene("The boring tasks are already moving. Research, reports, emails, dashboards, all at once.", "Boring work is next", "startup office and laptop workflow montage", 5.6),
            Scene("But speed without review becomes expensive chaos. The real product is control.", "Speed needs control", "team review, audit trail, approval gate, dashboard", 5.9),
            Scene("Give AI narrow tasks, visible logs, and one human who holds the keys.", "Human keeps the keys", "manager approval, secure workflow, digital key metaphor", 5.8),
            Scene("So would you hire an AI worker if you controlled exactly what it could touch?", "Would you hire one?", "final hero tech office shot, CTA, clean futuristic hold", 5.9),
        ],
        metadata=UploadMetadata(
            title="Your next intern is not human",
            description="Original stock-footage cinematic AI explainer using Pexels clips, original narration, music, and SFX.",
            hashtags=["#AI", "#AIAgents", "#Automation", "#FutureOfWork", "#TechShorts"],
            tags=["AI agents", "automation", "future of work", "AI interns", "business automation"],
            contains_synthetic_media=True,
        ),
        copyright_notes=["Pexels footage transformed with original edit, narration, captions, music, and SFX."],
        disclosure_notes=["Synthetic narration and edited stock-footage explainer."],
    )
