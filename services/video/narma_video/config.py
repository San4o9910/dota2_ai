import os
from pathlib import Path

PART_BYTES = 5 * 1024 * 1024
MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024
MAX_FRAMES = 432000
MAX_DURATION = 7200

def database_url():
    value = os.environ.get("DATABASE_URL", "")
    if not value.startswith(("postgres://", "postgresql://")):
        raise RuntimeError("DATABASE_URL must point to PostgreSQL")
    return value

def media_root():
    root = Path(os.environ.get("VIDEO_STORAGE_PATH", "/var/lib/narma/video")).resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root

def job_directory(job_id):
    from uuid import UUID
    return media_root() / str(UUID(str(job_id)))

def service_token():
    token = os.environ.get("VIDEO_SERVICE_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("VIDEO_SERVICE_TOKEN must contain at least 32 characters")
    return token
