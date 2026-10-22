#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Local verification only. Never pushes or requires a registry.
for ARCH in amd64 arm64; do
  docker buildx build --platform "linux/$ARCH" --load --tag "immich-album-relay:verify-$ARCH" .
  docker run --rm --platform "linux/$ARCH" "immich-album-relay:verify-$ARCH" --help >/dev/null
  docker run --rm --platform "linux/$ARCH" --entrypoint python "immich-album-relay:verify-$ARCH" \
    -c 'from zoneinfo import ZoneInfo; from immich_album_relay.config import Config; print(ZoneInfo("America/Phoenix"))'
done
