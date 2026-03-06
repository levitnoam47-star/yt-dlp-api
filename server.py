from flask import Flask, request, jsonify, Response
import subprocess, json, requests

app = Flask(__name__)

@app.route("/direct-url", methods=["GET"])
def direct_url():
    url = request.args.get("url")
    result = subprocess.run(["yt-dlp", "-f", "best[ext=mp4]", "-g", url], capture_output=True, text=True)
    return jsonify({"url": result.stdout.strip()})

@app.route("/download", methods=["GET"])
def download():
    url = request.args.get("url")
    # Get direct URL
    result = subprocess.run(["yt-dlp", "-f", "best[ext=mp4]", "-g", url], capture_output=True, text=True)
    video_url = result.stdout.strip()
    if not video_url:
        return jsonify({"error": "Could not get URL"}), 400
    
    # Stream the video through our server
    r = requests.get(video_url, stream=True)
    return Response(
        r.iter_content(chunk_size=8192),
        content_type="video/mp4",
        headers={"Content-Length": r.headers.get("Content-Length", "")}
    )
