from __future__ import annotations


VFX_PRESETS: dict[str, list[str]] = {
    "hologram": ["scanlines", "hologram_glow", "flicker", "chromatic_aberration"],
    "danger": ["red_flash", "glitch", "camera_shake", "alarm_particles", "electric_arcs"],
    "hero": ["lens_flare", "rim_light", "floating_particles", "volumetric_beams"],
    "speed": ["motion_blur", "streak_lines", "whoosh_trails", "spark_hits"],
    "reveal": ["light_sweep", "energy_pulse", "bass_hit_flash", "depth_fog"],
    "control": ["shield_pulse", "audit_scan", "clean_glow", "approval_spark"],
}


def vfx_for(purpose: str, metaphor_theme: str, shot_type: str) -> list[str]:
    layers: list[str] = []
    layers.extend(VFX_PRESETS["hero"])

    if metaphor_theme in {"risk", "access"} or purpose == "warning":
        layers.extend(VFX_PRESETS["danger"])
    elif metaphor_theme == "speed" or shot_type in {"whip_pan", "fast_montage"}:
        layers.extend(VFX_PRESETS["speed"])
    elif metaphor_theme == "control":
        layers.extend(VFX_PRESETS["control"])
    elif purpose in {"reveal", "cta"}:
        layers.extend(VFX_PRESETS["reveal"])
    else:
        layers.extend(VFX_PRESETS["hologram"])

    if shot_type in {"impact_reveal", "hero_closeup"}:
        layers.extend(["bass_hit_flash", "subtle_camera_shock"])
    if shot_type == "ui_macro":
        layers.extend(["macro_scanlines", "cursor_light_trail"])

    deduped: list[str] = []
    for layer in layers:
        if layer not in deduped:
            deduped.append(layer)
    return deduped
