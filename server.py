from flask import Flask, request, jsonify, send_file
import subprocess
import os
import tempfile
import uuid

app = Flask(__name__)
cookies_path = "/app/cookies.txt"

def get_cookies_flag():
    if os.path.exists(cookies_path):
        try:
            with open(cookies_path, "r", encoding="utf-8", errors="ignore") as f:
                if "Netscape HTTP Cookie File" in f.read(256):
                    return ["--cookies", cookies_path]
        except Exception:
            pass
    return []

def get_direct_url(video_url):
    base_cmd = ["yt-dlp", "-f", "best[ext=mp4]", "--get-url"]
    yt_result = subprocess.run(
        base_cmd + get_cookies_flag() + [video_url],
        capture_output=True, text=True, timeout=60
    )
    if yt_result.returncode != 0 and "does not look like a Netscape" in (yt_result.stderr or ""):
        yt_result = subprocess.run(
            base_cmd + [video_url],
            capture_output=True, text=True, timeout=60
        )
    if yt_result.returncode != 0:
        raise Exception(f"yt-dlp failed: {yt_result.stderr[-500:]}")
    return yt_result.stdout.strip()

def detect_facecam_corner(direct_url, start_sec):
    """Auto-detect which corner has the facecam by comparing JPEG sizes of each corner crop."""
    tmp = tempfile.gettempdir()
    detect_id = str(uuid.uuid4())[:8]

    # Define 4 corners: (x, y) as fractions
    corners = {
        "bottom_left":  ("0",         "ih*0.55"),
        "bottom_right": ("iw*0.73",   "ih*0.55"),
        "top_left":     ("0",         "0"),
        "top_right":    ("iw*0.73",   "0"),
    }
    corner_w = "iw*0.27"
    corner_h = "ih*0.35"

    best_corner = "bottom_left"
    best_size = 0

    for name, (cx, cy) in corners.items():
        out_path = os.path.join(tmp, f"detect_{detect_id}_{name}.jpg")
        cmd = [
            "ffmpeg", "-y", "-ss", str(start_sec),
            "-i", direct_url,
            "-frames:v", "1",
            "-vf", f"crop={corner_w}:{corner_h}:{cx}:{cy}",
            "-q:v", "5",
            out_path
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if os.path.exists(out_path):
                size = os.path.getsize(out_path)
                if size > best_size:
                    best_size = size
                    best_corner = name
                os.remove(out_path)
        except Exception:
            if os.path.exists(out_path):
                os.remove(out_path)

    return best_corner

def get_filter_complex(corner):
    """Build FFmpeg filter based on detected facecam corner."""
    # Facecam crop params per corner
    face_crops = {
        "bottom_left":  "crop=iw*0.27:ih*0.30:0:ih*0.55",
        "bottom_right": "crop=iw*0.27:ih*0.30:iw*0.73:ih*0.55",
        "top_left":     "crop=iw*0.27:ih*0.30:0:0",
        "top_right":    "crop=iw*0.27:ih*0.30:iw*0.73:0",
    }
    # Chart crop: exclude the facecam corner
    chart_crops = {
        "bottom_left":  "crop=iw*0.73:ih*0.87:iw*0.25:ih*0.05",
        "bottom_right": "crop=iw*0.73:ih*0.87:iw*0.02:ih*0.05",
        "top_left":     "crop=iw*0.73:ih*0.87:iw*0.25:ih*0.10",
        "top_right":    "crop=iw*0.73:ih*0.87:iw*0.02:ih*0.10",
    }

    face_crop = face_crops.get(corner, face_crops["bottom_left"])
    chart_crop = chart_crops.get(corner, chart_crops["bottom_left"])

    return (
        f"[0:v]split=2[v1][v2];"
        f"[v1]{face_crop},scale=1080:570[face];"
        f"[v2]{chart_crop},scale=1080:1350[chart];"
        f"[face][chart]vstack=inputs=2[out]"
    )

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

    try:
        direct_url = get_direct_url(video_url)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Auto-detect facecam position
    try:
        corner = detect_facecam_corner(direct_url, int(start))
        print(f"Detected facecam at: {corner}")
    except Exception as e:
        print(f"Facecam detection failed, defaulting to bottom_left: {e}")
        corner = "bottom_left"

    filter_complex = get_filter_complex(corner)

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
