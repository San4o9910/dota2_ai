FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jre-headless curl ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/narma/replay
COPY services/replay/bootstrap.py services/replay/dependencies.lock.json ./
COPY services/replay/src ./src
# Build installs the checksum-verified native Snappy library into the read-only image.
# /tmp can keep its noexec mount policy at runtime.
RUN python bootstrap.py && rm -rf tooling
WORKDIR /app
COPY services/video/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home narma && mkdir -p /var/lib/narma/video && chown narma:narma /var/lib/narma/video
COPY services/video/narma_video ./narma_video
COPY services/video/migrations ./migrations
USER narma
CMD ["python", "-m", "narma_video.replay_worker"]
