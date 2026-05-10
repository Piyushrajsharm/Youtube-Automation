from __future__ import annotations

import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def render_volumetric_fog(
    width: int,
    height: int,
    light_sources: list[dict],
    fog_density: float = 0.15,
    time: float = 0.0,
) -> Image.Image:
    fog = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    fog_arr = np.zeros((height, width, 4), dtype=np.float32)

    for light in light_sources:
        lx = light.get("x", width * 0.5)
        ly = light.get("y", height * 0.2)
        color = light.get("color", (100, 200, 255))
        intensity = light.get("intensity", 0.6)
        radius = light.get("radius", width * 0.4)

        yy, xx = np.mgrid[0:height, 0:width]
        dist = np.sqrt((xx - lx) ** 2 + (yy - ly) ** 2)
        falloff = np.exp(-dist / (radius * 0.5))

        rays = np.ones_like(dist)
        for ray_idx in range(8):
            angle = ray_idx * math.tau / 8 + time * 0.15
            ray_mask = np.abs(
                np.arctan2(yy - ly, xx - lx) - angle
            ) < 0.12
            rays += ray_mask * 0.3 * np.exp(-dist / (radius * 0.7))

        fog_contribution = falloff * rays * fog_density * intensity
        for c in range(3):
            fog_arr[:, :, c] += fog_contribution * color[c]
        fog_arr[:, :, 3] += fog_contribution * 0.5

    fog_arr = np.clip(fog_arr, 0, 255)
    return Image.fromarray(fog_arr.astype(np.uint8), "RGBA")


def render_god_rays(
    width: int,
    height: int,
    light_pos: tuple[float, float],
    ray_count: int = 12,
    time: float = 0.0,
    color: tuple[int, int, int] = (200, 220, 255),
    intensity: float = 0.25,
) -> Image.Image:
    rays_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(rays_img, "RGBA")

    lx, ly = light_pos

    for i in range(ray_count):
        base_angle = i * math.tau / ray_count + time * 0.08
        sway = math.sin(time * 0.5 + i * 1.7) * 0.08
        angle = base_angle + sway

        ray_length = height * (1.2 + 0.3 * math.sin(time * 0.3 + i))
        spread = 0.04 + 0.02 * math.sin(time * 0.4 + i * 2.1)

        x_end = lx + math.cos(angle) * ray_length
        y_end = ly + math.sin(angle) * ray_length

        perp_angle = angle + math.pi / 2
        spread_x = math.cos(perp_angle) * width * spread
        spread_y = math.sin(perp_angle) * width * spread

        alpha = int(18 + 22 * math.sin(time * 0.6 + i * 1.3))

        points = [
            (lx + spread_x, ly + spread_y),
            (lx - spread_x, ly - spread_y),
            (x_end - spread_x * 3, y_end - spread_y * 3),
            (x_end + spread_x * 3, y_end + spread_y * 3),
        ]

        draw.polygon(points, fill=(*color, alpha))

    return rays_img


def render_bloom(
    img: Image.Image,
    threshold: float = 0.7,
    blur_radius: int = 15,
    intensity: float = 0.35,
) -> Image.Image:
    arr = np.asarray(img).astype(np.float32) / 255.0

    bright = np.maximum(arr[:, :, :3] - threshold, 0)
    bright_rgb = np.zeros((bright.shape[0], bright.shape[1], 4), dtype=np.float32)
    bright_rgb[:, :, :3] = bright
    bright_rgb[:, :, 3] = 1.0

    bright_img = Image.fromarray((bright_rgb * 255).astype(np.uint8), "RGBA")
    blurred = bright_img.filter(ImageFilter.GaussianBlur(blur_radius))

    bloom_arr = np.asarray(blurred).astype(np.float32) / 255.0
    result_arr = arr.copy()
    result_arr[:, :, :3] += bloom_arr[:, :, :3] * intensity
    result_arr = np.clip(result_arr, 0, 1)

    return Image.fromarray((result_arr * 255).astype(np.uint8), img.mode if img.mode else "RGB")


def render_cinematic_lighting(
    width: int,
    height: int,
    scene_type: str = "hook",
    time: float = 0.0,
    color_scheme: str = "cyan_gold",
) -> Image.Image:
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")

    palettes = {
        "cyan_gold": {
            "primary": (0, 245, 212),
            "secondary": (255, 214, 102),
            "accent": (255, 54, 121),
        },
        "teal_amber": {
            "primary": (94, 234, 212),
            "secondary": (248, 250, 252),
            "accent": (251, 113, 133),
        },
        "blue_rose": {
            "primary": (125, 211, 252),
            "secondary": (250, 204, 21),
            "accent": (244, 114, 182),
        },
        "danger_red": {
            "primary": (255, 54, 121),
            "secondary": (255, 120, 80),
            "accent": (255, 200, 100),
        },
    }

    palette = palettes.get(color_scheme, palettes["cyan_gold"])
    primary = palette["primary"]
    secondary = palette["secondary"]
    accent = palette["accent"]

    light_configs = []

    if scene_type in ("hook", "reveal", "cta"):
        light_configs = [
            {
                "x": width * 0.5,
                "y": height * 0.15,
                "color": primary,
                "intensity": 0.7,
                "radius": width * 0.5,
                "type": "key",
            },
            {
                "x": width * 0.15,
                "y": height * 0.6,
                "color": secondary,
                "intensity": 0.4,
                "radius": width * 0.35,
                "type": "fill",
            },
            {
                "x": width * 0.85,
                "y": height * 0.4,
                "color": accent,
                "intensity": 0.3,
                "radius": width * 0.3,
                "type": "rim",
            },
        ]
    elif scene_type in ("warning", "problem"):
        light_configs = [
            {
                "x": width * 0.5,
                "y": height * 0.2,
                "color": accent,
                "intensity": 0.8,
                "radius": width * 0.6,
                "type": "alarm",
            },
            {
                "x": width * 0.25,
                "y": height * 0.7,
                "color": primary,
                "intensity": 0.3,
                "radius": width * 0.3,
                "type": "edge",
            },
        ]
    else:
        light_configs = [
            {
                "x": width * 0.4,
                "y": height * 0.3,
                "color": primary,
                "intensity": 0.6,
                "radius": width * 0.45,
                "type": "key",
            },
            {
                "x": width * 0.7,
                "y": height * 0.5,
                "color": secondary,
                "intensity": 0.4,
                "radius": width * 0.35,
                "type": "fill",
            },
        ]

    for light in light_configs:
        cx, cy = light["x"], light["y"]
        color = light["color"]
        radius = light["radius"]
        intensity = light["intensity"]

        pulse = 0.85 + 0.15 * math.sin(time * 2.0 + cx * 0.01)
        effective_radius = radius * pulse

        for ring in range(5):
            r = effective_radius * (0.2 + ring * 0.2)
            alpha = int(intensity * (80 - ring * 14) * (1 - ring * 0.18))
            if alpha > 0:
                draw.ellipse(
                    (cx - r, cy - r, cx + r, cy + r),
                    fill=(*color, alpha),
                )

    return overlay
