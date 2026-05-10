"""Standalone NVIDIA image-to-video smoke test."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

from viralforge.config import load_settings
from viralforge.nvidia_client import NvidiaUnifiedClient
from viralforge.nvidia_video_adapter import image_data_uri_from_frame


def demo(prompt: str) -> Path:
    settings = load_settings()
    if not settings.nvidia_api_key:
        raise RuntimeError("NVIDIA_API_KEY not set. Add it to .env")

    client = NvidiaUnifiedClient(settings)
    out = Path(__file__).resolve().parents[1] / "outputs" / "nvidia_demos"
    out.mkdir(parents=True, exist_ok=True)
    seed_path = out / "demo_nvidia_seed.jpg"
    video_path = out / "demo_nvidia_video.mp4"

    seed = _demo_seed(settings.video_width, settings.video_height)
    image_data_uri = image_data_uri_from_frame(seed, seed_path)
    data = client.generate_video_from_image(
        image_data_uri,
        prompt=prompt,
        seed=1,
        cfg_scale=settings.nvidia_video_cfg_scale,
        motion_bucket_id=settings.nvidia_video_motion_bucket_id,
    )
    video_path.write_bytes(data)
    return video_path


def _demo_seed(width: int, height: int) -> np.ndarray:
    image = Image.new("RGB", (width, height), (4, 8, 16))
    draw = ImageDraw.Draw(image)
    for step in range(0, height, 72):
        draw.line((0, step, width, step + width * 0.18), fill=(0, 245, 212), width=3)
    draw.rounded_rectangle((width * 0.16, height * 0.26, width * 0.84, height * 0.62), radius=44, outline=(255, 214, 102), width=5)
    draw.text((width * 0.22, height * 0.39), "AI VIDEO SEED", fill=(255, 255, 255))
    return np.asarray(image)


if __name__ == "__main__":
    path = demo(
        "Cinematic futuristic AI command room, holographic interface, dramatic camera push, "
        "volumetric fog, teal and amber rim lighting, premium sci-fi commercial shot."
    )
    print(path)
