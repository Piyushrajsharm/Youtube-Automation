from __future__ import annotations

import json
import requests
from pathlib import Path
from .config import Settings
from .models import VideoPlan

def trigger_cloud_render(plan: VideoPlan, settings: Settings, output_dir: Path) -> dict[str, str]:
    """
    Orchestrates cloud rendering based on the configured RENDER_MODE.
    Returns a dict with 'status' and 'message' or 'url'.
    """
    mode = settings.render_mode
    
    if mode == "creatomate":
        return _render_creatomate(plan, settings)
    elif mode == "github":
        return _render_github(plan, settings, output_dir)
    else:
        return {"status": "error", "message": f"Unknown cloud render mode: {mode}"}

def _render_creatomate(plan: VideoPlan, settings: Settings) -> dict[str, str]:
    if not settings.creatomate_api_key:
        return {"status": "error", "message": "CREATOMATE_API_KEY not set"}
    
    # Simplified Creatomate mapping
    payload = {
        "source": {
            "output_format": "mp4",
            "width": 1080,
            "height": 1920,
            "elements": []
        }
    }
    
    # Add scenes as elements
    for i, scene in enumerate(plan.scenes):
        payload["source"]["elements"].append({
            "type": "text",
            "text": scene.narration,
            "time": i * 5, # Placeholder timing
            "duration": 5
        })

    try:
        resp = requests.post(
            "https://api.creatomate.com/v1/renders",
            headers={"Authorization": f"Bearer {settings.creatomate_api_key}"},
            json=payload,
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        return {"status": "success", "url": data.get("url", ""), "id": data.get("id", "")}
    except Exception as e:
        return {"status": "error", "message": f"Creatomate API failed: {e}"}

def _render_github(plan: VideoPlan, settings: Settings, output_dir: Path) -> dict[str, str]:
    if not settings.github_token or not settings.github_repo:
        return {"status": "error", "message": "GITHUB_TOKEN or GITHUB_REPO not set"}
    
    # Save the plan to a file that the GH Action can read
    plan_path = output_dir / "video_plan.json"
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan.to_dict(), f, indent=2)
    
    # Trigger GitHub repository_dispatch
    repo = settings.github_repo # e.g. "username/repo"
    url = f"https://api.github.com/repos/{repo}/dispatches"
    headers = {
        "Authorization": f"token {settings.github_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {
        "event_type": "render_video",
        "client_payload": {
            "topic": plan.topic,
            "plan_json": plan.to_dict()
        }
    }
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return {"status": "success", "message": "GitHub Action triggered successfully"}
    except Exception as e:
        return {"status": "error", "message": f"GitHub API failed: {e}"}
