from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from viralforge.config import load_settings
from viralforge.pexels_demo_renderer import default_pexels_demo_plan, render_pexels_demo


def main() -> int:
    settings = load_settings()
    settings.google_video_enabled = False
    settings.video_duration_seconds = 34
    settings.video_bitrate = "14000k"
    settings.voice_name = "en-US-ChristopherNeural"
    settings.voice_rate = "+4%"
    settings.voice_pitch = "-1Hz"
    settings.music_volume = 0.08
    settings.sfx_enabled = False
    output_dir = settings.outputs_dir / "20260507_pexels_ai_interns_demo"
    render_pexels_demo(default_pexels_demo_plan(), output_dir, settings)
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
