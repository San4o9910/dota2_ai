FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home narma && mkdir -p /var/lib/narma/video && chown narma:narma /var/lib/narma/video
COPY narma_video ./narma_video
COPY migrations ./migrations
USER narma
CMD ["uvicorn", "narma_video.api:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
