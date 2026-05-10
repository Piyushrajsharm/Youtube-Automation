import os
import requests
from dotenv import load_dotenv

def register_commands():
    load_dotenv(os.path.join("d:\\Automation", ".env"))
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not token:
        print("No bot token found.")
        return
        
    commands = [
        {"command": "discover", "description": "Find current tech trends"},
        {"command": "status", "description": "Check bot usage and queue"},
        {"command": "jobs", "description": "List recent jobs"},
        {"command": "health", "description": "Check local OAuth/config health"},
        {"command": "whoami", "description": "Check your role"},
        {"command": "plan", "description": "Generate script and metadata only"},
        {"command": "render", "description": "Create a private video package"},
        {"command": "render_upload", "description": "Render, then request upload approval"},
        {"command": "autopilot", "description": "Toggle 24/7 automation (/autopilot on/off)"},
        {"command": "cancel", "description": "Cancel queued/pending job"},
        {"command": "config", "description": "Safe bot settings summary"}
    ]
    
    res = requests.post(
        f"https://api.telegram.org/bot{token}/setMyCommands",
        json={"commands": commands}
    )
    print(res.json())

if __name__ == "__main__":
    register_commands()
