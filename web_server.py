import os
import threading
import time

import requests
from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/")
def home():
    """Root route for health check"""
    return "✅ Bot is alive and running!", 200


@app.route("/health")
def health():
    """Simple health route for Koyeb to monitor container"""
    return jsonify({"status": "ok", "timestamp": time.time()}), 200


@app.route("/ping")
def ping():
    """Manual ping endpoint"""
    return jsonify({"pong": True}), 200


def ping_self():
    """Keep the bot alive by pinging its own Koyeb URL periodically."""
    url = os.environ.get("KEEPALIVE_URL")
    interval = int(os.environ.get("KEEPALIVE_INTERVAL", 290))  # Default: 4m 50s

    if not url:
        print("⚠️ KEEPALIVE_URL not set. Skipping self-ping.")
        return

    print(f"🟢 Keepalive thread started — pinging {url} every {interval} seconds.")
    while True:
        time.sleep(interval)
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                print(f"🔁 Successfully pinged {url}")
            else:
                print(f"⚠️ Ping returned status {response.status_code}")
        except requests.RequestException as e:
            print(f"❌ Keepalive ping failed: {e}")


def start_keepalive():
    """Launch keepalive pinger in a background thread"""
    thread = threading.Thread(target=ping_self, daemon=True)
    thread.start()
    return thread


# --- Run when deployed ---
if __name__ == "__main__":
    start_keepalive()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
