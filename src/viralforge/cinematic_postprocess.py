from __future__ import annotations

import math
import numpy as np
from PIL import Image, ImageFilter


def apply_film_grain(
    img: Image.Image,
    intensity: float = 0.04,
    seed: int = 42,
) -> Image.Image:
    arr = np.asarray(img).astype(np.float32)
    h, w = arr.shape[:2]

    rng = np.random.default_rng(seed)
    grain = rng.normal(0, intensity * 255, (h, w, 1))

    grain_pattern = grain * 0.7
    grain_pattern += rng.normal(0, intensity * 128, (h, w, 1)) * 0.3

    result = arr + grain_pattern
    result = np.clip(result, 0, 255)
    return Image.fromarray(result.astype(np.uint8), img.mode)


def apply_chromatic_aberration(
    img: Image.Image,
    offset: float = 1.5,
    direction: tuple[float, float] = (1.0, 0.0),
) -> Image.Image:
    arr = np.asarray(img)
    if arr.shape[2] == 4:
        rgb = arr[:, :, :3]
        alpha = arr[:, :, 3]
    else:
        rgb = arr
        alpha = None

    h, w = rgb.shape[:2]
    dx = int(offset * direction[0])
    dy = int(offset * direction[1])

    result = np.zeros_like(rgb)
    result[:, :, 0] = np.roll(np.roll(rgb[:, :, 0], dy, axis=0), dx, axis=1)
    result[:, :, 1] = rgb[:, :, 1]
    result[:, :, 2] = np.roll(np.roll(rgb[:, :, 2], -dy, axis=0), -dx, axis=1)

    edge_mask = np.zeros((h, w), dtype=bool)
    if dx != 0 or dy != 0:
        margin = max(abs(dx), abs(dy))
        if margin > 0:
            edge_mask[:margin, :] = True
            edge_mask[-margin:, :] = True
            edge_mask[:, :margin] = True
            edge_mask[:, -margin:] = True
        result[edge_mask] = rgb[edge_mask]

    if alpha is not None:
        final = np.dstack([result, alpha])
        return Image.fromarray(final, "RGBA")
    return Image.fromarray(result, "RGB")


def apply_lens_distortion(
    img: Image.Image,
    strength: float = 0.08,
) -> Image.Image:
    arr = np.asarray(img).astype(np.float32)
    h, w = arr.shape[:2]

    center_x, center_y = w / 2, h / 2
    max_radius = math.sqrt(center_x ** 2 + center_y ** 2)

    yy, xx = np.mgrid[0:h, 0:w]
    xx = xx - center_x
    yy = yy - center_y

    r = np.sqrt(xx ** 2 + yy ** 2) / max_radius
    distortion = 1 + strength * r ** 2

    src_x = (xx * distortion + center_x).astype(np.float32)
    src_y = (yy * distortion + center_y).astype(np.float32)

    src_x = np.clip(src_x, 0, w - 1)
    src_y = np.clip(src_y, 0, h - 1)

    result = np.zeros_like(arr)
    for c in range(arr.shape[2]):
        result[:, :, c] = np.interp(
            np.arange(h * w),
            np.arange(h * w),
            arr[:, :, c].flatten(),
        ).reshape(h, w)

    for y in range(h):
        for x in range(w):
            sx = int(src_x[y, x])
            sy = int(src_y[y, x])
            result[y, x] = arr[sy, sx]

    return Image.fromarray(result.astype(np.uint8), img.mode)


def apply_motion_blur(
    img: Image.Image,
    direction: tuple[float, float] = (1.0, 0.0),
    distance: int = 8,
) -> Image.Image:
    if distance <= 0:
        return img

    angle = math.atan2(direction[1], direction[0])
    angle_deg = math.degrees(angle)

    blur_img = img.filter(ImageFilter.GaussianBlur(radius=distance * 0.4))

    result = img.copy()
    pixels = result.load()
    blur_pixels = blur_img.load()
    w, h = result.size

    blend_factor = min(1.0, distance / 16)
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            orig = pixels[x, y]
            blurred = blur_pixels[x, y]

            if len(orig) == 4:
                blended = tuple(
                    int(orig[i] * (1 - blend_factor) + blurred[i] * blend_factor)
                    for i in range(3)
                ) + (orig[3],)
            else:
                blended = tuple(
                    int(orig[i] * (1 - blend_factor) + blurred[i] * blend_factor)
                    for i in range(3)
                )

            pixels[x, y] = blended

    return result


def apply_vignette(
    img: Image.Image,
    intensity: float = 0.55,
    softness: float = 0.7,
) -> Image.Image:
    arr = np.asarray(img).astype(np.float32)
    h, w = arr.shape[:2]

    center_x, center_y = w / 2, h / 2
    yy, xx = np.mgrid[0:h, 0:w]

    dx = (xx - center_x) / center_x
    dy = (yy - center_y) / center_y
    dist = np.sqrt(dx ** 2 + dy ** 2)

    vignette = np.ones((h, w), dtype=np.float32)
    mask = dist > softness
    vignette[mask] = 1 - ((dist[mask] - softness) / (1 - softness)) ** 1.5 * intensity

    vignette = np.clip(vignette, 0, 1)
    vignette_3d = vignette[:, :, np.newaxis]

    result = arr * vignette_3d
    result = np.clip(result, 0, 255)
    return Image.fromarray(result.astype(np.uint8), img.mode)


def apply_color_grading(
    img: Image.Image,
    shadows: tuple[float, float, float] = (1.0, 1.0, 1.0),
    midtones: tuple[float, float, float] = (1.0, 1.0, 1.0),
    highlights: tuple[float, float, float] = (1.0, 1.0, 1.0),
    saturation: float = 1.0,
    contrast: float = 1.0,
) -> Image.Image:
    arr = np.asarray(img).astype(np.float32) / 255.0

    if contrast != 1.0:
        arr = (arr - 0.5) * contrast + 0.5

    if saturation != 1.0:
        luminance = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
        luminance = luminance[:, :, np.newaxis]
        arr = luminance + saturation * (arr - luminance)

    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

    shadow_mask = (1 - np.clip(r * 3, 0, 1)) * (1 - np.clip(g * 3, 0, 1)) * (1 - np.clip(b * 3, 0, 1))
    highlight_mask = np.clip(r * 3 - 2, 0, 1) * np.clip(g * 3 - 2, 0, 1) * np.clip(b * 3 - 2, 0, 1)
    midtone_mask = 1 - shadow_mask - highlight_mask

    arr[:, :, 0] = np.clip(r * (shadows[0] * shadow_mask + midtones[0] * midtone_mask + highlights[0] * highlight_mask), 0, 1)
    arr[:, :, 1] = np.clip(g * (shadows[1] * shadow_mask + midtones[1] * midtone_mask + highlights[1] * highlight_mask), 0, 1)
    arr[:, :, 2] = np.clip(b * (shadows[2] * shadow_mask + midtones[2] * midtone_mask + highlights[2] * highlight_mask), 0, 1)

    arr = np.clip(arr * 255, 0, 255)
    return Image.fromarray(arr.astype(np.uint8), img.mode)


def apply_depth_of_field(
    img: Image.Image,
    depth_map: np.ndarray | None = None,
    focus_depth: float = 0.5,
    blur_amount: int = 8,
    width: int = 1080,
    height: int = 1920,
) -> Image.Image:
    if depth_map is None:
        yy = np.linspace(0, 1, height)[:, np.newaxis]
        xx = np.linspace(0, 1, width)[np.newaxis, :]
        depth_map = np.ones((height, width), dtype=np.float32) * 0.5
        depth_map += (yy - 0.5) * 0.3

    sharp = img
    blurred = img.filter(ImageFilter.GaussianBlur(blur_amount))

    sharp_arr = np.asarray(sharp).astype(np.float32)
    blurred_arr = np.asarray(blurred).astype(np.float32)

    blur_factor = np.abs(depth_map - focus_depth) * 2
    blur_factor = np.clip(blur_factor, 0, 1)

    if sharp_arr.shape[2] == 4:
        blur_factor_4d = blur_factor[:, :, np.newaxis]
        result = sharp_arr * (1 - blur_factor_4d) + blurred_arr * blur_factor_4d
    else:
        blur_factor_3d = blur_factor[:, :, np.newaxis]
        result = sharp_arr * (1 - blur_factor_3d) + blurred_arr * blur_factor_3d

    result = np.clip(result, 0, 255)
    return Image.fromarray(result.astype(np.uint8), sharp.mode)


def cinematic_post_process(
    img: Image.Image,
    time: float,
    scene_index: int,
    intensity: float = 1.0,
    enable_grain: bool = True,
    enable_chromatic: bool = True,
    enable_vignette: bool = True,
    enable_color_grade: bool = True,
) -> Image.Image:
    result = img

    if enable_vignette:
        result = apply_vignette(result, intensity=0.45 * intensity)

    if enable_chromatic:
        chroma_offset = 1.2 * intensity
        direction = (math.sin(time * 0.5), math.cos(time * 0.3))
        result = apply_chromatic_aberration(result, offset=chroma_offset, direction=direction)

    if enable_color_grade:
        result = apply_color_grading(
            result,
            shadows=(0.95, 0.98, 1.05),
            midtones=(1.0, 1.02, 1.0),
            highlights=(1.05, 1.0, 0.95),
            saturation=1.15,
            contrast=1.08,
        )

    if enable_grain:
        grain_seed = int(time * 100) + scene_index * 1000
        result = apply_film_grain(result, intensity=0.035 * intensity, seed=grain_seed)

    return result
