import time
import requests
import argparse

def ping_space(url, interval_minutes):
    print(f"Starting keep-awake ping for: {url}")
    print(f"Interval: Every {interval_minutes} minutes. Press CTRL+C to stop.")
    
    interval_seconds = interval_minutes * 60
    
    while True:
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Success! Space is awake.")
            else:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Pinged, but got status code: {response.status_code}")
        except Exception as e:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Failed to ping: {e}")
            
        time.sleep(interval_seconds)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Keep a Hugging Face Space awake.")
    parser.add_argument("url", help="The direct URL of your Hugging Face space (e.g., https://username-spacename.hf.space)")
    parser.add_argument("--interval", type=int, default=10, help="Ping interval in minutes (default: 10)")
    
    args = parser.parse_args()
    ping_space(args.url, args.interval)
