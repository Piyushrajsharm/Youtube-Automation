from __future__ import annotations

from .models import ScenePlan


def build_cinematic_prompt(scene: ScenePlan, topic: str) -> str:
    skills = ", ".join(scene.selected_skills)
    skill_lines = "\n".join(f"- {fragment}" for fragment in scene.skill_profile.get("prompt_fragments", []))
    lighting = ", ".join(f"{key}: {value}" for key, value in scene.lighting.items())
    vfx = ", ".join(scene.vfx[:10])
    foreground = ", ".join(scene.foreground_elements[:8])
    shot_sequence = "; ".join(
        f"{shot.get('start')}-{shot.get('end')}s {shot.get('shot')} ({shot.get('camera')})"
        for shot in scene.shot_sequence[:5]
    )
    broll = ", ".join(str(clip.get("type")) for clip in scene.broll_clips[:4])
    layers = ", ".join(str(layer.get("type")) for layer in scene.layers)
    return (
        f"Create a vertical cinematic shot for a YouTube Short.\n"
        f"Topic: {topic}\n"
        f"Scene purpose: {scene.purpose}\n"
        f"Scene type: {scene.scene_type}\n"
        f"Emotion: {scene.emotion}\n"
        f"Location: {scene.location}\n"
        f"Shot type: {scene.shot_types[0] if scene.shot_types else 'hero_closeup'}\n"
        f"Camera: {scene.camera_motion}\n"
        f"Lighting: {lighting}\n"
        f"Foreground: {foreground}\n"
        f"Midground: {scene.midground}\n"
        f"Background: {scene.background}\n"
        f"Atmosphere: {scene.atmosphere}\n"
        f"VFX: {vfx}\n"
        f"Camera emotion: {scene.camera_emotion}\n"
        f"Shot sequence: {shot_sequence}\n"
        f"B-roll micro-scenes: {broll}\n"
        f"Depth layers: {layers}\n"
        f"Selected cinematic skills: {skills}\n"
        f"Apply these skill instructions:\n{skill_lines}\n"
        f"Narration beat: {scene.narration}\n"
        f"Composition rule: clear subject, readable central keywords, no copyrighted characters, no real logos, original design only."
    )
