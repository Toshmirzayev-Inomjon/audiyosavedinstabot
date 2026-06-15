FROM mwader/static-ffmpeg:7.1 AS ffmpeg
FROM cloudflare/cloudflared:latest AS cloudflared
FROM denoland/deno:bin-2.8.3 AS deno

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /ffprobe /usr/local/bin/ffprobe
COPY --from=cloudflared /usr/local/bin/cloudflared /usr/local/bin/cloudflared
COPY --from=deno /deno /usr/local/bin/deno

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY bot ./bot
RUN mkdir -p /app/data /app/tmp

CMD ["python", "-m", "app.main"]
