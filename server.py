@app.route("/composite", methods=["GET"])
def composite():
    """Create 9:16 composite: facecam on top, chart on bottom — 1080x1920"""
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
            direct = subprocess.run(
                ["yt-dlp", "-f", "best[ext=mp4]", "-g", url],
                capture_output=True, text=True, timeout=60
            )
            video_url = direct.stdout.strip()

        if not video_url:
            return jsonify({"error": "Could not get video URL"}), 400

        # Step 2: Download segment + create 1080x1920 composite in ONE ffmpeg pass
        #
        # Source layout (16:9 trading stream):
        # ┌──────────────────────────────┐
        # │  Toolbar                     │ ← top ~5%
        # │  ┌────────────────────────┐  │
        # │  │                        │  │
        # │  │     CHART AREA         │  │
        # │  │                        │  │
        # │  │                        │  │
        # │  ├──────┐                 │  │
        # │  │FACE  │                 │  │
        # │  │CAM   │                 │  │
        # │  └──────┴─────────────────┘  │
        # │  Bottom indicators           │ ← bottom ~8%
        # └──────────────────────────────┘
        #
        # Facecam: bottom-left ~25% width, ~30% height
        # Chart: center area excluding facecam, toolbars, indicators
        
        ffmpeg_result = subprocess.run([
            "ffmpeg",
            "-ss", str(start),
            "-i", video_url,
            "-t", str(duration),
            "-filter_complex",
            # Split input once to avoid double decode
            "[0:v]split=2[v1][v2];"
            # FACECAM: crop bottom-left corner only
            # crop=width:height:x:y
            # 25% of width, 28% of height, starting at x=0, y=72% from top
            "[v1]crop=iw*0.25:ih*0.28:0:ih*0.72,scale=1080:570[face];"
            # CHART: crop the main chart area
            # Remove left 25% (facecam), top 5% (toolbar), bottom 8% (indicators)
            # Take from x=25% of width, y=5% from top, width=73%, height=87%
            "[v2]crop=iw*0.73:ih*0.87:iw*0.25:ih*0.05,scale=1080:1350[chart];"
            # Stack vertically = 1080x1920 (9:16)
            "[face][chart]vstack=inputs=2[out]",
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-threads", "2",
            "-y", output_file
        ], capture_output=True, text=True, timeout=600)

        if not os.path.exists(output_file) or os.path.getsize(output_file) < 1024:
            return jsonify({
                "error": "ffmpeg composite failed",
                "stderr": ffmpeg_result.stderr[-500:] if ffmpeg_result.stderr else "",
                "returncode": ffmpeg_result.returncode
            }), 500

        file_size = os.path.getsize(output_file)

        def generate():
            with open(output_file, "rb") as f:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    yield chunk
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
