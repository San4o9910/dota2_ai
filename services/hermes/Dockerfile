FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/hermes-venv UV_PYTHON_DOWNLOADS=never \
    HERMES_DISABLE_LAZY_INSTALLS=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.11.33
COPY services/hermes/fetch_source.py /usr/local/lib/narma-fetch-hermes.py
WORKDIR /opt/hermes
# Exact official commit/tree and frozen dependency lock. Auth is a temporary
# BuildKit mount, never an ARG, image ENV, repository config or logged command.
RUN --mount=type=secret,id=github_token,required=true \
    --mount=type=cache,id=narma-hermes-source-9fd44b4,target=/var/cache/narma-hermes-git,sharing=locked \
    python /usr/local/lib/narma-fetch-hermes.py --cache /var/cache/narma-hermes-git --destination /opt/hermes
RUN uv sync --frozen --no-dev --no-default-groups --python /usr/local/bin/python \
    && rm -rf /root/.cache/uv \
    && useradd --uid 10002 --create-home narma-hermes
WORKDIR /app
COPY services/hermes/server.py services/hermes/agent_task.py services/hermes/smoke.py ./
USER narma-hermes
EXPOSE 8092
CMD ["/opt/hermes-venv/bin/python", "/app/server.py"]
