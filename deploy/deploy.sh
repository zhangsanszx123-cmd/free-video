#!/usr/bin/env bash
# Usage: bash deploy/deploy.sh [--local] IMAGE
# Direct-upload references use :sha256-<portable config digest> and require --local.
# receive-release.sh records the verified local store ID in deploy/releases/image-ids/.
set -Eeuo pipefail
local_only=false
if [[ "${1:-}" == '--local' ]]; then local_only=true; shift; fi
[[ $# -eq 1 ]] || { echo 'Usage: deploy.sh [--local] IMAGE' >&2; exit 2; }
image=$1
local_image() { [[ "$1" =~ ^ghcr\.io/zhangsanszx123-cmd/free-video:sha256-([a-f0-9]{64})$ ]]; }
valid_image() { [[ "$1" =~ ^ghcr\.io/zhangsanszx123-cmd/free-video(@sha256:|:sha256-)[a-f0-9]{64}$ ]]; }
verify_local_image() {
  local reference=$1 actual expected
  actual=$(docker image inspect --format '{{.Id}}' "$reference") || return 1
  if local_image "$reference"; then
    expected="sha256:${BASH_REMATCH[1]}"
    if [[ -s "/opt/projects/free-video/deploy/releases/image-ids/${BASH_REMATCH[1]}" ]]; then
      expected=$(cat "/opt/projects/free-video/deploy/releases/image-ids/${BASH_REMATCH[1]}")
    fi
    [[ "$actual" == "$expected" ]] || { echo 'Local image ID does not match its immutable reference' >&2; return 1; }
  fi
}
valid_image "$image" || { echo 'Unexpected image reference' >&2; exit 2; }
if local_image "$image" && ! "$local_only"; then
  echo 'Direct-upload image references require --local; registry pulls are disabled for this format' >&2
  exit 2
fi
cd /opt/projects/free-video
exec 9>deploy/.deploy.lock
flock -n 9 || { echo 'Another deployment is active'; exit 75; }
test -s deploy/runtime.env
test -s deploy/secrets/mysql-ca.pem
test -d storage/transcriptions && test -d storage/downloads
mkdir -p deploy/releases
compose() { APP_IMAGE="$1" docker compose -f docker-compose.yml "${@:2}"; }
previous=''
if [[ -s deploy/current-image ]]; then
  previous=$(cat deploy/current-image)
  valid_image "$previous" || { echo 'Recorded current image is invalid' >&2; exit 2; }
  if local_image "$previous"; then
    verify_local_image "$previous" || { echo 'Recorded rollback image is unavailable or invalid' >&2; exit 2; }
  fi
fi
# Pull and validate before disrupting the running version. Local rollback needs
# only a cached image, so it works without registry credentials or connectivity.
compose "$image" config --quiet
if "$local_only"; then
  verify_local_image "$image"
else
  compose "$image" pull app
fi
if compose "$image" up -d --no-build --pull never --wait --wait-timeout 180 app; then
  if [[ -n "$previous" && "$previous" != "$image" ]]; then printf '%s\n' "$previous" > deploy/previous-image; fi
  printf '%s\n' "$image" > deploy/current-image.tmp
  mv deploy/current-image.tmp deploy/current-image
  printf '%s %s\n' "$(date -u +%FT%TZ)" "$image" >> deploy/releases/history.log
  echo 'Deployment healthy'
else
  echo 'Deployment failed; restoring previous image'
  if [[ -n "$previous" ]]; then
    compose "$previous" up -d --no-build --pull never --wait --wait-timeout 180 app || { echo 'ROLLBACK FAILED: operator intervention required'; exit 2; }
  else
    compose "$image" stop app
    echo 'First deployment failed; no previous image exists'
  fi
  exit 1
fi
