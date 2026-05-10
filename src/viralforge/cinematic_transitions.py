from __future__ import annotations

import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


def apply_flash_transition(
    frame: np.ndarray,
    progress: float,
    width: int,
    height: int,
    color: tuple[int, int, int] = (255, 255, 255),
) -> np.ndarray:
    if progress < 0 or progress > 1:
        return frame

    intensity = math.sin(progress * math.pi)
    if intensity < 0.01:
        return frame

    overlay = np.zeros_like(frame, dtype=np.float32)
    overlay[:, :, :3] = color
    overlay[:, :, 3] = int(intensity * 180)

    frame_float = frame.astype(np.float32)
    alpha = overlay[:, :, 3:4] / 255.0
    result = frame_float * (1 - alpha) + overlay[:, :, :3] * alpha
    return np.clip(result, 0, 255).astype(np.uint8)


def apply_zoom_transition(
    frame: np.ndarray,
    progress: float,
    width: int,
    height: int,
) -> np.ndarray:
    if progress <= 0:
        return frame

    scale = 1 + progress * 3
    blur_amount = int(progress * 12)

    center_x, center_y = width // 2, height // 2
    new_w = int(width * scale)
    new_h = int(height * scale)

    img = Image.fromarray(frame)
    resized = img.resize((new_w, new_h), Image.Resampling.BICUBIC)

    left = max(0, (new_w - width) // 2)
    top = max(0, (new_h - height) // 2)

    cropped = resized.crop((left, top, left + width, top + height))

    if blur_amount > 0:
        cropped = cropped.filter(ImageFilter.GaussianBlur(blur_amount))

    return np.asarray(cropped)


def apply_whip_pan_transition(
    frame: np.ndarray,
    progress: float,
    width: int,
    height: int,
    direction: int = 1,
) -> np.ndarray:
    if progress <= 0 or progress >= 1:
        return frame

    offset = int(width * progress * direction)
    blur = int(15 * math.sin(progress * math.pi))

    img = Image.fromarray(frame)
    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(blur))

    arr = np.asarray(img)
    result = np.zeros_like(arr)

    if direction > 0:
        if offset < width:
            result[:, :width - offset] = arr[:, offset:]
    else:
        if offset > -width:
            result[:, -offset:] = arr[:, :width + offset]

    return result


def apply_glitch_transition(
    frame: np.ndarray,
    progress: float,
    width: int,
    height: int,
    seed: int = 42,
) -> np.ndarray:
    if progress <= 0 or progress >= 1:
        return frame

    result = frame.copy()
    intensity = math.sin(progress * math.pi)

    rng = np.random.default_rng(seed + int(progress * 100))

    glitch_lines = int(20 * intensity)
    for _ in range(glitch_lines):
        y = rng.integers(0, height)
        h = rng.integers(2, 8)
        shift = int(rng.uniform(-50, 50) * intensity)

        if 0 <= y < height and 0 <= y + h < height:
            if shift > 0:
                result[y:y + h, shift:] = frame[y:y + h, :-shift]
            else:
                result[y:y + h, :shift] = frame[y:y + h, -shift:]

    if intensity > 0.5:
        channel_shift = int(8 * intensity)
        r_channel = result[:, :, 0]
        b_channel = result[:, :, 2]
        result[:, :, 0] = np.roll(r_channel, channel_shift, axis=1)
        result[:, :, 2] = np.roll(b_channel, -channel_shift, axis=1)

    return result


def apply_light_sweep_transition(
    frame: np.ndarray,
    progress: float,
    width: int,
    height: int,
    color: tuple[int, int, int] = (200, 230, 255),
) -> np.ndarray:
    if progress <= 0 or progress >= 1:
        return frame

    result = frame.astype(np.float32)

    sweep_x = int(-width * 0.3 + progress * width * 1.6)
    sweep_width = int(width * 0.15)

    for x in range(max(0, sweep_x - sweep_width), min(width, sweep_x + sweep_width)):
        dist = abs(x - sweep_x)
        if dist < sweep_width:
            alpha = (1 - dist / sweep_width) * 0.4 * math.sin(progress * math.pi)
            for y in range(height):
                for c in range(3):
                    result[y, x, c] = min(255, result[y, x, c] + color[c] * alpha)

    return np.clip(result, 0, 255).astype(np.uint8)


def apply_dissolve_transition(
    frame: np.ndarray,
    progress: float,
    width: int,
    height: int,
) -> np.ndarray:
    if progress <= 0:
        return frame

    fade_out = 1 - progress
    result = (frame * fade_out).astype(np.uint8)
    return result


def cinematic_transition(
    frame: np.ndarray,
    transition_type: str,
    progress: float,
    width: int,
    height: int,
    scene_index: int = 0,
    color: tuple[int, int, int] = (200, 230, 255),
) -> np.ndarray:
    if progress <= 0 or progress >= 1:
        return frame

    transitions = {
        "flash_cut": apply_flash_transition,
        "zoom_cut": apply_zoom_transition,
        "whip_cut": lambda f, p, w, h: apply_whip_pan_transition(f, p, w, h, direction=1),
        "glitch_cut": lambda f, p, w, h: apply_glitch_transition(f, p, w, h, seed=scene_index),
        "light_sweep": lambda f, p, w, h: apply_light_sweep_transition(f, p, w, h, color=color),
        "whoosh": lambda f, p, w, h: apply_whip_pan_transition(f, p, w, h, direction=-1),
        "fade": apply_dissolve_transition,
    }

    transition_func = transitions.get(transition_type, apply_flash_transition)

    try:
        return transition_func(frame, progress, width, height)
    except Exception:
        return frame
