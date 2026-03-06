FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Deno (recommended JS runtime for yt-dlp)
RUN curl -fsSL https://deno.land/install.sh | sh
ENV DENO_DIR="/root/.deno"
ENV PATH="${DENO_DIR}/bin:${PATH}"

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir flask yt-dlp gunicorn

WORKDIR /app
COPY . .

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "600", "--workers", "2", "server:app"]
