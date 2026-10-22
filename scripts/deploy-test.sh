#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${RELAY_TEST_DIR:-$(dirname "$ROOT")/immich-album-relay_test}"
python3 "$ROOT/scripts/sync-test.py" "$TARGET"
cd "$TARGET"
docker buildx build --load --tag immich-album-relay-test:local .
# Do not fabricate a usable private configuration or start with fictional credentials.
if [[ ! -f config.yml || ! -f .env ]]; then
  echo 'Image built. Live startup blocked: create private config.yml and .env using the synchronized examples.' >&2
  exit 2
fi
COMPOSE=(docker compose -p immich-album-relay-test -f compose.yml -f compose.test.yml)
"${COMPOSE[@]}" run --rm --no-deps relay validate --offline
"${COMPOSE[@]}" up -d --force-recreate --no-build relay
for ((attempt=0; attempt<30; attempt++)); do
  STATUS="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' immich-album-relay_test)"
  if [[ "$STATUS" == 'running healthy' ]]; then
    echo 'Deployment verified: immich-album-relay_test is running and healthy.'
    exit 0
  fi
  if [[ "$STATUS" == exited* || "$STATUS" == dead* ]]; then
    echo 'Deployment failed: test container exited; inspect its logs locally.' >&2
    exit 1
  fi
  sleep 2
done
echo "Deployment failed health verification: $STATUS" >&2
exit 1
