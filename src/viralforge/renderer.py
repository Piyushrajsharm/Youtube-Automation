from __future__ import annotations

import asyncio
import shutil
import subprocess
import math
import re
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .config import Settings
from .cinematic_score import cinematic_score
from .google_video_adapter import generate_google_videos
from .models import Scene, ScenePlan, VideoPlan
from .motion_engine import camera_state, current_shot, current_shot_entry, event_intensity, should_flash
from .nvidia_audio_adapter import synthesize_nvidia_audio
from .quality_checker import check_skill_quality
from .retention_checker import check_retention
from .scene_quality_checker import check_scene_quality
from .scene_planner import create_scene_plan
from .nvidia_video_adapter import generate_nvidia_videos
from .seedance2_adapter import seedance2_manifest
from .sfx_engine import synthesize_sfx
from .subtitle_engine import caption_for_time, keyword_chips
from .utils import clean_text, ensure_dir, write_json
from .voice_director import directed_script, voice_params

# Advanced cinematic rendering engines
from .cinematic_lighting import render_volumetric_fog, render_god_rays, render_bloom, render_cinematic_lighting
from .particle_system import create_scene_particles
from .cinematic_postprocess import cinematic_post_process, apply_depth_of_field
from .advanced_background import create_advanced_background
from .cinematic_transitions import cinematic_transition


CINEMA_PALETTES = [
    ((4, 8, 16), (0, 245, 212), (255, 214, 102), (255, 54, 121)),
    ((7, 9, 20), (94, 234, 212), (248, 250, 252), (251, 113, 133)),
    ((9, 12, 26), (125, 211, 252), (250, 204, 21), (244, 114, 182)),
    ((14, 12, 24), (52, 211, 153), (255, 237, 213), (249, 115, 22)),
    ((3, 7, 18), (34, 211, 238), (226, 232, 240), (168, 85, 247)),
]

_PARTICLE_SYSTEMS: dict[int, object] = {}

EDGE_TTS_TIMEOUT_SECONDS = 35
EDGE_TTS_ATTEMPTS = 2

_BROLL_RENDERERS = {
    "ai_office",
    "task_montage",
    "vault_access",
    "human_review",
    "chaos_dashboard",
    "server_room",
    "final_hero_system",
}


def render_video(plan: VideoPlan, output_dir: Path, settings: Settings) -> dict[str, Path | None]:
    ensure_dir(output_dir)
    video_path = output_dir / "video.mp4"
    raw_video_path = output_dir / "video_raw.mp4"
    thumbnail_path = output_dir / "thumbnail.jpg"

    from moviepy.audio.AudioClip import CompositeAudioClip
    from moviepy.audio.fx.all import audio_loop
    from moviepy.editor import AudioFileClip, VideoClip, VideoFileClip, concatenate_videoclips

    target_duration = float(settings.video_duration_seconds)
    scene_plans = create_scene_plan(plan, target_duration)
    retention = check_retention(scene_plans)
    scene_quality = check_scene_quality(scene_plans)
    score = cinematic_score(scene_plans)
    skill_quality = check_skill_quality(scene_plans)
    write_json(output_dir / "scene_plan.json", [scene.to_dict() for scene in scene_plans])
    write_json(output_dir / "retention.json", retention.to_dict())
    write_json(output_dir / "scene_quality.json", scene_quality)
    write_json(output_dir / "cinematic_score.json", score)
    write_json(output_dir / "skill_quality.json", skill_quality)
    seedance2_path = seedance2_manifest(scene_plans, output_dir, settings)
    google_videos: dict[str, Path] = {}
    nvidia_videos: dict[str, Path] = {}

    voice_path = synthesize_voice(plan, output_dir, settings, scene_plans)
    if voice_path and voice_path.exists() and voice_path.stat().st_size > 0:
        probe = AudioFileClip(str(voice_path))
        max_duration = 59.0 if settings.video_format == "shorts" else 74.0
        padding = 0.0 if voice_path.name == "narration_timed.wav" else 0.8
        target_duration = max(target_duration, min(max_duration, probe.duration + padding))
        probe.close()
        scene_plans = create_scene_plan(plan, target_duration)
        retention = check_retention(scene_plans)
        scene_quality = check_scene_quality(scene_plans)
        score = cinematic_score(scene_plans)
        skill_quality = check_skill_quality(scene_plans)
        write_json(output_dir / "scene_plan.json", [scene.to_dict() for scene in scene_plans])
        write_json(output_dir / "retention.json", retention.to_dict())
        write_json(output_dir / "scene_quality.json", scene_quality)
        write_json(output_dir / "cinematic_score.json", score)
        write_json(output_dir / "skill_quality.json", skill_quality)
    if not score["passed"]:
        flags = "; ".join(str(item) for item in score.get("flags", []))
        raise RuntimeError(f"Cinematic score gate failed: {score['score']}/100. {flags}")
    if not skill_quality["passed"]:
        flags = "; ".join(str(item) for item in skill_quality.get("flags", []))
        raise RuntimeError(f"Cinematic skill gate failed. {flags}")
    if not scene_quality["passed"]:
        flags = "; ".join(str(item) for item in scene_quality.get("flags", []))
        raise RuntimeError(f"Scene quality gate failed: {scene_quality['minimum_score']}/100. {flags}")

    seed_frame_builder = lambda scene, index: _frame_for_scene(
        scene,
        index,
        min(scene.duration_seconds * 0.42, max(0.35, scene.duration_seconds - 0.2)),
        settings.video_width,
        settings.video_height,
        settings.presenter_enabled,
        str(settings.presenter_asset),
        settings,
    )
    if settings.google_video_enabled:
        google_videos = generate_google_videos(
            scene_plans,
            output_dir,
            settings,
            seed_frame_builder=seed_frame_builder,
        )
    if settings.nvidia_video_enabled:
        nvidia_videos = generate_nvidia_videos(
            scene_plans,
            output_dir,
            settings,
            seed_frame_builder=seed_frame_builder,
        )

    clips = []
    opened_video_sources = []
    for index, scene in enumerate(scene_plans):
        external_path = google_videos.get(scene.scene_id) or nvidia_videos.get(scene.scene_id)
        if external_path and external_path.exists() and external_path.stat().st_size > 0:
            source = VideoFileClip(str(external_path)).without_audio()
            opened_video_sources.append(source)
            clips.append(_fit_external_video_clip(source, settings.video_width, settings.video_height, scene.duration_seconds))
            continue
        clips.append(
            VideoClip(
                make_frame=lambda t, scene=scene, index=index: _frame_for_scene(
                    scene,
                    index,
                    t,
                    settings.video_width,
                    settings.video_height,
                    settings.presenter_enabled,
                    str(settings.presenter_asset),
                    settings,
                ),
                duration=scene.duration_seconds,
            )
        )
    final = concatenate_videoclips(clips, method="compose")
    music_path = synthesize_music(plan, output_dir, max(final.duration, settings.video_duration_seconds), settings)
    sfx_path = (
        synthesize_sfx(scene_plans, output_dir, final.duration, settings.audio_sample_rate)
        if settings.sfx_enabled
        else None
    )

    audio_layers = []
    opened_audio = []
    if music_path and music_path.exists():
        music_source = AudioFileClip(str(music_path))
        opened_audio.append(music_source)
        music = audio_loop(music_source, duration=final.duration).volumex(settings.music_volume)
        opened_audio.append(music)
        audio_layers.append(music)
    if voice_path and voice_path.exists() and voice_path.stat().st_size > 0:
        voice_source = AudioFileClip(str(voice_path))
        opened_audio.append(voice_source)
        voice = voice_source.subclip(0, min(voice_source.duration, final.duration)).volumex(1.0)
        opened_audio.append(voice)
        audio_layers.append(voice)
    if sfx_path and sfx_path.exists():
        sfx_source = AudioFileClip(str(sfx_path)).volumex(0.85)
        opened_audio.append(sfx_source)
        sfx_clip = sfx_source.subclip(0, min(sfx_source.duration, final.duration))
        opened_audio.append(sfx_clip)
        audio_layers.append(sfx_clip)

    if audio_layers:
        final = final.set_audio(CompositeAudioClip(audio_layers))

    final.write_videofile(
        str(raw_video_path),
        fps=settings.video_fps,
        codec="libx264",
        audio_codec="aac",
        bitrate=settings.video_bitrate,
        audio_fps=settings.audio_sample_rate,
        preset="medium",
        threads=4,
        logger=None,
    )
    _normalize_video_loudness(raw_video_path, video_path, settings)
    _save_thumbnail(scene_plans[0], thumbnail_path, settings)

    for audio in opened_audio:
        audio.close()
    final.close()
    for clip in clips:
        clip.close()
    for source in opened_video_sources:
        source.close()

    return {
        "video": video_path,
        "thumbnail": thumbnail_path,
        "audio": voice_path,
        "music": music_path,
        "sfx": sfx_path,
        "nvidia_videos": nvidia_videos,
        "google_videos": google_videos,
        "seedance2": seedance2_path,
    }


def synthesize_voice(
    plan: VideoPlan,
    output_dir: Path,
    settings: Settings,
    scene_plans: list[ScenePlan] | None = None,
) -> Path | None:
    narration = directed_script(scene_plans) if scene_plans else " ".join(clean_text(scene.narration) for scene in plan.scenes)
    if not narration or settings.voice_engine == "off":
        return None
    if settings.nvidia_audio_enabled or settings.voice_engine == "nvidia":
        nvidia_voice_path = synthesize_nvidia_audio(narration, output_dir, settings)
        if nvidia_voice_path and nvidia_voice_path.exists():
            return nvidia_voice_path
        if settings.voice_engine == "nvidia":
            return None
    if settings.voice_engine == "edge":
        if scene_plans:
            timed_audio_path = output_dir / "narration_timed.wav"
            try:
                asyncio.run(_edge_tts_scene_timeline(scene_plans, output_dir, timed_audio_path, settings))
                return timed_audio_path if timed_audio_path.exists() else None
            except Exception:
                pass
        audio_path = output_dir / "narration.mp3"
        try:
            asyncio.run(_edge_tts_save(narration, audio_path, settings))
            return audio_path if audio_path.exists() else None
        except Exception:
            return _pyttsx3_voice(narration, output_dir)
    if settings.voice_engine == "pyttsx3":
        return _pyttsx3_voice(narration, output_dir)
    return None


async def _edge_tts_save(text: str, path: Path, settings: Settings) -> None:
    await _edge_tts_save_with_retry(
        text=text,
        path=path,
        settings=settings,
        rate=settings.voice_rate,
        pitch=settings.voice_pitch,
    )


async def _edge_tts_scene_timeline(
    scene_plans: list[ScenePlan],
    output_dir: Path,
    output_path: Path,
    settings: Settings,
) -> None:
    from moviepy.audio.AudioClip import CompositeAudioClip
    from moviepy.editor import AudioFileClip

    generated: list[tuple[ScenePlan, Path]] = []
    for scene in scene_plans:
        text = _voice_line_for_scene(scene)
        if not text:
            continue
        params = voice_params(scene)
        path = output_dir / f"narration_{scene.scene_id}.mp3"
        await _edge_tts_save_with_retry(
            text=text,
            path=path,
            settings=settings,
            rate=params.get("rate", settings.voice_rate),
            pitch=params.get("pitch", settings.voice_pitch),
        )
        if path.exists() and path.stat().st_size > 0:
            generated.append((scene, path))

    if not generated:
        raise RuntimeError("No scene voice clips were generated.")

    audio_clips = []
    opened = []
    total_duration = max(scene.end_time for scene in scene_plans)
    try:
        cursor = 0.04
        speech_gap = 0.08
        for scene, path in generated:
            source = AudioFileClip(str(path))
            opened.append(source)
            if cursor >= total_duration - 0.1:
                break
            available = max(0.1, total_duration - cursor)
            clip = source.subclip(0, min(source.duration, available))
            clip = clip.set_start(cursor).volumex(1.05)
            opened.append(clip)
            audio_clips.append(clip)
            cursor += min(source.duration, available) + speech_gap
        CompositeAudioClip(audio_clips).set_duration(total_duration).write_audiofile(
            str(output_path),
            fps=settings.audio_sample_rate,
            codec="pcm_s16le",
            logger=None,
        )
    finally:
        for clip in opened:
            clip.close()


async def _edge_tts_save_with_retry(
    text: str,
    path: Path,
    settings: Settings,
    rate: str,
    pitch: str,
) -> None:
    import edge_tts

    last_error: Exception | None = None
    for attempt in range(EDGE_TTS_ATTEMPTS):
        if path.exists():
            path.unlink()
        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=settings.voice_name,
                rate=rate,
                pitch=pitch,
            )
            await asyncio.wait_for(communicate.save(str(path)), timeout=EDGE_TTS_TIMEOUT_SECONDS)
            if path.exists() and path.stat().st_size > 0:
                return
            last_error = RuntimeError(f"Edge TTS created an empty file: {path.name}")
        except Exception as exc:
            last_error = exc
        if path.exists() and path.stat().st_size == 0:
            path.unlink()
        if attempt < EDGE_TTS_ATTEMPTS - 1:
            await asyncio.sleep(1.0)
    raise RuntimeError(f"Edge TTS failed for {path.name}") from last_error


def _voice_line_for_scene(scene: ScenePlan) -> str:
    text = scene.narration.strip().replace("...", ".").replace("…", ".").replace("*", "")
    text = text.replace("’", "'").replace("‘", "'")
    if not text:
        return ""
    return text


def _pyttsx3_voice(narration: str, output_dir: Path) -> Path | None:
    audio_path = output_dir / "narration.wav"
    try:
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", 184)
        engine.setProperty("volume", 0.96)
        engine.save_to_file(narration, str(audio_path))
        engine.runAndWait()
    except Exception:
        return None
    return audio_path if audio_path.exists() else None


def synthesize_music(plan: VideoPlan, output_dir: Path, duration: float, settings: Settings) -> Path | None:
    if not settings.music_enabled:
        return None
    music_path = output_dir / "original_music.wav"
    sample_rate = settings.audio_sample_rate
    total = int(max(3.0, duration) * sample_rate)
    t = np.arange(total, dtype=np.float32) / sample_rate
    bpm = 96 + (abs(hash(plan.topic)) % 18)
    beat = 60.0 / bpm
    key = 110.0 * (2 ** ((abs(hash(plan.angle)) % 5) / 12))

    audio = np.zeros(total, dtype=np.float32)
    chord_steps = [0, 3, 7, 10, 5, 8, 12, 10]
    chord_len = beat * 4
    for idx, step in enumerate(chord_steps):
        start = int(idx * chord_len * sample_rate)
        end = min(total, int((idx + 1) * chord_len * sample_rate))
        if start >= total:
            break
        local_t = t[: end - start]
        root = key * (2 ** (step / 12))
        pad = (
            np.sin(2 * np.pi * root * local_t)
            + 0.45 * np.sin(2 * np.pi * root * 1.5 * local_t)
            + 0.28 * np.sin(2 * np.pi * root * 2.0 * local_t)
        )
        envelope = _fade_envelope(end - start, sample_rate, 0.35, 0.45)
        audio[start:end] += 0.08 * pad * envelope

    for beat_index in range(int(duration / beat) + 1):
        beat_start = int(beat_index * beat * sample_rate)
        if beat_start >= total:
            continue
        _add_kick(audio, beat_start, sample_rate)
        if beat_index % 2 == 1:
            _add_snap(audio, beat_start, sample_rate)
        if beat_index % 4 == 3:
            _add_riser(audio, beat_start, sample_rate)

    audio += 0.012 * np.sin(2 * np.pi * (key * 4) * t) * (0.5 + 0.5 * np.sin(2 * np.pi * t / 8))
    audio = np.tanh(audio * 1.4)
    stereo = np.stack([audio * 0.92, audio], axis=1)
    pcm = np.int16(np.clip(stereo, -1, 1) * 32767)
    with wave.open(str(music_path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return music_path


def _add_kick(audio: np.ndarray, start: int, sample_rate: int) -> None:
    length = min(len(audio) - start, int(0.36 * sample_rate))
    if length <= 0:
        return
    x = np.arange(length, dtype=np.float32) / sample_rate
    freq = 76 * np.exp(-x * 12) + 38
    wave_data = np.sin(2 * np.pi * freq * x) * np.exp(-x * 10)
    audio[start : start + length] += 0.42 * wave_data


def _add_snap(audio: np.ndarray, start: int, sample_rate: int) -> None:
    length = min(len(audio) - start, int(0.09 * sample_rate))
    if length <= 0:
        return
    rng = np.random.default_rng(start)
    noise = rng.uniform(-1, 1, length).astype(np.float32) * np.exp(-np.linspace(0, 8, length))
    audio[start : start + length] += 0.1 * noise


def _add_riser(audio: np.ndarray, start: int, sample_rate: int) -> None:
    length = min(len(audio) - start, int(0.45 * sample_rate))
    if length <= 0:
        return
    x = np.arange(length, dtype=np.float32) / sample_rate
    freq = np.linspace(360, 940, length)
    riser = np.sin(2 * np.pi * freq * x) * np.linspace(0, 1, length) ** 2
    audio[start : start + length] += 0.055 * riser


def _fade_envelope(length: int, sample_rate: int, attack: float, release: float) -> np.ndarray:
    env = np.ones(length, dtype=np.float32)
    attack_len = min(length, int(attack * sample_rate))
    release_len = min(length, int(release * sample_rate))
    if attack_len:
        env[:attack_len] *= np.linspace(0, 1, attack_len)
    if release_len:
        env[-release_len:] *= np.linspace(1, 0, release_len)
    return env


def _fit_external_video_clip(source, width: int, height: int, duration: float):
    from moviepy.video.fx.all import loop as video_loop

    source_duration = float(source.duration or 0)
    if source_duration <= 0:
        return source.set_duration(duration).resize((width, height))
    clip = video_loop(source, duration=duration) if source_duration < duration else source.subclip(0, duration)
    scale = max(width / max(1, clip.w), height / max(1, clip.h))
    clip = clip.resize(scale)
    return clip.crop(
        x_center=clip.w / 2,
        y_center=clip.h / 2,
        width=width,
        height=height,
    ).set_duration(duration)


def _normalize_durations(scenes: list[Scene], target_seconds: float) -> list[Scene]:
    if not scenes:
        return []
    current = sum(max(1.0, scene.duration_seconds) for scene in scenes)
    factor = target_seconds / current if current else 1.0
    normalized: list[Scene] = []
    for scene in scenes:
        normalized.append(
            Scene(
                narration=scene.narration,
                onscreen_text=scene.onscreen_text,
                visual_style=scene.visual_style,
                duration_seconds=max(2.8, round(scene.duration_seconds * factor, 2)),
            )
        )
    return normalized


def _frame_for_scene(
    scene: Scene,
    index: int,
    t: float,
    width: int,
    height: int,
    presenter_enabled: bool = True,
    presenter_asset: str | None = None,
    settings: Settings | None = None,
) -> np.ndarray:
    advanced_rendering = settings.advanced_rendering if settings else True
    cinematic_intensity = settings.cinematic_intensity if settings else 0.85
    particle_density = settings.particle_density if settings else 1.0

    palette = CINEMA_PALETTES[index % len(CINEMA_PALETTES)]
    _, cyan, gold, rose = palette
    progress = min(1.0, max(0.0, t / max(scene.duration_seconds, 0.01)))
    ease = _ease_out_cubic(progress)
    shot_meta = current_shot_entry(scene, t) if isinstance(scene, ScenePlan) else {}
    shot = str(shot_meta.get("shot") or (current_shot(scene, t) if isinstance(scene, ScenePlan) else "presenter_medium"))
    is_broll = isinstance(scene, ScenePlan) and (shot_meta.get("type") == "broll" or shot in _BROLL_RENDERERS)

    scene_type = "hook"
    if isinstance(scene, ScenePlan):
        scene_type = scene.purpose

    color_scheme = "cyan_gold"
    if scene_type in ("warning",):
        color_scheme = "danger_red"
    elif scene_type in ("reveal", "payoff"):
        color_scheme = "blue_rose"
    elif scene_type in ("control",):
        color_scheme = "teal_amber"

    if advanced_rendering:
        img = create_advanced_background(width, height, scene_type, t, index, color_scheme)
        img = img.convert("RGBA")
    else:
        img = _base_background(width, height, index).copy()

    draw = ImageDraw.Draw(img, "RGBA")

    if advanced_rendering and isinstance(scene, ScenePlan):
        light_sources = [
            {"x": width * 0.5, "y": height * 0.2, "color": cyan, "intensity": 0.6 * cinematic_intensity, "radius": width * 0.45},
            {"x": width * 0.2, "y": height * 0.6, "color": gold, "intensity": 0.35 * cinematic_intensity, "radius": width * 0.3},
        ]
        fog_overlay = render_volumetric_fog(width, height, light_sources, fog_density=0.12 * cinematic_intensity, time=t)
        img = Image.alpha_composite(img, fog_overlay)
        draw = ImageDraw.Draw(img, "RGBA")

        if scene_type in ("reveal", "cta", "payoff"):
            god_rays = render_god_rays(
                width, height,
                light_pos=(width * 0.5, height * 0.15),
                ray_count=10,
                time=t,
                color=cyan,
                intensity=0.2 * cinematic_intensity,
            )
            img = Image.alpha_composite(img, god_rays)
            draw = ImageDraw.Draw(img, "RGBA")

    _draw_depth_background(draw, width, height, scene, index, progress, cyan, gold, rose, shot_meta)
    if is_broll:
        _draw_broll_scene(draw, width, height, scene, index, progress, t, cyan, gold, rose, shot_meta)
    else:
        _draw_cinematic_world(draw, width, height, scene, index, progress, cyan, gold, rose, shot)

    if advanced_rendering:
        lighting_overlay = render_cinematic_lighting(width, height, scene_type, t, color_scheme)
        img = Image.alpha_composite(img, lighting_overlay)
        draw = ImageDraw.Draw(img, "RGBA")

    _draw_light_sweep(draw, width, height, cyan, gold, progress, index)

    if advanced_rendering:
        colors_dict = {"primary": cyan, "secondary": gold, "accent": rose}
        particles = create_scene_particles(width, height, scene_type, t, colors_dict, dt=0.033)
        if particle_density != 1.0:
            particles = particles.convert("RGBA")
            arr = np.asarray(particles).copy()
            arr[:, :, 3] = np.clip(arr[:, :, 3] * particle_density, 0, 255).astype(np.uint8)
            particles = Image.fromarray(arr, "RGBA")
        img = Image.alpha_composite(img, particles)
    else:
        _draw_particle_field(draw, width, height, cyan, gold, rose, progress, index)

    if not is_broll:
        _draw_scene_visual(draw, width, height, scene, index, progress, cyan, gold, rose)
    if presenter_enabled and shot == "over_shoulder":
        _draw_over_shoulder_silhouette(draw, width, height, progress, cyan, gold)
    show_presenter = presenter_enabled and shot not in {
        "text_only",
        "ui_closeup",
        "risk_closeup",
        "task_queue",
        "cta_lock",
        "ui_macro",
        "macro_ui",
        "text_impact",
        "vault_cutaway",
        "key_cutaway",
        "task_cutaway",
        "shield_cutaway",
        "fast_montage",
        "over_shoulder",
    } and not is_broll
    if show_presenter:
        if presenter_asset and Path(presenter_asset).exists():
            _draw_real_presenter(img, width, height, presenter_asset, progress, t, index, cyan, gold, shot, scene)
            draw = ImageDraw.Draw(img, "RGBA")
        else:
            _draw_presenter(draw, width, height, scene, index, progress, cyan, gold, rose)
        if isinstance(scene, ScenePlan):
            _draw_foreground_occlusion(draw, width, height, scene, progress, cyan, gold, rose, shot_meta)
    if isinstance(scene, ScenePlan):
        img = _apply_camera_motion(img, scene, progress, t, index)
        draw = ImageDraw.Draw(img, "RGBA")
        if should_flash(scene, t):
            draw.rectangle((0, 0, width, height), fill=(*rose, 44))
        _draw_vfx_overlay(draw, width, height, scene, index, progress, t, cyan, gold, rose, shot)
        _draw_retention_overlay(draw, width, height, scene, t, cyan, gold, rose)
    _draw_kinetic_text(draw, scene, width, height, cyan, gold, rose, ease, index, t)

    frame = np.asarray(img.convert("RGB"))

    if advanced_rendering:
        frame = cinematic_post_process(
            Image.fromarray(frame).convert("RGB"),
            time=t,
            scene_index=index,
            intensity=cinematic_intensity,
            enable_grain=True,
            enable_chromatic=True,
            enable_vignette=True,
            enable_color_grade=True,
        )
        frame = np.asarray(frame.convert("RGB"))

    return frame


@lru_cache(maxsize=32)
def _base_background(width: int, height: int, index: int) -> Image.Image:
    palette = CINEMA_PALETTES[index % len(CINEMA_PALETTES)]
    bg, cyan, _, _ = palette
    img = _cinematic_gradient(width, height, bg, cyan, index, 0.28)
    _draw_vignette(img, width, height)
    rng = np.random.default_rng(30000 + index)
    arr = np.asarray(img).astype(np.int16)
    grain = rng.normal(0, 2.4, arr.shape[:2])[:, :, None]
    arr = np.clip(arr + grain, 0, 255).astype(np.uint8)
    return ImageEnhance.Contrast(Image.fromarray(arr, "RGB")).enhance(1.05)


def _draw_depth_background(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    scene: Scene,
    index: int,
    progress: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    shot_meta: dict[str, object],
) -> None:
    if not isinstance(scene, ScenePlan):
        return
    layer_types = {str(layer.get("type")) for layer in scene.layers}
    if "background" not in layer_types:
        return
    offset = math.sin(progress * math.tau * 0.45 + index) * width * 0.018
    for band in range(5):
        y = height * (0.12 + band * 0.12)
        x0 = width * (-0.05 + band * 0.08) + offset * (band + 1)
        x1 = width * (0.62 + band * 0.1) + offset * 0.4
        color = (cyan, gold, rose)[band % 3]
        draw.line((x0, y, x1, y + height * 0.13), fill=(*color, 16 + band * 5), width=8)
    if "lens_light" in layer_types:
        flare_x = width * (0.18 + 0.62 * progress)
        flare_y = height * (0.18 + 0.05 * math.sin(progress * math.tau + index))
        for radius, alpha in ((90, 24), (170, 12), (280, 7)):
            draw.ellipse((flare_x - radius, flare_y - radius, flare_x + radius, flare_y + radius), outline=(*gold, alpha), width=3)
    if shot_meta.get("type") in {"broll", "visual_metaphor"}:
        draw.rectangle((0, 0, width, height), fill=(0, 0, 0, 22))


def _draw_broll_scene(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    scene: Scene,
    index: int,
    progress: float,
    local_time: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    shot_meta: dict[str, object],
) -> None:
    if not isinstance(scene, ScenePlan):
        return
    shot = str(shot_meta.get("broll_type") or shot_meta.get("shot") or "ai_office")
    start = float(shot_meta.get("start", 0.0))
    end = float(shot_meta.get("end", scene.duration_seconds))
    shot_progress = min(1.0, max(0.0, (local_time - start) / max(0.01, end - start)))
    if shot == "ai_office":
        _draw_broll_ai_office(draw, width, height, scene, index, shot_progress, cyan, gold, rose)
    elif shot == "task_montage":
        _draw_broll_task_montage(draw, width, height, scene, index, shot_progress, cyan, gold, rose)
    elif shot == "vault_access":
        _draw_broll_vault_access(draw, width, height, scene, index, shot_progress, cyan, gold, rose)
    elif shot == "human_review":
        _draw_broll_human_review(draw, width, height, scene, index, shot_progress, cyan, gold, rose)
    elif shot == "chaos_dashboard":
        _draw_broll_chaos_dashboard(draw, width, height, scene, index, shot_progress, cyan, gold, rose)
    elif shot == "server_room":
        _draw_broll_server_room(draw, width, height, scene, index, shot_progress, cyan, gold, rose)
    elif shot == "final_hero_system":
        _draw_broll_final_hero_system(draw, width, height, scene, index, shot_progress, cyan, gold, rose)
    else:
        _draw_hologram_core(draw, width, height, cyan, gold, rose, shot_progress, index)
    _draw_broll_label(draw, width, height, scene, shot, cyan, gold, shot_progress)


def _draw_broll_ai_office(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    scene: ScenePlan,
    index: int,
    progress: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
) -> None:
    horizon = height * 0.58
    _draw_perspective_floor(draw, width, height, horizon, cyan, gold, progress, index)
    for col in range(4):
        x = width * (0.12 + col * 0.2 + math.sin(progress * math.tau + col) * 0.01)
        draw.rounded_rectangle((x, height * 0.25, x + width * 0.12, height * 0.58), radius=18, fill=(255, 255, 255, 14), outline=(*cyan, 72), width=2)
        draw.line((x + 18, height * 0.31, x + width * 0.1, height * 0.31), fill=(*gold, 90), width=3)
    desk_y = height * 0.63
    draw.polygon([(width * 0.08, desk_y), (width * 0.72, desk_y), (width * 0.84, height * 0.82), (width * 0.0, height * 0.82)], fill=(0, 0, 0, 120), outline=(*gold, 70))
    cx, cy = width * 0.42, height * 0.49
    _draw_hologram_badge(draw, cx, cy, width * 0.15, cyan, gold, rose, progress)
    for idx, label in enumerate(["ONBOARD", "RESEARCH", "DRAFT"]):
        x = width * (0.14 + idx * 0.18)
        y = height * (0.68 - idx * 0.045)
        phase = min(1.0, max(0.0, progress * 1.5 - idx * 0.16))
        draw.rounded_rectangle((x, y, x + width * 0.2, y + 44), radius=14, fill=(4, 12, 24, 185), outline=(*(cyan if idx % 2 else gold), 125), width=2)
        draw.text((x + 14, y + 11), label, font=_font(int(width * 0.024), bold=True), fill=(255, 255, 255, 220))
        if phase > 0.72:
            _draw_check(draw, x + width * 0.17, y + 24, gold)


def _draw_broll_task_montage(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    scene: ScenePlan,
    index: int,
    progress: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
) -> None:
    _draw_task_speed_lanes(draw, width, height, cyan, gold, rose, progress)
    font = _font(int(width * 0.052), bold=True)
    for idx, label in enumerate(["RESEARCH", "DRAFT", "SEND"]):
        p = (progress * 1.35 + idx * 0.28) % 1
        x = width * (0.72 - p * 0.62)
        y = height * (0.28 + idx * 0.15)
        color = (cyan, gold, rose)[idx % 3]
        draw.rounded_rectangle((x, y, x + width * 0.34, y + 74), radius=18, fill=(0, 0, 0, 128), outline=(*color, 160), width=3)
        draw.text((x + 18, y + 16), label, font=font, fill=(255, 255, 255, 225))
        draw.line((x - width * 0.22, y + 37, x, y + 37), fill=(*color, 120), width=6)


def _draw_broll_vault_access(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    scene: ScenePlan,
    index: int,
    progress: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
) -> None:
    _draw_cinematic_vault(draw, width, height, cyan, gold, rose, progress, danger=True)
    for ring in range(4):
        r = width * (0.18 + ring * 0.075 + progress * 0.04)
        cx, cy = width * 0.44, height * 0.51
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(*rose, max(18, 125 - ring * 24)), width=3)
    font = _font(int(width * 0.038), bold=True)
    draw.rounded_rectangle((width * 0.09, height * 0.23, width * 0.53, height * 0.29), radius=22, fill=(60, 0, 16, 150), outline=(*rose, 180), width=2)
    draw.text((width * 0.12, height * 0.245), "PERMISSION GATE", font=font, fill=(255, 245, 245, 235))


def _draw_broll_human_review(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    scene: ScenePlan,
    index: int,
    progress: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
) -> None:
    _draw_review_cockpit(draw, width, height, cyan, gold, rose, progress)
    hand_x = width * (0.73 - 0.1 * min(1.0, progress * 1.2))
    hand_y = height * 0.61
    draw.line((width * 0.9, height * 0.72, hand_x, hand_y), fill=(31, 41, 67, 235), width=int(width * 0.045))
    draw.ellipse((hand_x - 34, hand_y - 30, hand_x + 34, hand_y + 30), fill=(214, 155, 120, 245), outline=(*gold, 120), width=2)
    button = (width * 0.53, height * 0.57, width * 0.78, height * 0.64)
    draw.rounded_rectangle(button, radius=26, fill=(*gold, 135), outline=(*cyan, 150), width=3)
    draw.text((button[0] + 34, button[1] + 18), "APPROVE", font=_font(int(width * 0.034), bold=True), fill=(6, 11, 22, 245))
    if progress > 0.55:
        _draw_check(draw, button[2] - 42, button[1] + 36, cyan)


def _draw_broll_chaos_dashboard(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    scene: ScenePlan,
    index: int,
    progress: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
) -> None:
    draw.rectangle((0, 0, width, height), fill=(42, 2, 16, 42))
    panel = (width * 0.08, height * 0.28, width * 0.78, height * 0.68)
    draw.rounded_rectangle(panel, radius=28, fill=(5, 7, 18, 205), outline=(*rose, 190), width=4)
    font = _font(int(width * 0.036), bold=True)
    draw.text((panel[0] + 30, panel[1] + 24), "ACCESS ALERT", font=font, fill=(*rose, 245))
    points = []
    for idx in range(18):
        x = panel[0] + 34 + idx * (panel[2] - panel[0] - 68) / 17
        y = panel[1] + height * (0.24 + 0.06 * math.sin(idx * 0.8 + progress * math.tau * 2))
        if idx > 11:
            y += height * (idx - 11) * 0.018
        points.append((x, y))
    draw.line(points, fill=(*rose, 220), width=5)
    for idx in range(4):
        y = panel[1] + height * (0.15 + idx * 0.065)
        draw.rounded_rectangle((panel[0] + 32, y, panel[0] + width * 0.36, y + 34), radius=12, fill=(255, 255, 255, 18), outline=(*rose, 90))
    for glitch in range(8):
        y = height * (0.2 + glitch * 0.08 + math.sin(progress * math.tau * 4 + glitch) * 0.01)
        draw.rectangle((width * 0.02, y, width * (0.2 + 0.6 * ((glitch + index) % 3) / 3), y + 5), fill=(*rose, 95))


def _draw_broll_server_room(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    scene: ScenePlan,
    index: int,
    progress: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
) -> None:
    horizon = height * 0.55
    _draw_perspective_floor(draw, width, height, horizon, cyan, gold, progress, index)
    _draw_server_architecture(draw, width, height, horizon, cyan, gold, progress, index, intense=False)
    for lane in range(5):
        y = height * (0.38 + lane * 0.075)
        x0 = width * (0.1 + progress * 0.12)
        x1 = width * (0.72 - lane * 0.04)
        color = cyan if lane % 2 else gold
        draw.line((x0, y, x1, y + height * 0.13), fill=(*color, 115), width=4)
        draw.ellipse((x1 - 12, y + height * 0.13 - 12, x1 + 12, y + height * 0.13 + 12), fill=(*color, 220))


def _draw_broll_final_hero_system(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    scene: ScenePlan,
    index: int,
    progress: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
) -> None:
    _draw_hologram_core(draw, width, height, cyan, gold, rose, progress, index)
    x = width * 0.55
    head_y = height * 0.36
    draw.ellipse((x - 48, head_y - 48, x + 48, head_y + 48), fill=(0, 0, 0, 150), outline=(*cyan, 115), width=3)
    draw.rounded_rectangle((x - 82, head_y + 42, x + 92, height * 0.74), radius=42, fill=(0, 0, 0, 155), outline=(*gold, 90), width=2)
    _draw_large_key(draw, width * 0.36, height * (0.55 + 0.02 * math.sin(progress * math.tau)), width * 0.13, gold)
    for side, label in [(-1, "NO"), (1, "YES")]:
        gx = width * (0.36 + side * 0.18)
        gy = height * 0.72
        draw.rounded_rectangle((gx - 58, gy - 26, gx + 58, gy + 26), radius=18, fill=(255, 255, 255, 18), outline=(*(rose if side < 0 else cyan), 130), width=2)
        draw.text((gx - 28, gy - 15), label, font=_font(int(width * 0.028), bold=True), fill=(255, 255, 255, 220))


def _draw_broll_label(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    scene: ScenePlan,
    shot: str,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    progress: float,
) -> None:
    label = {
        "ai_office": "AI WORKER",
        "task_montage": "TASKS MOVE",
        "vault_access": "ACCESS RISK",
        "human_review": "HUMAN REVIEW",
        "chaos_dashboard": "NO GUARDRAILS",
        "server_room": "SAFE SPEED",
        "final_hero_system": "WHO GETS KEYS?",
    }.get(shot, clean_text(scene.purpose.upper(), 18))
    font = _font(int(width * 0.031), bold=True)
    x = width * 0.08
    y = height * 0.11
    text_w = draw.textlength(label, font=font)
    draw.rounded_rectangle((x - 16, y - 10, x + text_w + 20, y + font.size + 12), radius=18, fill=(0, 0, 0, 120), outline=(*gold, 120), width=2)
    draw.text((x, y), label, font=font, fill=(*cyan, int(160 + 80 * min(1.0, progress * 2))))


def _cinematic_gradient(
    width: int,
    height: int,
    bg: tuple[int, int, int],
    accent: tuple[int, int, int],
    index: int,
    progress: float,
) -> Image.Image:
    y = np.linspace(0, 1, height, dtype=np.float32)[:, None]
    x = np.linspace(0, 1, width, dtype=np.float32)[None, :]
    base = np.zeros((height, width, 3), dtype=np.float32)
    for c in range(3):
        base[:, :, c] = bg[c] + (accent[c] * 0.34 - bg[c]) * (0.58 * y + 0.28 * x)
    wave = 0.5 + 0.5 * np.sin((x * 4.5 + y * 3.0 + progress * 1.8 + index) * math.tau)
    base += wave[:, :, None] * np.array(accent, dtype=np.float32) * 0.06
    return Image.fromarray(np.uint8(np.clip(base, 0, 255)), "RGB")


def _draw_vignette(img: Image.Image, width: int, height: int) -> None:
    yy, xx = np.mgrid[0:height, 0:width]
    dx = (xx - width / 2) / (width / 2)
    dy = (yy - height / 2) / (height / 2)
    mask = np.clip((dx * dx + dy * dy - 0.32) / 0.76, 0, 1)
    arr = np.asarray(img).astype(np.float32)
    arr *= (1 - mask[:, :, None] * 0.5)
    img.paste(Image.fromarray(np.uint8(np.clip(arr, 0, 255))))


def _apply_camera_motion(img: Image.Image, scene: ScenePlan, progress: float, local_time: float, index: int) -> Image.Image:
    scale, dx, dy = camera_state(scene, progress, local_time, index)
    if abs(scale - 1.0) < 0.005 and abs(dx) < 0.5 and abs(dy) < 0.5:
        return img
    width, height = img.size
    new_w = max(width, int(width * scale))
    new_h = max(height, int(height * scale))
    resized = img.resize((new_w, new_h), Image.Resampling.BICUBIC)
    left = int((new_w - width) / 2 - dx)
    top = int((new_h - height) / 2 - dy)
    left = max(0, min(left, new_w - width))
    top = max(0, min(top, new_h - height))
    return resized.crop((left, top, left + width, top + height))


def _normalize_video_loudness(raw_path: Path, output_path: Path, settings: Settings) -> None:
    try:
        from imageio_ffmpeg import get_ffmpeg_exe

        ffmpeg = get_ffmpeg_exe()
    except Exception:
        ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        shutil.move(str(raw_path), str(output_path))
        return

    command = [
        ffmpeg,
        "-y",
        "-i",
        str(raw_path),
        "-af",
        f"loudnorm=I={settings.audio_target_lufs}:TP=-1.5:LRA=9",
        "-ar",
        str(settings.audio_sample_rate),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output_path),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
    except Exception:
        shutil.move(str(raw_path), str(output_path))


def _draw_light_sweep(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    progress: float,
    index: int,
) -> None:
    sweep_x = int((-0.35 + progress * 1.65) * width)
    for offset, alpha in ((0, 42), (18, 24), (38, 12)):
        draw.polygon(
            [
                (sweep_x + offset, -height * 0.1),
                (sweep_x + offset + width * 0.12, -height * 0.1),
                (sweep_x + offset - width * 0.32, height * 1.1),
                (sweep_x + offset - width * 0.44, height * 1.1),
            ],
            fill=(*(gold if index % 2 else cyan), alpha),
        )


def _draw_particle_field(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
    index: int,
) -> None:
    rng = np.random.default_rng(9000 + index)
    for particle in range(62):
        depth = rng.uniform(0.25, 1.0)
        px = (rng.uniform(-0.1, 1.1) + progress * (0.08 + depth * 0.06)) % 1.2 - 0.1
        py = (rng.uniform(-0.1, 1.1) + math.sin(progress * math.tau + particle) * 0.012) % 1.2 - 0.1
        x = int(px * width)
        y = int(py * height)
        radius = int(1 + depth * 3)
        color = (cyan, gold, rose)[particle % 3]
        alpha = int(35 + depth * 110)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*color, alpha))
        if particle % 9 == 0:
            draw.line((x, y, x - 35 * depth, y + 18 * depth), fill=(*color, alpha // 2), width=1)


def _draw_cinematic_world(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    scene: Scene,
    index: int,
    progress: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    shot: str,
) -> None:
    if not isinstance(scene, ScenePlan):
        return
    theme = str(scene.visual_metaphor.get("theme", "ai_worker"))
    location = scene.location.lower()
    horizon = height * 0.56

    _draw_perspective_floor(draw, width, height, horizon, cyan, gold, progress, index)
    _draw_server_architecture(draw, width, height, horizon, cyan, gold, progress, index, intense=theme in {"risk", "access"})
    _draw_volumetric_beams(draw, width, height, cyan, gold, rose, progress, theme)

    if "vault" in location or theme in {"access", "risk"} or shot == "vault_cutaway":
        _draw_cinematic_vault(draw, width, height, cyan, gold, rose, progress, danger=theme == "risk")
    elif "cockpit" in location or theme == "control" or shot == "shield_cutaway":
        _draw_review_cockpit(draw, width, height, cyan, gold, rose, progress)
    elif theme == "speed" or shot in {"fast_montage", "task_cutaway"}:
        _draw_task_speed_lanes(draw, width, height, cyan, gold, rose, progress)
    elif theme == "question" or shot in {"key_cutaway", "final_hero"}:
        _draw_hero_key_foreground(draw, width, height, cyan, gold, rose, progress)
    else:
        _draw_command_room_core(draw, width, height, cyan, gold, rose, progress)

    if shot in {"establishing", "final_hero"}:
        _draw_location_label(draw, width, height, scene.location, cyan, gold)
    if shot in {"ui_macro", "macro_ui"}:
        _draw_macro_focus_overlay(draw, width, height, cyan, gold, progress)


def _draw_perspective_floor(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    horizon: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    progress: float,
    index: int,
) -> None:
    floor_top = horizon
    draw.polygon(
        [(0, height), (width, height), (width * 0.62, floor_top), (width * 0.38, floor_top)],
        fill=(0, 0, 0, 92),
    )
    for rail in range(-5, 6):
        x0 = width * (0.5 + rail * 0.045)
        x1 = width * (0.5 + rail * 0.18)
        color = cyan if rail % 2 else gold
        draw.line((x0, floor_top, x1, height), fill=(*color, 34), width=2)
    for step in range(9):
        p = (step + (progress * 1.6 + index * 0.11) % 1) / 9
        y = floor_top + (height - floor_top) * (p ** 1.8)
        span = width * (0.1 + p * 0.8)
        color = cyan if step % 2 else gold
        draw.line((width / 2 - span / 2, y, width / 2 + span / 2, y), fill=(*color, int(32 + p * 70)), width=2)


def _draw_server_architecture(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    horizon: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    progress: float,
    index: int,
    *,
    intense: bool,
) -> None:
    for side in (-1, 1):
        for tower in range(5):
            depth = tower / 5
            tower_w = width * (0.08 + depth * 0.03)
            tower_h = height * (0.38 + depth * 0.18)
            gap = width * (0.06 + tower * 0.105)
            x = width * 0.5 + side * (width * 0.24 + gap)
            x0 = x - tower_w / 2
            y0 = horizon - tower_h * 0.66
            color = gold if intense and tower % 2 else cyan
            draw.rounded_rectangle(
                (x0, y0, x0 + tower_w, horizon + height * 0.12),
                radius=12,
                fill=(3, 9, 20, 120),
                outline=(*color, int(38 + depth * 72)),
                width=2,
            )
            for slot in range(7):
                yy = y0 + 22 + slot * tower_h * 0.095
                phase = 0.45 + 0.55 * math.sin(progress * math.tau * 2 + slot + tower + index)
                draw.line((x0 + 12, yy, x0 + tower_w - 12, yy), fill=(*color, int(20 + phase * 80)), width=2)


def _draw_volumetric_beams(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
    theme: str,
) -> None:
    colors = (rose, gold, cyan) if theme in {"risk", "access"} else (cyan, gold, cyan)
    for beam in range(5):
        x = width * (0.08 + beam * 0.21 + math.sin(progress * math.tau + beam) * 0.018)
        color = colors[beam % len(colors)]
        draw.polygon(
            [
                (x - width * 0.035, 0),
                (x + width * 0.07, 0),
                (x + width * (0.16 + beam * 0.01), height),
                (x - width * (0.08 + beam * 0.02), height),
            ],
            fill=(*color, 13 if theme not in {"risk", "access"} else 22),
        )


def _draw_command_room_core(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
) -> None:
    cx, cy = width * 0.43, height * 0.46
    for ring in range(4):
        r = width * (0.1 + ring * 0.045 + 0.012 * math.sin(progress * math.tau + ring))
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(*(cyan if ring % 2 else gold), 48 + ring * 26), width=2)
    draw.rounded_rectangle((width * 0.14, height * 0.36, width * 0.58, height * 0.62), radius=28, fill=(255, 255, 255, 12), outline=(*cyan, 84), width=2)
    _draw_cursor(draw, width * (0.28 + progress * 0.18), height * (0.51 + math.sin(progress * math.tau) * 0.035), gold)
    _draw_hologram_badge(draw, width * 0.43, height * 0.48, width * 0.13, cyan, gold, rose, progress)


def _draw_cinematic_vault(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
    *,
    danger: bool,
) -> None:
    cx, cy = width * 0.42, height * 0.51
    base_color = rose if danger else gold
    radius = width * (0.19 + 0.012 * math.sin(progress * math.tau * 2))
    draw.ellipse((cx - radius * 1.18, cy - radius * 1.18, cx + radius * 1.18, cy + radius * 1.18), fill=(0, 0, 0, 78), outline=(*base_color, 150), width=5)
    for ring in range(4):
        r = radius * (0.55 + ring * 0.16)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(*(base_color if ring % 2 else cyan), 70 + ring * 22), width=3)
    for spoke in range(12):
        angle = spoke * math.tau / 12 + progress * 0.4
        draw.line(
            (cx, cy, cx + math.cos(angle) * radius * 0.95, cy + math.sin(angle) * radius * 0.95),
            fill=(*base_color, 80),
            width=2,
        )
    key_x = width * (0.22 + 0.09 * progress)
    key_y = height * (0.42 + 0.02 * math.sin(progress * math.tau * 2))
    _draw_large_key(draw, key_x, key_y, width * 0.14, gold)
    if danger:
        for spark in range(8):
            angle = spark * math.tau / 8 + progress * math.tau
            x = cx + math.cos(angle) * radius * 1.08
            y = cy + math.sin(angle) * radius * 1.08
            draw.line((x, y, x + math.cos(angle) * 42, y + math.sin(angle) * 28), fill=(*rose, 180), width=3)


def _draw_review_cockpit(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
) -> None:
    x0, y0 = width * 0.12, height * 0.36
    panel_w, panel_h = width * 0.48, height * 0.28
    draw.rounded_rectangle((x0, y0, x0 + panel_w, y0 + panel_h), radius=26, fill=(3, 10, 22, 170), outline=(*cyan, 145), width=3)
    font = _font(int(width * 0.026), bold=True)
    for idx, label in enumerate(("PERMISSION", "REVIEW", "AUDIT LOG")):
        y = y0 + 54 + idx * 58
        phase = min(1, max(0, progress * 1.4 - idx * 0.15))
        draw.rounded_rectangle((x0 + 28, y, x0 + panel_w - 34, y + 38), radius=15, fill=(255, 255, 255, 18), outline=(*cyan, 80))
        draw.text((x0 + 48, y + 8), label, font=font, fill=(255, 255, 255, 225))
        if phase > 0.55:
            _draw_check(draw, x0 + panel_w - 56, y + 20, gold)
    shield_cx, shield_cy = width * 0.47, height * 0.5
    pulse = 0.65 + 0.35 * math.sin(progress * math.tau * 2)
    draw.polygon(
        [
            (shield_cx, shield_cy - 74),
            (shield_cx + 64, shield_cy - 34),
            (shield_cx + 50, shield_cy + 64),
            (shield_cx, shield_cy + 104),
            (shield_cx - 50, shield_cy + 64),
            (shield_cx - 64, shield_cy - 34),
        ],
        fill=(*cyan, int(22 + pulse * 24)),
        outline=(*gold, int(130 + pulse * 80)),
    )


def _draw_task_speed_lanes(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
) -> None:
    font = _font(int(width * 0.026), bold=True)
    labels = ["RESEARCH", "DRAFT", "DONE"]
    for idx, label in enumerate(labels):
        p = (progress * 1.35 + idx * 0.16) % 1
        x = width * (0.02 + p * 0.55)
        y = height * (0.37 + idx * 0.055)
        color = (cyan, gold, rose)[idx % 3]
        draw.line((x - width * 0.24, y + 22, x + width * 0.34, y + 22), fill=(*color, 70), width=5)
        draw.rounded_rectangle((x, y, x + width * 0.22, y + 44), radius=14, fill=(255, 255, 255, 24), outline=(*color, 150), width=2)
        draw.text((x + 17, y + 10), label, font=font, fill=(255, 255, 255, 220))


def _draw_hero_key_foreground(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
) -> None:
    x = width * 0.37
    y = height * (0.53 + math.sin(progress * math.tau) * 0.02)
    size = width * (0.15 + 0.03 * math.sin(progress * math.tau * 2))
    for ring in range(4):
        r = size * (0.7 + ring * 0.32 + progress * 0.08)
        draw.ellipse((x - r, y - r, x + r, y + r), outline=(*(gold if ring % 2 else cyan), max(16, 98 - ring * 18)), width=2)
    _draw_large_key(draw, x, y, size, gold)
    draw.rounded_rectangle((width * 0.1, height * 0.67, width * 0.58, height * 0.72), radius=24, fill=(0, 0, 0, 90), outline=(*cyan, 110), width=2)


def _draw_hologram_badge(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    size: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
) -> None:
    draw.rounded_rectangle((cx - size, cy - size * 0.62, cx + size, cy + size * 0.62), radius=22, fill=(255, 255, 255, 22), outline=(*cyan, 150), width=3)
    draw.ellipse((cx - size * 0.26, cy - size * 0.38, cx + size * 0.26, cy + size * 0.14), outline=(*gold, 190), width=3)
    draw.arc((cx - size * 0.46, cy - size * 0.05, cx + size * 0.46, cy + size * 0.58), start=200, end=340, fill=(*gold, 170), width=3)
    draw.line((cx - size * 0.72, cy + size * 0.42, cx + size * 0.72, cy + size * 0.42), fill=(*rose, int(70 + 70 * progress)), width=3)


def _draw_large_key(draw: ImageDraw.ImageDraw, x: float, y: float, size: float, color: tuple[int, int, int]) -> None:
    draw.ellipse((x - size * 0.36, y - size * 0.36, x + size * 0.36, y + size * 0.36), outline=(*color, 230), width=max(4, int(size * 0.05)))
    draw.line((x + size * 0.28, y, x + size * 1.05, y), fill=(*color, 230), width=max(5, int(size * 0.07)))
    draw.rectangle((x + size * 0.72, y, x + size * 0.82, y + size * 0.28), fill=(*color, 220))
    draw.rectangle((x + size * 0.91, y, x + size * 1.01, y + size * 0.2), fill=(*color, 220))


def _draw_location_label(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    location: str,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
) -> None:
    font = _font(int(width * 0.022), bold=True)
    label = clean_text(location.upper(), 34)
    text_w = draw.textlength(label, font=font)
    x = width * 0.08
    y = height * 0.116
    draw.rounded_rectangle((x - 12, y - 8, x + text_w + 18, y + font.size + 10), radius=14, fill=(0, 0, 0, 82), outline=(*gold, 88))
    draw.text((x, y), label, font=font, fill=(*cyan, 210))


def _draw_macro_focus_overlay(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    progress: float,
) -> None:
    focus = (width * 0.36, height * 0.5)
    w, h = width * 0.52, height * 0.23
    draw.rounded_rectangle((focus[0] - w / 2, focus[1] - h / 2, focus[0] + w / 2, focus[1] + h / 2), radius=26, outline=(*gold, 155), width=4)
    scan_y = focus[1] - h / 2 + (h * progress)
    draw.line((focus[0] - w / 2 + 16, scan_y, focus[0] + w / 2 - 16, scan_y), fill=(*cyan, 180), width=4)


def _draw_over_shoulder_silhouette(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    progress: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
) -> None:
    x = width * (0.77 + math.sin(progress * math.tau) * 0.01)
    shoulder_y = height * 0.72
    head_y = height * 0.43
    draw.ellipse((x - width * 0.075, head_y - width * 0.075, x + width * 0.075, head_y + width * 0.075), fill=(0, 0, 0, 170), outline=(*cyan, 70), width=2)
    draw.rounded_rectangle((x - width * 0.12, height * 0.51, x + width * 0.13, height * 0.9), radius=42, fill=(0, 0, 0, 170), outline=(*gold, 50), width=2)
    draw.line((x - width * 0.12, height * 0.55, width * 0.48, height * 0.49), fill=(*gold, 70), width=3)


def _draw_foreground_occlusion(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    scene: ScenePlan,
    progress: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    shot_meta: dict[str, object],
) -> None:
    if not scene.character_integration.get("foreground_occlusion"):
        return
    labels = scene.caption_plan.get("ui_labels", [])[:3] if scene.caption_plan else []
    base_x = width * (0.08 + 0.035 * math.sin(progress * math.tau))
    base_y = height * 0.58
    font = _font(int(width * 0.025), bold=True)
    for idx, label in enumerate(labels):
        slide = _ease_out_cubic(min(1.0, max(0.0, progress * 1.4 - idx * 0.15)))
        x = base_x + idx * width * 0.17 + (1 - slide) * width * 0.08
        y = base_y + math.sin(progress * math.tau + idx) * height * 0.012 + idx * height * 0.045
        color = (cyan, gold, rose)[idx % 3]
        text = str(label).upper()[:18]
        text_w = draw.textlength(text, font=font)
        draw.rounded_rectangle((x - 14, y - 10, x + text_w + 18, y + font.size + 13), radius=16, fill=(0, 0, 0, 112), outline=(*color, 130), width=2)
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 220))
        draw.line((x - 6, y + font.size + 18, x + text_w + 8, y + font.size + 18), fill=(*color, 110), width=3)
    scan_x = width * (0.04 + 0.58 * progress)
    draw.line((scan_x, height * 0.34, scan_x + width * 0.12, height * 0.78), fill=(*cyan, 62), width=5)


def _draw_scene_visual(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    scene: Scene,
    index: int,
    progress: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
) -> None:
    if isinstance(scene, ScenePlan):
        shot = current_shot(scene, progress * scene.duration_seconds)
        theme = str(scene.visual_metaphor.get("theme", ""))
        if shot in {"vault_cutaway", "impact_reveal"} or theme in {"access", "risk"}:
            _draw_access_lock(draw, width, height, cyan, gold, rose, progress)
            return
        if shot in {"key_cutaway", "final_hero"} or theme == "question":
            _draw_key_scene(draw, width, height, cyan, gold, rose, progress)
            return
        if shot in {"shield_cutaway", "over_shoulder"} or theme == "control":
            _draw_approval_dashboard(draw, width, height, cyan, gold, rose, progress)
            return
        if shot in {"task_cutaway", "fast_montage"} or theme == "speed":
            _draw_task_queue(draw, width, height, cyan, gold, rose, progress)
            return
        if shot in {"ui_macro", "macro_ui"}:
            _draw_glass_panels(draw, width, height, cyan, gold, rose, progress, scene)
            return
    kind = _scene_kind(scene, index)
    if kind == "agent_workspace":
        _draw_agent_workspace(draw, width, height, cyan, gold, rose, progress)
    elif kind == "task_queue":
        _draw_task_queue(draw, width, height, cyan, gold, rose, progress)
    elif kind == "access_risk":
        _draw_access_lock(draw, width, height, cyan, gold, rose, progress)
    elif kind == "approval":
        _draw_approval_dashboard(draw, width, height, cyan, gold, rose, progress)
    elif kind == "keys":
        _draw_key_scene(draw, width, height, cyan, gold, rose, progress)
    elif kind == "network":
        _draw_network_map(draw, width, height, cyan, gold, rose, progress, index)
    elif kind == "panels":
        _draw_glass_panels(draw, width, height, cyan, gold, rose, progress, scene)
    elif kind == "timeline":
        _draw_timeline_wave(draw, width, height, cyan, gold, rose, progress)
    elif kind == "pressure":
        _draw_pressure_scene(draw, width, height, cyan, gold, rose, progress)
    else:
        _draw_hologram_core(draw, width, height, cyan, gold, rose, progress, index)


def _scene_kind(scene: Scene, index: int) -> str:
    text = f"{scene.narration} {scene.onscreen_text} {scene.visual_style}".lower()
    if any(word in text for word in ("login", "browser", "agent", "intern", "chatbot", "worker")):
        return "agent_workspace"
    if any(word in text for word in ("boring", "admin", "research", "reports", "task", "finished")):
        return "task_queue"
    if any(word in text for word in ("risk", "access", "permission", "mistake", "wide access")):
        return "access_risk"
    if any(word in text for word in ("manager", "review", "approval", "human", "clear rules", "narrow jobs")):
        return "approval"
    if any(word in text for word in ("keys", "disciplined", "question")):
        return "keys"
    if any(word in text for word in ("time", "timing", "future", "wave", "next")):
        return "timeline"
    if any(word in text for word in ("attention", "cluster", "map")):
        return "network"
    if any(word in text for word in ("trap", "hype", "squeezed", "pressure")):
        return "pressure"
    if index % 3 == 0:
        return "panels"
    return "hologram"


def _draw_agent_workspace(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
) -> None:
    left = width * 0.08
    top = height * 0.34
    window_w = width * 0.55
    window_h = height * 0.28
    slide = _ease_out_back(min(1, progress * 1.3))
    x0 = left - (1 - slide) * width * 0.18
    draw.rounded_rectangle((x0, top, x0 + window_w, top + window_h), radius=24, fill=(5, 12, 25, 205), outline=(*cyan, 150), width=3)
    for dot, color in enumerate((rose, gold, cyan)):
        x = x0 + 28 + dot * 24
        draw.ellipse((x - 6, top + 22, x + 6, top + 34), fill=(*color, 210))
    draw.rounded_rectangle((x0 + 30, top + 58, x0 + window_w - 30, top + 92), radius=15, fill=(255, 255, 255, 22), outline=(*gold, 90))
    font = _font(int(width * 0.034), bold=True)
    draw.text((x0 + 48, top + 61), "agent://task-runner", font=font, fill=(255, 255, 255, 215))
    for row in range(4):
        phase = min(1, max(0, progress * 1.5 - row * 0.16))
        y = top + 122 + row * 40
        draw.rounded_rectangle((x0 + 34, y, x0 + 350, y + 24), radius=11, fill=(*cyan, int(34 + phase * 55)))
        draw.line((x0 + 48, y + 12, x0 + 48 + 245 * phase, y + 12), fill=(*gold, 170), width=4)
        if phase > 0.92:
            _draw_check(draw, x0 + window_w - 64, y + 12, cyan)
    _draw_cursor(draw, x0 + 390 + math.sin(progress * math.tau) * 80, top + 178 + math.cos(progress * math.tau) * 32, gold)


def _draw_task_queue(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
) -> None:
    font = _font(int(width * 0.029), bold=True)
    labels = ["research", "draft", "done"]
    for idx, label in enumerate(labels):
        phase = min(1, max(0, progress * 1.45 - idx * 0.14))
        x = width * (0.1 + idx * 0.135)
        y = height * (0.39 + idx * 0.045)
        draw.rounded_rectangle((x, y, x + width * 0.32, y + height * 0.07), radius=18, fill=(255, 255, 255, 28), outline=(*(cyan if idx % 2 else gold), 150), width=2)
        draw.text((x + 22, y + 18), label.upper(), font=font, fill=(255, 255, 255, 225))
        draw.rounded_rectangle((x + width * 0.21, y + 21, x + width * 0.29, y + 35), radius=7, fill=(255, 255, 255, 18), outline=(*cyan, 80))
        draw.rounded_rectangle((x + width * 0.21, y + 21, x + width * (0.21 + 0.08 * phase), y + 35), radius=7, fill=(*rose, 160))
        if phase > 0.86:
            _draw_check(draw, x + width * 0.3, y + 34, gold)


def _draw_access_lock(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
) -> None:
    cx, cy = width * 0.42, height * 0.49
    pulse = 1 + 0.08 * math.sin(progress * math.tau * 3)
    radius = width * 0.16 * pulse
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(*rose, 180), width=5)
    draw.rounded_rectangle((cx - 55, cy - 18, cx + 55, cy + 76), radius=18, fill=(8, 12, 25, 215), outline=(*gold, 220), width=3)
    draw.arc((cx - 42, cy - 75, cx + 42, cy + 32), start=200, end=340, fill=(*gold, 220), width=7)
    for idx, label in enumerate(("FILES", "PAY", "POST")):
        y = height * (0.36 + idx * 0.08)
        x = width * 0.13
        draw.rounded_rectangle((x, y, x + width * 0.18, y + 36), radius=14, fill=(255, 255, 255, 24), outline=(*(rose if idx == 1 else cyan), 125))
        draw.text((x + 16, y + 8), label, font=_font(int(width * 0.024), bold=True), fill=(255, 255, 255, 220))
        draw.line((x + width * 0.18, y + 18, cx - radius, cy), fill=(*(rose if idx == 1 else cyan), 95), width=2)


def _draw_approval_dashboard(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
) -> None:
    x0, y0 = width * 0.08, height * 0.34
    draw.rounded_rectangle((x0, y0, x0 + width * 0.55, y0 + height * 0.29), radius=24, fill=(2, 8, 18, 205), outline=(*cyan, 145), width=3)
    font = _font(int(width * 0.029), bold=True)
    draw.text((x0 + 26, y0 + 22), "HUMAN REVIEW", font=font, fill=(*gold, 240))
    for idx, label in enumerate(("NARROW JOB", "CLEAR PERMISSION", "APPROVE")):
        phase = min(1, max(0, progress * 1.35 - idx * 0.18))
        y = y0 + 70 + idx * 64
        draw.rounded_rectangle((x0 + 28, y, x0 + width * 0.47, y + 40), radius=16, fill=(255, 255, 255, 24), outline=(*cyan, 80))
        draw.text((x0 + 47, y + 10), label, font=_font(int(width * 0.024), bold=True), fill=(255, 255, 255, 225))
        if phase > 0.65:
            _draw_check(draw, x0 + width * 0.49, y + 20, gold)
    pulse = 0.5 + 0.5 * math.sin(progress * math.tau * 2)
    draw.ellipse((x0 + width * 0.38, y0 + 22, x0 + width * 0.48, y0 + 22 + width * 0.1), outline=(*rose, int(90 + 90 * pulse)), width=4)


def _draw_key_scene(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
) -> None:
    cx, cy = width * 0.39, height * 0.49
    draw.rounded_rectangle((cx - 58, cy - 82, cx + 58, cy + 82), radius=34, fill=(255, 255, 255, 22), outline=(*cyan, 150), width=3)
    key_angle = -0.45 + progress * 0.9
    kx = cx + math.cos(key_angle) * 120
    ky = cy + math.sin(key_angle) * 58
    draw.line((kx, ky, cx, cy), fill=(*gold, 230), width=8)
    draw.ellipse((kx - 26, ky - 26, kx + 26, ky + 26), outline=(*gold, 230), width=7)
    draw.rectangle((cx - 8, cy - 8, cx + 42, cy + 8), fill=(*gold, 230))
    for tooth in range(3):
        draw.rectangle((cx + 22 + tooth * 12, cy + 2, cx + 29 + tooth * 12, cy + 22), fill=(*gold, 220))
    for ring in range(4):
        r = 65 + ring * 36 + progress * 18
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(*rose, max(12, 90 - ring * 20)), width=2)


def _draw_hologram_core(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
    index: int,
) -> None:
    cx, cy = width // 2, int(height * 0.47)
    pulse = 0.75 + 0.25 * math.sin(progress * math.tau * 2)
    for ring in range(5):
        radius = int((95 + ring * 42) * pulse)
        alpha = max(18, 120 - ring * 20)
        bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
        draw.ellipse(bbox, outline=(*cyan, alpha), width=2 + ring % 2)
    for spoke in range(16):
        angle = spoke * math.tau / 16 + progress * math.tau + index
        length = 110 + 80 * (spoke % 3)
        x = cx + math.cos(angle) * length
        y = cy + math.sin(angle) * length * 0.58
        color = gold if spoke % 4 == 0 else cyan
        draw.line((cx, cy, x, y), fill=(*color, 96), width=2)
        size = 7 + (spoke % 4) * 3
        draw.ellipse((x - size, y - size, x + size, y + size), fill=(*(rose if spoke % 5 == 0 else color), 210))


def _draw_network_map(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
    index: int,
) -> None:
    rng = np.random.default_rng(1200 + index)
    nodes = []
    for _ in range(13):
        nodes.append((rng.uniform(0.12, 0.88) * width, rng.uniform(0.28, 0.72) * height))
    focus = (width * 0.52, height * 0.48)
    for x, y in nodes:
        phase = max(0, min(1, progress * 1.4 - abs(x - focus[0]) / width * 0.6))
        draw.line((x, y, focus[0], focus[1]), fill=(*cyan, int(35 + phase * 120)), width=2)
        r = 7 + phase * 7
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(*(gold if phase > 0.7 else rose), int(120 + phase * 90)))
    draw.ellipse((focus[0] - 38, focus[1] - 38, focus[0] + 38, focus[1] + 38), outline=(*gold, 230), width=4)


def _draw_glass_panels(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
    scene: Scene,
) -> None:
    labels = _panel_labels(scene)
    for idx, label in enumerate(labels):
        slide = _ease_out_back(min(1, max(0, progress * 1.4 - idx * 0.16)))
        x0 = width * (0.08 + idx * 0.29)
        y0 = height * (0.42 + math.sin(idx) * 0.035) + (1 - slide) * 140
        box = (x0, y0, x0 + width * 0.24, y0 + height * 0.16)
        color = (cyan, gold, rose)[idx % 3]
        draw.rounded_rectangle(box, radius=18, fill=(255, 255, 255, 26), outline=(*color, 170), width=2)
        draw.line((box[0] + 14, box[1] + 18, box[2] - 14, box[1] + 18), fill=(*color, 160), width=3)
        font = _font(int(width * 0.034), bold=True)
        for line_idx, line in enumerate(_wrap(draw, label, font, int(width * 0.18), max_lines=3)):
            draw.text((box[0] + 17, box[1] + 42 + line_idx * font.size * 1.08), line, font=font, fill=(255, 255, 255, 230))


def _draw_timeline_wave(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
) -> None:
    points = []
    for i in range(80):
        x = width * (0.08 + 0.84 * i / 79)
        y = height * (0.55 + 0.06 * math.sin(i * 0.32 + progress * math.tau * 2))
        points.append((x, y))
    draw.line(points, fill=(*cyan, 170), width=4)
    for marker in range(5):
        px = 0.1 + marker * 0.2 + progress * 0.04
        x = width * px
        y = height * (0.55 + 0.06 * math.sin(marker * 1.6 + progress * math.tau * 2))
        radius = 14 + 8 * math.sin(progress * math.tau + marker)
        color = gold if marker % 2 else rose
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*color, 190))
        draw.line((x, y + 28, x, y + height * 0.13), fill=(*color, 92), width=2)


def _draw_pressure_scene(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    progress: float,
) -> None:
    cx, cy = width // 2, int(height * 0.5)
    for card in range(5):
        shift = (card - 2) * width * 0.12
        y_shift = math.sin(progress * math.tau + card) * 22
        angle = (card - 2) * 0.08 + math.sin(progress * math.tau) * 0.03
        _draw_rotated_card(draw, cx + shift, cy + y_shift, width * 0.22, height * 0.12, angle, (cyan, gold, rose)[card % 3])
    radius = int(42 + progress * 420)
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(*gold, max(0, int(90 * (1 - progress)))), width=5)


def _draw_rotated_card(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    w: float,
    h: float,
    angle: float,
    color: tuple[int, int, int],
) -> None:
    pts = []
    for x, y in [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]:
        rx = x * math.cos(angle) - y * math.sin(angle) + cx
        ry = x * math.sin(angle) + y * math.cos(angle) + cy
        pts.append((rx, ry))
    draw.polygon(pts, fill=(255, 255, 255, 34), outline=(*color, 160))


def _draw_presenter(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    scene: Scene,
    index: int,
    progress: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
) -> None:
    scale = width / 720
    anchor_x = int(width * 0.78)
    hip_y = int(height * 0.69)
    bob = math.sin(progress * math.tau * 2) * 4 * scale
    talk = 0.35 + 0.65 * abs(math.sin(progress * math.tau * (5.5 + index % 3)))
    blink = math.sin(progress * math.tau * 5.7 + index) > 0.965
    gesture = _presenter_gesture(scene, index)

    glow_r = int(128 * scale)
    draw.ellipse(
        (anchor_x - glow_r, hip_y - int(370 * scale), anchor_x + glow_r, hip_y - int(120 * scale)),
        fill=(*cyan, 18),
        outline=(*cyan, 45),
        width=max(1, int(2 * scale)),
    )

    neck = (anchor_x, hip_y - int(246 * scale) + bob)
    shoulder_y = hip_y - int(224 * scale) + bob
    torso_top = hip_y - int(216 * scale) + bob
    torso_bottom = hip_y + int(38 * scale)
    body_w = int(152 * scale)

    # Shadow and torso.
    draw.ellipse((anchor_x - body_w, torso_bottom - 5, anchor_x + body_w, torso_bottom + 28 * scale), fill=(0, 0, 0, 80))
    draw.rounded_rectangle(
        (anchor_x - body_w // 2, torso_top, anchor_x + body_w // 2, torso_bottom),
        radius=int(34 * scale),
        fill=(11, 18, 35, 238),
        outline=(*cyan, 120),
        width=max(2, int(2 * scale)),
    )
    draw.polygon(
        [
            (anchor_x - body_w // 2 + 12 * scale, torso_top + 8 * scale),
            (anchor_x - 10 * scale, torso_top + 112 * scale),
            (anchor_x - 26 * scale, torso_bottom),
            (anchor_x - body_w // 2 + 20 * scale, torso_bottom),
        ],
        fill=(24, 35, 64, 225),
    )
    draw.polygon(
        [
            (anchor_x + body_w // 2 - 12 * scale, torso_top + 8 * scale),
            (anchor_x + 10 * scale, torso_top + 112 * scale),
            (anchor_x + 26 * scale, torso_bottom),
            (anchor_x + body_w // 2 - 20 * scale, torso_bottom),
        ],
        fill=(24, 35, 64, 225),
    )
    draw.line((anchor_x, torso_top + 20 * scale, anchor_x, torso_bottom - 8 * scale), fill=(*gold, 130), width=max(2, int(3 * scale)))
    draw.rounded_rectangle((anchor_x - 20 * scale, torso_top + 8 * scale, anchor_x + 20 * scale, torso_top + 44 * scale), radius=10, fill=(229, 190, 155, 255))

    left_shoulder = (anchor_x - int(76 * scale), shoulder_y)
    right_shoulder = (anchor_x + int(76 * scale), shoulder_y)
    if gesture == "point":
        left_hand = (width * 0.46, height * (0.48 + math.sin(progress * math.tau) * 0.015))
        right_hand = (anchor_x + int(74 * scale), hip_y - int(96 * scale))
        target = (width * 0.46, height * 0.49)
        draw.line((left_hand[0], left_hand[1], target[0], target[1]), fill=(*gold, 90), width=max(1, int(2 * scale)))
    elif gesture == "warn":
        left_hand = (anchor_x - int(118 * scale), hip_y - int(176 * scale) + math.sin(progress * math.tau * 2) * 12 * scale)
        right_hand = (anchor_x + int(104 * scale), hip_y - int(158 * scale))
    elif gesture == "approve":
        left_hand = (anchor_x - int(116 * scale), hip_y - int(118 * scale))
        right_hand = (anchor_x + int(112 * scale), hip_y - int(184 * scale) - math.sin(progress * math.tau * 2) * 12 * scale)
        _draw_check(draw, right_hand[0] + 26 * scale, right_hand[1] - 22 * scale, gold)
    else:
        left_hand = (anchor_x - int(112 * scale), hip_y - int(134 * scale) + math.sin(progress * math.tau) * 9 * scale)
        right_hand = (anchor_x + int(112 * scale), hip_y - int(134 * scale) - math.sin(progress * math.tau) * 9 * scale)

    _draw_arm(draw, left_shoulder, left_hand, scale, (229, 190, 155), cyan)
    _draw_arm(draw, right_shoulder, right_hand, scale, (229, 190, 155), cyan)

    # Head, hair, face.
    head_cx = anchor_x
    head_cy = int(hip_y - 302 * scale + bob)
    head_rx = int(49 * scale)
    head_ry = int(58 * scale)
    draw.ellipse((head_cx - head_rx, head_cy - head_ry, head_cx + head_rx, head_cy + head_ry), fill=(232, 190, 153, 255), outline=(*gold, 80), width=max(1, int(2 * scale)))
    draw.pieslice((head_cx - head_rx - 4, head_cy - head_ry - 12, head_cx + head_rx + 4, head_cy + 18 * scale), start=180, end=360, fill=(26, 31, 48, 255))
    draw.polygon(
        [
            (head_cx - head_rx + 4 * scale, head_cy - head_ry + 26 * scale),
            (head_cx - 10 * scale, head_cy - head_ry - 22 * scale),
            (head_cx + head_rx - 5 * scale, head_cy - head_ry + 24 * scale),
            (head_cx + head_rx - 8 * scale, head_cy - head_ry + 2 * scale),
        ],
        fill=(31, 38, 59, 255),
    )
    eye_y = head_cy - int(8 * scale)
    for side in (-1, 1):
        eye_x = head_cx + side * int(18 * scale)
        if blink:
            draw.line((eye_x - 7 * scale, eye_y, eye_x + 7 * scale, eye_y), fill=(22, 23, 28, 230), width=max(2, int(3 * scale)))
        else:
            draw.ellipse((eye_x - 5 * scale, eye_y - 4 * scale, eye_x + 5 * scale, eye_y + 4 * scale), fill=(17, 22, 33, 255))
            draw.ellipse((eye_x + 1 * scale, eye_y - 2 * scale, eye_x + 3 * scale, eye_y), fill=(255, 255, 255, 220))
    draw.arc((head_cx - 9 * scale, head_cy + 2 * scale, head_cx + 9 * scale, head_cy + 23 * scale), start=250, end=300, fill=(117, 82, 66, 210), width=max(1, int(2 * scale)))
    mouth_w = int((18 + talk * 14) * scale)
    mouth_h = int((5 + talk * 14) * scale)
    draw.ellipse((head_cx - mouth_w // 2, head_cy + 30 * scale - mouth_h // 2, head_cx + mouth_w // 2, head_cy + 30 * scale + mouth_h // 2), fill=(74, 24, 35, 230))
    draw.arc((head_cx - 30 * scale, head_cy + 18 * scale, head_cx + 30 * scale, head_cy + 52 * scale), start=18, end=162, fill=(255, 220, 210, 120), width=max(1, int(2 * scale)))


def _presenter_gesture(scene: Scene, index: int) -> str:
    text = f"{scene.narration} {scene.onscreen_text}".lower()
    if any(word in text for word in ("risk", "access", "mistake", "keys")):
        return "warn"
    if any(word in text for word in ("review", "manager", "clear", "approve", "rules")):
        return "approve"
    if any(word in text for word in ("look", "this", "worker", "agent", "task")):
        return "point"
    return "explain" if index % 2 else "point"


def _draw_arm(
    draw: ImageDraw.ImageDraw,
    shoulder: tuple[float, float],
    hand: tuple[float, float],
    scale: float,
    skin: tuple[int, int, int],
    accent: tuple[int, int, int],
) -> None:
    elbow = ((shoulder[0] + hand[0]) / 2, (shoulder[1] + hand[1]) / 2 + 24 * scale)
    draw.line((shoulder[0], shoulder[1], elbow[0], elbow[1], hand[0], hand[1]), fill=(20, 31, 55, 245), width=max(8, int(17 * scale)), joint="curve")
    draw.line((shoulder[0], shoulder[1], elbow[0], elbow[1], hand[0], hand[1]), fill=(*accent, 80), width=max(2, int(4 * scale)), joint="curve")
    r = int(13 * scale)
    draw.ellipse((hand[0] - r, hand[1] - r, hand[0] + r, hand[1] + r), fill=(*skin, 255), outline=(*accent, 110), width=max(1, int(2 * scale)))


def _draw_check(draw: ImageDraw.ImageDraw, x: float, y: float, color: tuple[int, int, int]) -> None:
    draw.line((x - 12, y, x - 3, y + 10, x + 16, y - 14), fill=(*color, 230), width=4)


def _draw_cursor(draw: ImageDraw.ImageDraw, x: float, y: float, color: tuple[int, int, int]) -> None:
    draw.polygon([(x, y), (x + 28, y + 62), (x + 8, y + 52), (x - 8, y + 78)], fill=(*color, 220), outline=(0, 0, 0, 120))


def _draw_real_presenter(
    img: Image.Image,
    width: int,
    height: int,
    presenter_asset: str,
    progress: float,
    local_time: float,
    index: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    shot: str,
    scene: Scene,
) -> None:
    presenter = _load_presenter_asset(presenter_asset)
    performance = _animate_presenter_rig(presenter, scene, progress, local_time, index, shot)
    talk = _presenter_talk_intensity(scene, local_time, progress)
    body_angle = math.sin(progress * math.tau * 0.72 + index * 0.8) * (1.25 + 0.7 * talk)
    if shot in {"hero_closeup", "character_closeup", "impact_reveal"}:
        body_angle *= 1.35
    performance = performance.rotate(body_angle, resample=Image.Resampling.BICUBIC, expand=True)
    scale = height * 0.62 / presenter.height
    if index % 3 == 1:
        scale *= 0.96
    if shot in {"presenter_closeup", "hero_closeup", "impact_reveal", "character_closeup"}:
        scale *= 1.22
    if shot == "final_hero":
        scale *= 1.08
    if shot == "establishing":
        scale *= 0.78
    scale *= 1.0 + 0.022 * math.sin(progress * math.tau * 0.95 + index) + 0.012 * talk
    target_w = int(performance.width * scale)
    target_h = int(performance.height * scale)
    resized = performance.resize((target_w, target_h), Image.Resampling.LANCZOS)

    sway = math.sin(progress * math.tau * 1.2 + index) * 18 + math.sin(local_time * 5.0 + index) * 5 * talk
    if shot in {"hero_closeup", "impact_reveal", "character_closeup"}:
        x_base = 0.5
        y_base = 0.27
    elif shot == "final_hero":
        x_base = 0.53
        y_base = 0.34
    elif shot == "establishing":
        x_base = 0.62
        y_base = 0.46
    else:
        x_base = 0.58
        y_base = 0.38
    x = int((width * x_base) + sway)
    y = int((height * y_base) + math.sin(progress * math.tau * 1.7 + index) * 12 + math.sin(local_time * 7.0) * 4 * talk)
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow, "RGBA")
    shadow_draw.ellipse((x + target_w * 0.1, y + target_h * 0.9, x + target_w * 0.88, y + target_h * 1.02), fill=(0, 0, 0, 105))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    base = img.convert("RGBA")
    base.alpha_composite(shadow)

    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow, "RGBA")
    glow_draw.ellipse((x - 34, y + 30, x + target_w + 42, y + target_h * 0.78), outline=(*cyan, 54), width=4)
    glow_draw.arc((x - 54, y + 8, x + target_w + 58, y + target_h * 0.72), start=210, end=330, fill=(*gold, 70), width=3)
    glow_draw.line((x + target_w * 0.06, y + target_h * 0.08, x + target_w * 0.06, y + target_h * 0.78), fill=(*cyan, 85), width=5)
    glow_draw.line((x + target_w * 0.9, y + target_h * 0.16, x + target_w * 0.86, y + target_h * 0.74), fill=(*gold, 56), width=4)
    if isinstance(scene, ScenePlan) and scene.character.get("gesture") in {"hand_forward", "raise_hand", "point_to_hologram"}:
        glow_draw.line((x + target_w * 0.18, y + target_h * 0.48, width * 0.42, height * 0.52), fill=(*gold, 80), width=5)
        glow_draw.ellipse((width * 0.42 - 20, height * 0.52 - 20, width * 0.42 + 20, height * 0.52 + 20), outline=(*gold, 130), width=4)
    glow = glow.filter(ImageFilter.GaussianBlur(2))
    base.alpha_composite(glow)
    base.alpha_composite(resized, dest=(x, y))

    img.paste(base.convert("RGB"))


@lru_cache(maxsize=8)
def _load_presenter_asset(path: str) -> Image.Image:
    return Image.open(path).convert("RGBA")


def _animate_presenter_rig(
    presenter: Image.Image,
    scene: Scene,
    progress: float,
    local_time: float,
    index: int,
    shot: str,
) -> Image.Image:
    rig = presenter.copy()
    width, height = rig.size
    bbox = rig.getbbox() or (0, 0, width, height)
    talk = _presenter_talk_intensity(scene, local_time, progress)
    blink = _presenter_blink(progress, local_time, index)
    head_angle = math.sin(progress * math.tau * 0.8 + index * 0.9) * (2.8 + 1.2 * talk)
    if shot in {"hero_closeup", "impact_reveal", "final_hero", "character_closeup"}:
        head_angle *= 1.35
    head_dx = int(math.sin(progress * math.tau * 1.15 + index) * 7)
    head_dy = int(math.sin(progress * math.tau * 2.0 + index) * 3 - talk * 3)

    body = _presenter_body_layer(rig, bbox, progress, index, talk, shot)
    head_box = _presenter_head_box(width, height, bbox)
    head = rig.crop(head_box)
    head = _draw_face_performance(head, talk, blink, progress, index)
    head = _soften_alpha_edges(head, 0.8)
    rotated = head.rotate(head_angle, resample=Image.Resampling.BICUBIC, expand=True)

    canvas = Image.new("RGBA", rig.size, (0, 0, 0, 0))
    canvas.alpha_composite(body)
    paste_x = head_box[0] - (rotated.width - head.width) // 2 + head_dx
    paste_y = head_box[1] - (rotated.height - head.height) // 2 + head_dy
    canvas.alpha_composite(rotated, (paste_x, paste_y))
    return _apply_presenter_micro_warp(canvas, progress, talk, index)


def _presenter_head_box(width: int, height: int, bbox: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    left = max(0, int(width * 0.25))
    top = max(0, int(height * 0.14))
    right = min(width, int(width * 0.78))
    bottom = min(height, int(height * 0.48))
    if bbox[1] > 0:
        top = max(0, bbox[1] - int(height * 0.035))
    return left, top, right, bottom


def _presenter_body_layer(
    presenter: Image.Image,
    bbox: tuple[int, int, int, int],
    progress: float,
    index: int,
    talk: float,
    shot: str,
) -> Image.Image:
    body = presenter.copy()
    width, height = body.size
    head_box = _presenter_head_box(width, height, bbox)
    mask = Image.new("L", body.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse(
        (
            head_box[0] + width * 0.015,
            head_box[1] + height * 0.01,
            head_box[2] - width * 0.025,
            head_box[3] - height * 0.03,
        ),
        fill=245,
    )
    mask = mask.filter(ImageFilter.GaussianBlur(16))
    alpha = body.getchannel("A")
    alpha_arr = np.asarray(alpha).astype(np.float32)
    erase_arr = np.asarray(mask).astype(np.float32) / 255.0
    alpha_arr *= 1.0 - erase_arr * 0.96
    body.putalpha(Image.fromarray(np.uint8(np.clip(alpha_arr, 0, 255))))

    breath = 1.0 + 0.014 * math.sin(progress * math.tau * 1.7 + index) + 0.006 * talk
    shoulder_sway = math.sin(progress * math.tau * 1.05 + index) * (9 + 7 * talk)
    lean = math.sin(progress * math.tau * 0.72 + index * 0.6) * (0.018 + 0.01 * talk)
    if shot in {"hero_closeup", "character_closeup", "impact_reveal"}:
        shoulder_sway *= 1.45
        lean *= 1.25
    resized = body.resize((width, int(height * breath)), Image.Resampling.BICUBIC)
    result = Image.new("RGBA", body.size, (0, 0, 0, 0))
    result.alpha_composite(resized.crop((0, 0, min(width, resized.width), min(height, resized.height))), (int(shoulder_sway * 0.18), 0))
    animated = result.transform(
        result.size,
        Image.Transform.AFFINE,
        (1, lean, shoulder_sway, 0.003 * math.sin(progress * math.tau + index), 1, 0),
        resample=Image.Resampling.BICUBIC,
    )
    return _draw_body_gesture_shadows(animated, progress, talk, index, shot)


def _draw_body_gesture_shadows(
    body: Image.Image,
    progress: float,
    talk: float,
    index: int,
    shot: str,
) -> Image.Image:
    animated = body.copy()
    draw = ImageDraw.Draw(animated, "RGBA")
    width, height = animated.size
    if talk <= 0.04 and shot not in {"hero_closeup", "character_closeup", "final_hero"}:
        return animated
    pulse = 0.5 + 0.5 * math.sin(progress * math.tau * 2.2 + index)
    alpha = int(34 + 48 * max(talk, pulse * 0.45))
    shoulder_y = height * 0.48
    left_x = width * (0.28 + 0.018 * math.sin(progress * math.tau + index))
    right_x = width * (0.72 + 0.018 * math.cos(progress * math.tau + index))
    draw.arc((left_x - 34, shoulder_y - 28, left_x + 86, shoulder_y + 122), start=210, end=330, fill=(255, 255, 255, alpha), width=max(2, int(width * 0.008)))
    draw.arc((right_x - 86, shoulder_y - 28, right_x + 34, shoulder_y + 122), start=210, end=330, fill=(255, 255, 255, alpha // 2), width=max(2, int(width * 0.007)))
    return animated


def _draw_face_performance(
    head: Image.Image,
    talk: float,
    blink: bool,
    progress: float,
    index: int,
) -> Image.Image:
    animated = head.copy()
    draw = ImageDraw.Draw(animated, "RGBA")
    w, h = animated.size
    mouth_open = talk * (0.45 + 0.55 * abs(math.sin(progress * math.tau * 11 + index)))
    mouth_x = w * 0.51 + math.sin(progress * math.tau * 1.7 + index) * w * 0.008
    mouth_y = h * 0.62
    mouth_w = w * (0.092 + 0.035 * mouth_open)
    mouth_h = h * (0.014 + 0.035 * mouth_open)
    if talk > 0.05:
        draw.ellipse(
            (mouth_x - mouth_w / 2, mouth_y - mouth_h / 2, mouth_x + mouth_w / 2, mouth_y + mouth_h / 2),
            fill=(58, 18, 24, int(112 + 105 * mouth_open)),
        )
        draw.arc(
            (mouth_x - mouth_w / 2, mouth_y - mouth_h * 0.7, mouth_x + mouth_w / 2, mouth_y + mouth_h * 0.9),
            start=0,
            end=180,
            fill=(255, 232, 218, int(75 + 70 * mouth_open)),
            width=max(1, int(w * 0.006)),
        )
    else:
        draw.arc(
            (mouth_x - mouth_w / 2, mouth_y - h * 0.015, mouth_x + mouth_w / 2, mouth_y + h * 0.018),
            start=8,
            end=172,
            fill=(72, 28, 34, 90),
            width=max(1, int(w * 0.004)),
        )

    if blink:
        skin = (214, 155, 120, 205)
        for ex in (w * 0.39, w * 0.61):
            ey = h * 0.42
            draw.rounded_rectangle((ex - w * 0.045, ey - h * 0.01, ex + w * 0.045, ey + h * 0.012), radius=4, fill=skin)
            draw.line((ex - w * 0.04, ey + h * 0.006, ex + w * 0.04, ey + h * 0.006), fill=(39, 28, 24, 180), width=max(1, int(w * 0.006)))
    else:
        glint_shift = math.sin(progress * math.tau * 1.3 + index) * w * 0.006
        for ex in (w * 0.39, w * 0.61):
            ey = h * 0.42
            draw.ellipse((ex + glint_shift, ey - h * 0.004, ex + glint_shift + w * 0.012, ey + h * 0.008), fill=(255, 255, 255, 150))
    return animated


def _soften_alpha_edges(layer: Image.Image, radius: float) -> Image.Image:
    alpha = layer.getchannel("A").filter(ImageFilter.GaussianBlur(radius))
    result = layer.copy()
    result.putalpha(alpha)
    return result


def _apply_presenter_micro_warp(presenter: Image.Image, progress: float, talk: float, index: int) -> Image.Image:
    width, height = presenter.size
    shear = math.sin(progress * math.tau * 0.65 + index) * 0.012
    shift = math.sin(progress * math.tau * 1.1 + index) * (2.5 + 2.5 * talk)
    warped = presenter.transform(
        presenter.size,
        Image.Transform.AFFINE,
        (1, shear, shift, 0.002 * math.sin(progress * math.tau + index), 1, 0),
        resample=Image.Resampling.BICUBIC,
    )
    return warped.crop((0, 0, width, height))


def _presenter_talk_intensity(scene: Scene, local_time: float, progress: float) -> float:
    if not isinstance(scene, ScenePlan):
        return 0.45 + 0.45 * abs(math.sin(progress * math.tau * 4))
    words = max(1, len(scene.caption_words or scene.narration.split()))
    estimated_voice_duration = min(scene.duration_seconds - 0.25, max(1.2, 0.28 * words + 0.9))
    if local_time < 0.08 or local_time > estimated_voice_duration + 0.18:
        return 0.0
    attack = min(1.0, max(0.0, (local_time - 0.08) / 0.2))
    release = min(1.0, max(0.0, (estimated_voice_duration + 0.18 - local_time) / 0.35))
    syllable = 0.52 + 0.48 * abs(math.sin(local_time * 18.5 + len(scene.narration)))
    return max(0.0, min(1.0, attack * release * syllable))


def _presenter_blink(progress: float, local_time: float, index: int) -> bool:
    phase = (local_time * 0.8 + index * 0.23) % 3.4
    return phase > 3.28 or math.sin(progress * math.tau * 5.7 + index) > 0.985


def _draw_vfx_overlay(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    scene: ScenePlan,
    index: int,
    progress: float,
    local_time: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    shot: str,
) -> None:
    layers = set(scene.vfx)
    theme = str(scene.visual_metaphor.get("theme", ""))
    if "scanlines" in layers or "macro_scanlines" in layers:
        for y in range(0, height, 22):
            alpha = 18 if y % 44 else 32
            draw.line((0, y + int(progress * 18) % 22, width, y + int(progress * 18) % 22), fill=(*cyan, alpha), width=1)
    if "lens_flare" in layers:
        _draw_lens_flare(draw, width * (0.12 + 0.68 * progress), height * 0.22, cyan, gold)
    if "volumetric_beams" in layers:
        for beam in range(4):
            x = width * (0.18 + beam * 0.19 + math.sin(progress * math.tau + beam) * 0.025)
            draw.line((x, 0, x + width * 0.12, height), fill=(*cyan, 26), width=9)
    if "streak_lines" in layers or shot in {"fast_montage", "task_cutaway"}:
        for streak in range(14):
            y = height * (0.28 + (streak * 0.047 + progress * 0.85) % 0.46)
            x = width * ((progress * 1.6 + streak * 0.13) % 1.1 - 0.1)
            color = (cyan, gold, rose)[streak % 3]
            draw.line((x, y, x + width * 0.28, y - height * 0.035), fill=(*color, 78), width=3)
    if "glitch" in layers or theme == "risk":
        intensity = max(event_intensity(scene, local_time, "screen_glitch", 0.45), 0.18 if theme == "risk" else 0.0)
        if intensity:
            _draw_glitch_overlay(draw, width, height, rose, cyan, intensity, index, local_time)
    if "electric_arcs" in layers:
        arc_intensity = max(event_intensity(scene, local_time, "electric_arc", 0.45), 0.25 if theme in {"risk", "access"} else 0)
        if arc_intensity:
            _draw_electric_arcs(draw, width, height, rose, gold, progress, arc_intensity)
    if "shield_pulse" in layers:
        _draw_shield_pulse(draw, width, height, cyan, gold, progress)
    if "energy_pulse" in layers or "bass_hit_flash" in layers:
        pulse = max(event_intensity(scene, local_time, "energy_pulse", 0.45), event_intensity(scene, local_time, "text_punch_zoom", 0.25))
        if pulse:
            r = width * (0.18 + pulse * 0.36)
            cx, cy = width * 0.43, height * 0.5
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(*gold, int(150 * pulse)), width=max(2, int(7 * pulse)))
    if "red_flash" in layers and event_intensity(scene, local_time, "risk_warning_red_flash", 0.3):
        draw.rectangle((0, 0, width, height), fill=(*rose, 46))


def _draw_retention_overlay(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    scene: ScenePlan,
    local_time: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
) -> None:
    for event in scene.retention_events:
        event_time = float(event.get("time", 0.0))
        name = str(event.get("event", ""))
        distance = abs(local_time - event_time)
        if distance > 0.18:
            continue
        intensity = 1 - distance / 0.18
        if name in {"cold_open_impact", "pattern_interrupt"}:
            draw.rectangle((0, 0, width, height), fill=(255, 255, 255, int(32 * intensity)))
            draw.rectangle((0, 0, width, height * 0.08), fill=(0, 0, 0, int(150 * intensity)))
            draw.rectangle((0, height * 0.92, width, height), fill=(0, 0, 0, int(150 * intensity)))
        elif name == "sound_drop":
            draw.rectangle((0, 0, width, height), fill=(0, 0, 0, int(92 * intensity)))
            draw.line((width * 0.12, height * 0.5, width * 0.88, height * 0.5), fill=(*rose, int(190 * intensity)), width=5)
        elif name in {"vfx_reveal", "hero_cta"}:
            x = width * 0.5
            y = height * 0.5
            r = width * (0.18 + 0.4 * intensity)
            draw.ellipse((x - r, y - r, x + r, y + r), outline=(*gold, int(160 * intensity)), width=8)
        elif name == "visual_metaphor_cutaway":
            draw.rectangle((width * 0.04, height * 0.33, width * 0.68, height * 0.66), outline=(*cyan, int(150 * intensity)), width=5)


def _draw_lens_flare(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
) -> None:
    for idx, radius in enumerate((22, 54, 104)):
        alpha = max(12, 68 - idx * 20)
        color = gold if idx == 0 else cyan
        draw.ellipse((x - radius, y - radius * 0.36, x + radius, y + radius * 0.36), outline=(*color, alpha), width=2)
    draw.line((x - 160, y, x + 190, y), fill=(*gold, 42), width=3)


def _draw_glitch_overlay(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    rose: tuple[int, int, int],
    cyan: tuple[int, int, int],
    intensity: float,
    index: int,
    local_time: float,
) -> None:
    rng = np.random.default_rng(int(index * 1000 + local_time * 90))
    for _ in range(int(5 + intensity * 12)):
        y = rng.uniform(0.16, 0.82) * height
        h = rng.uniform(3, 16)
        x_shift = rng.uniform(-0.08, 0.08) * width * intensity
        color = rose if rng.random() > 0.45 else cyan
        draw.rectangle((x_shift, y, width + x_shift, y + h), fill=(*color, int(18 + intensity * 70)))


def _draw_electric_arcs(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    rose: tuple[int, int, int],
    gold: tuple[int, int, int],
    progress: float,
    intensity: float,
) -> None:
    cx, cy = width * 0.42, height * 0.5
    for arc in range(7):
        angle = arc * math.tau / 7 + progress * math.tau * 0.7
        points = []
        for step in range(5):
            r = width * (0.17 + step * 0.025)
            jitter = math.sin(progress * math.tau * 8 + arc + step) * width * 0.012
            points.append((cx + math.cos(angle) * (r + jitter), cy + math.sin(angle) * (r + jitter)))
        draw.line(points, fill=(*(rose if arc % 2 else gold), int(95 + 120 * intensity)), width=3)


def _draw_shield_pulse(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    progress: float,
) -> None:
    cx, cy = width * 0.44, height * 0.5
    scale = 1 + 0.08 * math.sin(progress * math.tau * 2)
    pts = [
        (cx, cy - 118 * scale),
        (cx + 90 * scale, cy - 50 * scale),
        (cx + 68 * scale, cy + 88 * scale),
        (cx, cy + 140 * scale),
        (cx - 68 * scale, cy + 88 * scale),
        (cx - 90 * scale, cy - 50 * scale),
    ]
    draw.polygon(pts, fill=(*cyan, 16), outline=(*gold, 118))


def _draw_kinetic_text(
    draw: ImageDraw.ImageDraw,
    scene: Scene,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    ease: float,
    index: int,
    local_time: float,
) -> None:
    headline_font = _font(int(width * 0.092), bold=True)
    keyword_font = _font(int(width * 0.033), bold=True)
    label_font = _font(int(width * 0.028), bold=True)

    planned_headline = scene.caption_plan.get("headline", "") if isinstance(scene, ScenePlan) and scene.caption_plan else ""
    headline = _display_text(planned_headline or scene.onscreen_text or scene.visual_style, 54)
    lines = _wrap(draw, headline, headline_font, int(width * 0.56), max_lines=4)
    block_h = len(lines) * int(headline_font.size * 1.0)
    y = int(height * 0.19 - block_h * 0.04)
    panel_left = int(width * 0.055)
    panel_top = max(int(height * 0.14), y - int(height * 0.035))
    panel_right = int(width * 0.66)
    panel_bottom = y + block_h + int(height * 0.06)
    draw.rounded_rectangle(
        (panel_left, panel_top, panel_right, panel_bottom),
        radius=28,
        fill=(0, 0, 0, 92),
        outline=(*cyan, 80),
        width=2,
    )
    for idx, line in enumerate(lines):
        x = int(width * (0.08 - (1 - ease) * 0.065 + idx * 0.012))
        shadow = 4
        draw.text((x + shadow, y + shadow), line, font=headline_font, fill=(0, 0, 0, 150))
        draw.text((x, y), line, font=headline_font, fill=(*(gold if idx == 0 else (255, 255, 255)), 255))
        y += int(headline_font.size * 1.0)
    underline_width = int(width * 0.62 * ease)
    draw.line((width * 0.08, y + 10, width * 0.08 + min(underline_width, width * 0.52), y + 10), fill=(*rose, 220), width=5)
    _draw_center_keyword_chips(draw, scene, width, height, cyan, gold, rose, keyword_font, ease)
    if isinstance(scene, ScenePlan):
        _draw_dynamic_caption(draw, scene, width, height, cyan, gold, rose, local_time)
    draw.text((width * 0.84, height * 0.955), f"{index + 1:02d}", font=label_font, fill=(*gold, 180))


def _draw_dynamic_caption(
    draw: ImageDraw.ImageDraw,
    scene: ScenePlan,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    local_time: float,
) -> None:
    words, group_progress = caption_for_time(scene, local_time)
    if not words:
        return
    phrase = " ".join(word.upper() for word, _ in words)
    font_size = int(width * 0.052)
    font = _font(font_size, bold=True)
    while draw.textlength(phrase, font=font) > width * 0.74 and font_size > int(width * 0.036):
        font_size -= 3
        font = _font(font_size, bold=True)
    total_width = draw.textlength(phrase, font=font)
    x = (width - total_width) / 2
    y = height * 0.78
    alpha = int(120 + 135 * min(1.0, group_progress * 2.0))
    draw.rounded_rectangle((x - 24, y - 18, x + total_width + 24, y + font.size + 22), radius=22, fill=(0, 0, 0, 120), outline=(*cyan, 90), width=2)
    draw.text((x, y), phrase, font=font, fill=(255, 255, 255, alpha))
    if any(highlighted for _, highlighted in words):
        draw.line((x, y + font.size + 7, x + total_width, y + font.size + 7), fill=(*gold, alpha), width=5)


def _draw_center_keyword_chips(
    draw: ImageDraw.ImageDraw,
    scene: Scene,
    width: int,
    height: int,
    cyan: tuple[int, int, int],
    gold: tuple[int, int, int],
    rose: tuple[int, int, int],
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    ease: float,
) -> None:
    keywords = _extract_keywords(scene)
    positions = [
        (0.12, 0.68, cyan),
        (0.34, 0.65, gold),
        (0.16, 0.58, rose),
    ]
    for idx, keyword in enumerate(keywords[:3]):
        px, py, color = positions[idx]
        alpha = int(45 + 125 * min(1, max(0, ease * 1.3 - idx * 0.18)))
        text_w = draw.textlength(keyword, font=font)
        x = width * px
        y = height * py
        draw.rounded_rectangle((x - 16, y - 12, x + text_w + 18, y + font.size + 14), radius=18, fill=(0, 0, 0, 92), outline=(*color, alpha), width=2)
        draw.text((x, y), keyword, font=font, fill=(255, 255, 255, 210))


def _panel_labels(scene: Scene) -> list[str]:
    if isinstance(scene, ScenePlan) and scene.caption_plan.get("ui_labels"):
        return [str(label).title() for label in scene.caption_plan.get("ui_labels", [])[:3]]
    words = [word.strip(".,:;!?") for word in scene.onscreen_text.split() if len(word.strip(".,:;!?")) > 2]
    if len(words) >= 3:
        return [" ".join(words[:2]), " ".join(words[2:4]), " ".join(words[4:6]) or "Next move"]
    return ["Time saved", "Money moved", "New behavior"]


def _extract_keywords(scene: Scene | ScenePlan) -> list[str]:
    if isinstance(scene, ScenePlan):
        return keyword_chips(scene)
    text = f"{scene.onscreen_text} {scene.narration}".lower()
    priority = [
        ("agent", "AI AGENT"),
        ("intern", "AI AGENT"),
        ("browser", "BROWSER TAB"),
        ("login", "LOGIN"),
        ("worker", "WORKER"),
        ("task", "TASKS"),
        ("research", "RESEARCH"),
        ("admin", "ADMIN"),
        ("access", "ACCESS"),
        ("permission", "PERMISSIONS"),
        ("mistake", "MISTAKES"),
        ("review", "HUMAN REVIEW"),
        ("manager", "MANAGER"),
        ("keys", "THE KEYS"),
        ("clear", "CLEAR RULES"),
        ("boring", "BORING WORK"),
    ]
    result: list[str] = []
    for needle, label in priority:
        if needle in text and label not in result:
            result.append(label)
    blocked = {"YOUR", "THIS", "THAT", "WITH", "WHAT", "WHEN", "HUMAN", "NEW", "NOT"}
    words = [
        word.strip(".,:;!?").upper()
        for word in scene.onscreen_text.split()
        if len(word.strip(".,:;!?")) > 3 and word.strip(".,:;!?").upper() not in blocked
    ]
    for word in words:
        if word not in result:
            result.append(word)
    return result[:3] or ["WATCH THIS", "FAST CONTEXT", "NO HYPE"]


def _ease_out_cubic(x: float) -> float:
    return 1 - (1 - x) ** 3


def _ease_out_back(x: float) -> float:
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def _font(size: int, *, bold: bool) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in font_candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    *,
    max_lines: int,
) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len(" ".join(words)) > len(" ".join(lines)):
        lines[-1] = lines[-1].rstrip(". ") + "..."
    return lines or [text[:30]]


def _display_text(value: str, max_len: int) -> str:
    value = clean_text(value, max_len)
    value = re.sub(r"^[^A-Za-z0-9]+", "", value).strip()
    return value or "Watch this"


def _save_thumbnail(scene: Scene, thumbnail_path: Path, settings: Settings) -> None:
    frame = _frame_for_scene(
        scene,
        0,
        max(0.34, scene.duration_seconds * 0.34),
        settings.video_width,
        settings.video_height,
        settings.presenter_enabled,
        str(settings.presenter_asset),
        settings,
    )
    Image.fromarray(frame).save(thumbnail_path, quality=94)
