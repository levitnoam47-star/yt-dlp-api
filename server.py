from flask import Flask, request, jsonify, Response
import subprocess, json, os, tempfile, uuid, glob

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
    input_file = os.path.join(tmp_dir, "input.mp4")
    output_file = os.path.join(tmp_dir, f"{uuid.uuid4()}.mp4")
    
    try:
        # Step 1: Get direct video URL via yt-dlp
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
        
        # Step 2: Download just the segment we need with ffmpeg
        dl_result = subprocess.run([
            "ffmpeg", "-ss", str(start), "-i", video_url,
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-c:a", "aac",
            "-y", input_file
        ], capture_output=True, text=True, timeout=300)
        
        if not os.path.exists(input_file) or os.path.getsize(input_file) < 1024:
            return jsonify({
                "error": "Failed to download video segment",
                "stderr": dl_result.stderr[-500:] if dl_result.stderr else "",
                "stdout": dl_result.stdout[-200:] if dl_result.stdout else ""
            }), 500
        
        input_size = os.path.getsize(input_file)
        
        # Step 3: Create 9:16 composite with ffmpeg
        # Top: facecam cropped from bottom-left of source (1080x480)
        # Bottom: chart from center-right of source (1080x1440)
        # Total: 1080x1920 (9:16)
        ffmpeg_result = subprocess.run([
            "ffmpeg", "-i", input_file,
            "-filter_complex",
            # Facecam: crop bottom-left 40% width x 40% height, scale to 1080x480
            "[0:v]crop=iw*0.4:ih*0.4:0:ih*0.6,scale=1080:480[face];"
            # Chart: crop right 80% width x 80% height, scale to 1080x1440
            "[0:v]crop=iw*0.8:ih*0.78:iw*0.15:ih*0.02,scale=1080:1440[chart];"
            # Stack vertically
            "[face][chart]vstack=inputs=2[out]",
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-y", output_file
        ], capture_output=True, text=True, timeout=600)
        
        if not os.path.exists(output_file) or os.path.getsize(output_file) < 1024:
            return jsonify({
                "error": "ffmpeg composite failed",
                "input_size": input_size,
                "stderr": ffmpeg_result.stderr[-500:] if ffmpeg_result.stderr else "",
                "returncode": ffmpeg_result.returncode
            }), 500
        
        # Step 4: Stream the result back
        file_size = os.path.getsize(output_file)
        
        def generate():
            with open(output_file, "rb") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    yield chunk
            # Cleanup
            for f_path in [input_file, output_file]:
                if os.path.exists(f_path):
                    os.remove(f_path)
            if os.path.exists(tmp_dir):
                os.rmdir(tmp_dir)
        
        return Response(
            generate(),
            content_type="video/mp4",
            headers={"Content-Length": str(file_size)}
        )
    except subprocess.TimeoutExpired as e:
        # Cleanup on timeout
        for f in [input_file, output_file]:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(tmp_dir):
            os.rmdir(tmp_dir)
        return jsonify({"error": f"Process timed out: {str(e)}"}), 504
    except Exception as e:
        # Cleanup on error
        for f in [input_file, output_file]:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(tmp_dir):
            os.rmdir(tmp_dir)
        return jsonify({"error": str(e)}), 500
