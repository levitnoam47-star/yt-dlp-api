from flask import Flask, request, jsonify, send_file
import subprocess
import os
import tempfile
import uuid

app = Flask(__name__)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/composite", methods=["GET"])
def composite():
    video_url = request.args.get("url")
    if not video_url:
        return jsonify({"error": "Missing 'url' parameter"}), 400

    start = request.args.get("start", "0")
    duration = request.args.get("duration", "30")

    output_id = str(uuid.uuid4())
    output_path = os.path.join(tempfile.gettempdir(), f"{output_id}.mp4")

    # Step 1: Get direct video URL using yt-dlp
    try:
        yt_result = subprocess.run(
            ["yt-dlp", "-f", "best[ext=mp4]", "--get-url", video_url],
            capture_output=True, text=True, timeout=60
        )
        if yt_result.returncode != 0:
            return jsonify({
                "error": "yt-dlp failed to get direct URL",
                "stderr": yt_result.stderr[-500:]
            }), 500
        direct_url = yt_result.stdout.strip()
    except Exception as e:
        return jsonify({"error": f"yt-dlp error: {str(e)}"}), 500

    # Step 2: FFmpeg with direct URL
    filter_complex = (
        "[0:v]split=2[v1][v2];"
        "[v1]crop=iw*0.25:ih*0.28:0:ih*0.72,scale=1080:570[face];"
        "[v2]crop=iw*0.73:ih*0.87:iw*0.25:ih*0.05,scale=1080:1350[chart];"
        "[face][chart]vstack=inputs=2[out]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", direct_url,
        "-t", str(duration),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-threads", "2",
        output_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            return jsonify({
                "error": "FFmpeg failed",
                "stderr": result.stderr[-500:]
            }), 500

        return send_file(
            output_path,
            mimetype="video/mp4",
            as_attachment=True,
            download_name=f"clip_{output_id}.mp4"
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Processing timed out"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
