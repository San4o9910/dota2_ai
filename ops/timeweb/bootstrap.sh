#!/usr/bin/env bash
set -euo pipefail
exec 9>/var/lock/narma-deploy.lock
flock -n 9
[[ "$1" =~ ^[0-9a-f]{40}$ ]]
release="/opt/narma/releases/$1"
export DEBIAN_FRONTEND=noninteractive
timeout 180 cloud-init status --wait >/dev/null
apt-get update -qq
apt-get install -y -qq docker.io docker-compose-v2 ufw ca-certificates
systemctl enable --now docker
ufw allow 22/tcp
ufw --force enable
cd "$release/services/video"
compose=(docker compose --project-name narma-video --env-file /opt/narma/secrets/video.env)
"${compose[@]}" --profile analysis stop worker
"${compose[@]}" build
"${compose[@]}" up -d db migrate api
for attempt in {1..40}; do
  if "${compose[@]}" exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=15).close()"; then
    [[ -z "$("${compose[@]}" --profile analysis ps --status running --quiet worker)" ]]
    ln -sfn "$release" /opt/narma/current
    exit 0
  fi
  sleep 5
done
exit 1
