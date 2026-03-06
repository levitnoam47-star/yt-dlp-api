FROM python:3.11-slim
RUN pip install yt-dlp flask gunicorn requests
RUN apt-get update && apt-get install -y ffmpeg && pip install yt-dlp flask gunicorn
COPY server.py .
EXPOSE 8080
CMD ["gunicorn", "-b", "0.0.0.0:8080", "--timeout", "120", "server:app"]
