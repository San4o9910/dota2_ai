FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/hermes-venv UV_PYTHON_DOWNLOADS=never \
    HERMES_DISABLE_LAZY_INSTALLS=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.11.33
WORKDIR /opt/hermes
# Official supported source installation, with both source and dependency lock pinned.
RUN git init . && git remote add origin https://github.com/NousResearch/hermes-agent.git \
    && git fetch --depth=1 origin 9fd44b4dfc44138b9e5d5689acb56c438364ff7b \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = 9fd44b4dfc44138b9e5d5689acb56c438364ff7b \
    && git rev-parse HEAD > .narma-upstream-revision \
    && uv sync --frozen --no-dev --no-default-groups --python /usr/local/bin/python \
    && rm -rf .git /root/.cache/uv \
    && useradd --uid 10002 --create-home narma-hermes
WORKDIR /app
COPY services/hermes/server.py services/hermes/agent_task.py services/hermes/smoke.py ./
USER narma-hermes
EXPOSE 8092
CMD ["/opt/hermes-venv/bin/python", "/app/server.py"]
