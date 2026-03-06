from flask import Flask, request, jsonify, Response
import subprocess, json, os, tempfile, uuid

app = Flask(__name__)

@app.route("/direct-url", methods=["GET"])
def direct_url():
    url = request.args.get("url")
    result = subprocess.run(["yt-dlp", "-f", "best[ext=mp4]", "-g", url], capture_output=True, text=True)
    return jsonify({"url": result.stdout.strip()})

@app.route("/download", methods=["GET"])
def download():
    url = request.args.get("url")
    result = subprocess.run(["yt-dlp", "-f", "best[ext=mp4]", "-g", url], capture_output=True, text=True)
    video_url = result.stdout.strip()
    if not video_url:
        return jsonify({"error": "Could not get URL"}), 400
    import requests as req
    r = req.get(video_url, stream=True)
    return Response(
        r.iter_content(chunk_size=8192),
        content_type="video/mp4",
        headers={"Content-Length": r.headers.get("Content-Length", "")}
    )

@app.route("/composite", methods=["GET"])
def composite():
    """Create 9:16 composite: facecam on top, chart on bottom"""
    url = request.args.get("url")
    start = request.args.get("start", "0")
    duration = request.args.get("duration", "30")

    tmp_dir = tempfile.mkdtemp()
    output_file = os.path.join(tmp_dir, f"{uuid.uuid4()}.mp4")

    try:
        # Step 1: Get direct video URL via yt-dlp (720p to save memory)
        direct = subprocess.run(
            ["yt-dlp", "-f", "best[ext=mp4][height<=720]", "-g", url],
            capture_output=True, text=True, timeout=60
        )
        video_url = direct.stdout.strip()

        if not video_url:
            # Fallback to any mp4
            direct = subprocess.run(
                ["yt-dlp", "-f", "best[ext=mp4]", "-g", url],
                capture_output=True, text=True, timeout=60
            )
            video_url = direct.stdout.strip()

        if not video_url:
            return jsonify({
                "error": "Could not get video URL",
                "stderr": direct.stderr[-500:] if direct.stderr else ""
            }), 400

        # Step 2: Download segment + create composite in ONE ffmpeg pass
        ffmpeg_result = subprocess.run([
            "ffmpeg",
            "-ss", str(start),
            "-i", video_url,
            "-t", str(duration),
            "-filter_complex",
            # Split input into two streams to avoid double decode
            "[0:v]split=2[v1][v2];"
            # Facecam: crop bottom-left 40% width x 40% height, scale to 720x320
            "[v1]crop=iw*0.4:ih*0.4:0:ih*0.6,scale=720:320[face];"
            # Chart: crop right 80% width x 78% height, scale to 720x960
            "[v2]crop=iw*0.8:ih*0.78:iw*0.15:ih*0.02,scale=720:960[chart];"
            # Stack vertically = 720x1280
            "[face][chart]vstack=inputs=2[out]",
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "26",
            "-c:a", "aac",
            "-b:a", "96k",
            "-movflags", "+faststart",
            "-threads", "1",
            "-y", output_file
        ], capture_output=True, text=True, timeout=600)

        if not os.path.exists(output_file) or os.path.getsize(output_file) < 1024:
            return jsonify({
                "error": "ffmpeg composite failed",
                "stderr": ffmpeg_result.stderr[-500:] if ffmpeg_result.stderr else "",
                "returncode": ffmpeg_result.returncode
            }), 500

        # Step 3: Stream the result back
        file_size = os.path.getsize(output_file)

        def generate():
            with open(output_file, "rb") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    yield chunk
            # Cleanup
            if os.path.exists(output_file):
                os.remove(output_file)
            if os.path.exists(tmp_dir):
                os.rmdir(tmp_dir)

        return Response(
            generate(),
            content_type="video/mp4",
            headers={"Content-Length": str(file_size)}
        )
    except subprocess.TimeoutExpired:
        if os.path.exists(output_file):
            os.remove(output_file)
        if os.path.exists(tmp_dir):
            os.rmdir(tmp_dir)
        return jsonify({"error": "Process timed out"}), 504
    except Exception as e:
        if os.path.exists(output_file):
            os.remove(output_file)
        if os.path.exists(tmp_dir):
            os.rmdir(tmp_dir)
        return jsonify({"error": str(e)}), 500
