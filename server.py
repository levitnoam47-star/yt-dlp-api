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
    input_file = os.path.join(tmp_dir, "input.mp4")
    output_file = os.path.join(tmp_dir, f"{uuid.uuid4()}.mp4")
    
    try:
        # Step 1: Download the clip segment with yt-dlp
        dl_result = subprocess.run([
            "yt-dlp", "-f", "best[ext=mp4]",
            "--download-sections", f"*{start}-{int(start)+int(duration)}",
            "-o", input_file,
            url
        ], capture_output=True, text=True, timeout=120)
        
        if not os.path.exists(input_file):
            # Fallback: download full and trim with ffmpeg
            direct = subprocess.run(["yt-dlp", "-f", "best[ext=mp4]", "-g", url], capture_output=True, text=True)
            video_url = direct.stdout.strip()
            if not video_url:
                return jsonify({"error": "Could not get video URL"}), 400
            
            subprocess.run([
                "ffmpeg", "-ss", start, "-i", video_url, "-t", duration,
                "-c", "copy", input_file
            ], capture_output=True, timeout=120)
        
        if not os.path.exists(input_file):
            return jsonify({"error": "Failed to download video segment"}), 500
        
        # Step 2: Create 9:16 composite with ffmpeg
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
        ], capture_output=True, text=True, timeout=300)
        
        if not os.path.exists(output_file):
            return jsonify({
                "error": "ffmpeg failed",
                "stderr": ffmpeg_result.stderr[-500:] if ffmpeg_result.stderr else ""
            }), 500
        
        # Step 3: Stream the result back
        def generate():
            with open(output_file, "rb") as f:
                while chunk := f.read(8192):
                    yield chunk
            # Cleanup
            os.remove(output_file)
            os.remove(input_file)
            os.rmdir(tmp_dir)
        
        file_size = os.path.getsize(output_file)
        return Response(
            generate(),
            content_type="video/mp4",
            headers={"Content-Length": str(file_size)}
        )
    except Exception as e:
        # Cleanup on error
        for f in [input_file, output_file]:
            if os.path.exists(f):
                os.remove(f)
        if os.path.exists(tmp_dir):
            os.rmdir(tmp_dir)
        return jsonify({"error": str(e)}), 500
