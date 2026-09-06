#!/usr/bin/env bash
set -euo pipefail
stage=lock
trap 'code=$?; printf "NARMA_BOOTSTRAP_FAILURE:%s:%s\n" "$stage" "$code" >&2' ERR
mark_stage() { stage="$1"; printf 'NARMA_BOOTSTRAP_STAGE:%s\n' "$stage"; }
exec 9>/var/lock/narma-deploy.lock
flock -n 9
[[ "$1" =~ ^[0-9a-f]{40}$ ]]
release="/opt/narma/releases/$1"
export DEBIAN_FRONTEND=noninteractive
mark_stage cloud_init
timeout 180 cloud-init status --wait >/dev/null
mark_stage packages
apt-get update -qq
apt-get install -y -qq docker.io docker-compose-v2 ufw ca-certificates
mark_stage docker_firewall
systemctl enable --now docker
ufw allow 22/tcp
ufw --force enable
cd "$release/services/video"
compose=(docker compose --project-name narma-video --env-file /opt/narma/secrets/video.env)
mark_stage stop_worker
"${compose[@]}" --profile analysis stop worker
mark_stage build
"${compose[@]}" build
mark_stage database_api
"${compose[@]}" up -d db migrate api
mark_stage readiness
for attempt in {1..40}; do
  if "${compose[@]}" exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=15).close()"; then
    [[ -z "$("${compose[@]}" --profile analysis ps --status running --quiet worker)" ]]
    ln -sfn "$release" /opt/narma/current
    mark_stage ready
    exit 0
  fi
  sleep 5
done
printf 'NARMA_BOOTSTRAP_FAILURE:readiness:1\n' >&2
exit 1
