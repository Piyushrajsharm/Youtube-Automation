from __future__ import annotations

import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def generate_procedural_texture(
    width: int,
    height: int,
    texture_type: str = "gradient",
    colors: dict[str, tuple[int, int, int]] | None = None,
    time: float = 0.0,
    scene_index: int = 0,
) -> Image.Image:
    if colors is None:
        colors = {
            "bg": (4, 8, 16),
            "primary": (0, 245, 212),
            "secondary": (255, 214, 102),
            "accent": (255, 54, 121),
        }

    bg = colors.get("bg", (4, 8, 16))
    primary = colors.get("primary", (0, 245, 212))
    secondary = colors.get("secondary", (255, 214, 102))
    accent = colors.get("accent", (255, 54, 121))

    if texture_type == "gradient":
        return _procedural_gradient(width, height, bg, primary, secondary, time, scene_index)
    elif texture_type == "architectural":
        return _procedural_architecture(width, height, bg, primary, secondary, time, scene_index)
    elif texture_type == "tech_grid":
        return _procedural_tech_grid(width, height, bg, primary, time, scene_index)
    elif texture_type == "nebula":
        return _procedural_nebula(width, height, bg, primary, accent, time, scene_index)
    else:
        return _procedural_gradient(width, height, bg, primary, secondary, time, scene_index)


def _procedural_gradient(
    width: int,
    height: int,
    bg: tuple[int, int, int],
    primary: tuple[int, int, int],
    secondary: tuple[int, int, int],
    time: float,
    scene_index: int,
) -> Image.Image:
    yy = np.linspace(0, 1, height)[:, np.newaxis]
    xx = np.linspace(0, 1, width)[np.newaxis, :]

    base = np.zeros((height, width, 3), dtype=np.float32)
    for c in range(3):
        gradient = bg[c] * (1 - yy) + primary[c] * yy * 0.4
        gradient = gradient + secondary[c] * 0.15 * np.sin(xx * math.pi + time * 0.3)
        base[:, :, c] = gradient

    wave1 = 0.5 + 0.5 * np.sin((xx * 3 + yy * 2 + time * 0.5 + scene_index) * math.pi * 2)
    wave2 = 0.5 + 0.5 * np.sin((xx * 5 - yy * 3 + time * 0.7) * math.pi * 2)

    for c in range(3):
        base[:, :, c] += wave1 * primary[c] * 0.08
        base[:, :, c] += wave2 * secondary[c] * 0.05

    base = np.clip(base, 0, 255)
    return Image.fromarray(base.astype(np.uint8), "RGB")


def _procedural_architecture(
    width: int,
    height: int,
    bg: tuple[int, int, int],
    primary: tuple[int, int, int],
    secondary: tuple[int, int, int],
    time: float,
    scene_index: int,
) -> Image.Image:
    img_arr = np.zeros((height, width, 3), dtype=np.float32)

    for c in range(3):
        img_arr[:, :, c] = bg[c]

    horizon_y = int(height * 0.45)

    for c in range(3):
        fade = np.linspace(0, 1, horizon_y)[:, np.newaxis]
        img_arr[:horizon_y, :, c] = img_arr[:horizon_y, :, c] * (1 - fade * 0.3) + primary[c] * fade * 0.15

    for tower in range(12):
        tower_x = int(width * (0.05 + tower * 0.08 + 0.04 * math.sin(tower * 2.1 + scene_index)))
        tower_width = int(width * (0.03 + 0.02 * math.sin(tower * 1.3)))
        tower_height = int(height * (0.25 + 0.2 * math.sin(tower * 0.7 + time * 0.2)))

        x0 = max(0, tower_x - tower_width // 2)
        x1 = min(width, tower_x + tower_width // 2)
        y0 = max(0, horizon_y - tower_height)
        y1 = horizon_y

        pulse = 0.7 + 0.3 * math.sin(time * 0.5 + tower * 0.8)

        for c in range(3):
            tower_color = primary[c] if tower % 2 == 0 else secondary[c]
            img_arr[y0:y1, x0:x1, c] = tower_color * 0.15 * pulse

        window_rows = max(3, tower_height // 25)
        for row in range(window_rows):
            window_y = y0 + 15 + row * (tower_height - 30) // window_rows
            if window_y >= y1:
                break

            window_on = math.sin(time * 2 + tower + row * 0.5) > 0.2
            if window_on:
                for c in range(3):
                    img_arr[window_y:window_y + 3, x0 + 4:x1 - 4, c] = secondary[c] * 0.3

    for c in range(3):
        floor_gradient = np.linspace(0.3, 0, height - horizon_y)[:, np.newaxis]
        img_arr[horizon_y:, :, c] = bg[c] * (1 - floor_gradient * 0.5) + primary[c] * floor_gradient * 0.1

    return Image.fromarray(img_arr.astype(np.uint8), "RGB")


def _procedural_tech_grid(
    width: int,
    height: int,
    bg: tuple[int, int, int],
    primary: tuple[int, int, int],
    time: float,
    scene_index: int,
) -> Image.Image:
    img_arr = np.zeros((height, width, 3), dtype=np.float32)

    for c in range(3):
        img_arr[:, :, c] = bg[c]

    grid_spacing = 40
    grid_alpha = 0.12 + 0.08 * math.sin(time * 0.3)

    for y in range(0, height, grid_spacing):
        alpha = grid_alpha * (0.5 + 0.5 * math.sin(y * 0.05 + time))
        for c in range(3):
            img_arr[y:y + 1, :, c] += primary[c] * alpha

    for x in range(0, width, grid_spacing):
        alpha = grid_alpha * (0.5 + 0.5 * math.sin(x * 0.05 + time * 0.7))
        for c in range(3):
            img_arr[:, x:x + 1, c] += primary[c] * alpha

    node_count = 20
    for node in range(node_count):
        node_x = int(width * (0.1 + 0.8 * ((node * 0.137 + time * 0.05) % 1)))
        node_y = int(height * (0.1 + 0.8 * ((node * 0.213 + time * 0.03) % 1)))

        node_pulse = 0.5 + 0.5 * math.sin(time * 2 + node)
        radius = int(8 + node_pulse * 12)

        y0, y1 = max(0, node_y - radius), min(height, node_y + radius)
        x0, x1 = max(0, node_x - radius), min(width, node_x + radius)

        for cy in range(y0, y1):
            for cx in range(x0, x1):
                dist = math.sqrt((cx - node_x) ** 2 + (cy - node_y) ** 2)
                if dist < radius:
                    factor = (1 - dist / radius) * node_pulse * 0.4
                    for c in range(3):
                        img_arr[cy, cx, c] = min(255, img_arr[cy, cx, c] + primary[c] * factor)

    return Image.fromarray(img_arr.astype(np.uint8), "RGB")


def _procedural_nebula(
    width: int,
    height: int,
    bg: tuple[int, int, int],
    primary: tuple[int, int, int],
    accent: tuple[int, int, int],
    time: float,
    scene_index: int,
) -> Image.Image:
    yy, xx = np.mgrid[0:height, 0:width]

    img_arr = np.zeros((height, width, 3), dtype=np.float32)
    for c in range(3):
        img_arr[:, :, c] = bg[c]

    for cloud in range(5):
        cx = width * (0.3 + 0.4 * math.sin(cloud * 1.5 + time * 0.1))
        cy = height * (0.3 + 0.4 * math.cos(cloud * 1.2 + time * 0.08))
        radius = width * (0.2 + 0.1 * math.sin(cloud * 0.7))

        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        cloud_mask = np.exp(-dist / (radius * 0.5))

        cloud_color = primary if cloud % 2 == 0 else accent
        cloud_alpha = 0.15 + 0.1 * math.sin(time * 0.4 + cloud)

        for c in range(3):
            img_arr[:, :, c] += cloud_mask * cloud_color[c] * cloud_alpha

    star_count = 150
    rng = np.random.default_rng(scene_index * 1000 + 42)
    star_x = rng.uniform(0, width, star_count)
    star_y = rng.uniform(0, height, star_count)
    star_brightness = rng.uniform(0.3, 1.0, star_count)
    star_twinkle = np.sin(time * 3 + rng.uniform(0, 10, star_count)) * 0.5 + 0.5

    for i in range(star_count):
        sx, sy = int(star_x[i]), int(star_y[i])
        if 0 <= sx < width and 0 <= sy < height:
            brightness = star_brightness[i] * star_twinkle[i]
            for c in range(3):
                img_arr[sy, sx, c] = min(255, img_arr[sy, sx, c] + 255 * brightness * 0.5)

    img_arr = np.clip(img_arr, 0, 255)
    return Image.fromarray(img_arr.astype(np.uint8), "RGB")


def create_advanced_background(
    width: int,
    height: int,
    scene_type: str,
    time: float,
    scene_index: int,
    color_scheme: str = "cyan_gold",
) -> Image.Image:
    palettes = {
        "cyan_gold": {
            "bg": (4, 8, 16),
            "primary": (0, 245, 212),
            "secondary": (255, 214, 102),
            "accent": (255, 54, 121),
        },
        "teal_amber": {
            "bg": (7, 9, 20),
            "primary": (94, 234, 212),
            "secondary": (248, 250, 252),
            "accent": (251, 113, 133),
        },
        "blue_rose": {
            "bg": (9, 12, 26),
            "primary": (125, 211, 252),
            "secondary": (250, 204, 21),
            "accent": (244, 114, 182),
        },
        "danger_red": {
            "bg": (16, 4, 8),
            "primary": (255, 54, 121),
            "secondary": (255, 120, 80),
            "accent": (255, 200, 100),
        },
    }

    colors = palettes.get(color_scheme, palettes["cyan_gold"])

    texture_map = {
        "hook": "gradient",
        "problem": "tech_grid",
        "reveal": "nebula",
        "warning": "danger_red",
        "control": "architectural",
        "payoff": "gradient",
        "cta": "nebula",
    }

    texture_type = texture_map.get(scene_type, "gradient")

    if scene_type in ("warning", "danger"):
        colors = palettes["danger_red"]

    base = generate_procedural_texture(width, height, texture_type, colors, time, scene_index)

    vignette_mask = _create_vignette_mask(width, height, intensity=0.4)
    base_arr = np.asarray(base).astype(np.float32)
    base_arr *= vignette_mask
    base_arr = np.clip(base_arr, 0, 255)

    return Image.fromarray(base_arr.astype(np.uint8), "RGB")


def _create_vignette_mask(
    width: int,
    height: int,
    intensity: float = 0.5,
) -> np.ndarray:
    yy, xx = np.mgrid[0:height, 0:width]
    center_x, center_y = width / 2, height / 2

    dx = (xx - center_x) / center_x
    dy = (yy - center_y) / center_y
    dist = np.sqrt(dx ** 2 + dy ** 2)

    mask = np.ones((height, width), dtype=np.float32)
    mask = 1 - (dist ** 1.5) * intensity
    mask = np.clip(mask, 0, 1)

    return mask[:, :, np.newaxis]
