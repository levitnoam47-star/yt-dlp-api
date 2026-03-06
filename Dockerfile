FROM python:3.11-slim
RUN apt-get update && apt-get install -y ffmpeg && pip install yt-dlp flask gunicorn requests
COPY server.py .
CMD ["gunicorn", "-b", "0.0.0.0:8080", "server:app"]
