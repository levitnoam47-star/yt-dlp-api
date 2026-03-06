from flask import Flask, request, jsonify
import subprocess

app = Flask(__name__)

@app.route("/")
def health():
    return jsonify({"status": "ok"})

@app.route("/direct-url")
def direct_url():
    url = request.args.get("url")
    if not url:
        return jsonify({"error": "url param required"}), 400
    result = subprocess.run(
        ["yt-dlp", "-f", "best[ext=mp4]", "-g", url],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        return jsonify({"error": result.stderr.strip()}), 500
    return jsonify({"url": result.stdout.strip()})
