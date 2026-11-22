#!/usr/bin/env bash
# Receive a gzip-compressed docker-save archive, then apply it in a separate call.
# Usage: receive-release.sh receive|apply|status TRANSFER_ID IMAGE IMAGE_ID ARCHIVE_SHA
set -Eeuo pipefail
umask 077
[[ $# -eq 5 ]] || { echo 'Usage: receive-release.sh receive|apply|status TRANSFER_ID IMAGE IMAGE_ID ARCHIVE_SHA' >&2; exit 64; }
mode=$1 transfer_id=$2 image=$3 image_id=$4 archive_sha=$5
[[ "$mode" == receive || "$mode" == apply || "$mode" == status ]] || { echo 'Unexpected receiver mode' >&2; exit 64; }
[[ "$transfer_id" =~ ^[a-f0-9]{32}$ ]] || { echo 'Unexpected transfer ID' >&2; exit 64; }
[[ "$image" =~ ^ghcr\.io/zhangsanszx123-cmd/free-video:sha256-([a-f0-9]{64})$ ]] || { echo 'Unexpected direct-upload image reference' >&2; exit 64; }
[[ "$image_id" == "sha256:${BASH_REMATCH[1]}" && "$archive_sha" =~ ^[a-f0-9]{64}$ ]] || { echo 'Unexpected image ID or archive checksum' >&2; exit 64; }
cd /opt/projects/free-video
stage="deploy/releases/.incoming-$transfer_id"
archive="$stage/image.tar.gz"
expected_metadata=$(printf 'image=%s\nimage_id=%s\narchive_sha=%s' "$image" "$image_id" "$archive_sha")
# image_id is the portable config digest; containerd image stores report a different local ID.
local_id_file="deploy/releases/image-ids/${image_id#sha256:}"

expected_local_id() {
  if [[ -s "$local_id_file" ]]; then cat "$local_id_file"; else printf '%s\n' "$image_id"; fi
}
image_matches() {
  local actual
  actual=$(docker image inspect --format '{{.Id}}' "$image" 2>/dev/null) || return 1
  [[ "$actual" == "$(expected_local_id)" ]]
}
loaded_config_matches() {
  local actual
  actual=$(docker image save --platform linux/amd64 "$image" | python3 deploy/image-config-id.py -) || return 1
  [[ "$actual" == "$image_id" ]]
}
record_local_id() {
  local actual
  actual=$(docker image inspect --format '{{.Id}}' "$image") || return 1
  [[ "$actual" =~ ^sha256:[a-f0-9]{64}$ ]] || return 1
  mkdir -p deploy/releases/image-ids
  printf '%s\n' "$actual" > "$local_id_file.tmp.$$"
  mv -- "$local_id_file.tmp.$$" "$local_id_file"
}
application_healthy() {
  local container state
  [[ -f deploy/current-image && "$(cat deploy/current-image)" == "$image" ]] || return 1
  image_matches || return 1
  container=$(APP_IMAGE="$image" docker compose -f docker-compose.yml ps --all --quiet app 2>/dev/null) || return 1
  [[ -n "$container" ]] || return 1
  state=$(docker inspect --format '{{.Image}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container" 2>/dev/null) || return 1
  [[ "$state" == "$(expected_local_id) running healthy" ]]
}
deployed_healthy() {
  [[ -f "$stage/applied" && "$(cat "$stage/applied")" == "$expected_metadata" ]] || return 1
  application_healthy
}
received_matches() {
  [[ ! -L "$stage" && -f "$archive" && -f "$stage/received" && -f "$stage/metadata" ]] || return 1
  [[ "$(cat "$stage/metadata")" == "$expected_metadata" && "$(cat "$stage/received")" == "$archive_sha" ]]
}
verify_archive() {
  printf '%s  %s\n' "$archive_sha" "$archive" | sha256sum --check --status
}

if [[ "$mode" == status ]]; then
  if deployed_healthy; then printf 'deployed\n'; exit 0; fi
  if received_matches; then printf 'received\n'; exit 1; fi
  printf 'missing\n'
  exit 2
fi

mkdir -p deploy/releases
[[ ! -L "$stage" ]] || { echo 'Transfer staging path must not be a symlink' >&2; exit 64; }
mkdir -p -- "$stage"
chmod 700 -- "$stage"

if [[ "$mode" == receive ]]; then
  # Pin the metadata briefly; parallel retry uploads get independent partial files.
  exec 8>"$stage/.metadata.lock"
  flock -w 10 8 || { echo 'Transfer metadata is busy' >&2; exit 75; }
  if [[ -f "$stage/metadata" ]]; then
    [[ "$(cat "$stage/metadata")" == "$expected_metadata" ]] || { echo 'Transfer ID is already associated with another release' >&2; exit 64; }
  else
    printf '%s\n' "$expected_metadata" > "$stage/metadata.tmp.$$"
    mv -- "$stage/metadata.tmp.$$" "$stage/metadata"
  fi
  flock -u 8
  exec 8>&-
  partial=$(mktemp "$stage/image.tar.gz.partial.$$.XXXXXXXX")
  cleanup_receive() { rm -f -- "$partial"; }
  trap cleanup_receive EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM HUP
  # A lost SSH connection or stalled sender cannot retain a partial indefinitely.
  timeout --foreground 2400s cat > "$partial"
  printf '%s  %s\n' "$archive_sha" "$partial" | sha256sum --check --status || { echo 'Received archive checksum does not match' >&2; exit 65; }
  mv -- "$partial" "$archive"
  printf '%s\n' "$archive_sha" > "$stage/received.tmp.$$"
  mv -- "$stage/received.tmp.$$" "$stage/received"
  printf 'received\n'
  exit 0
fi

[[ -f "$stage/metadata" && "$(cat "$stage/metadata")" == "$expected_metadata" ]] || { echo 'Release transfer metadata is missing or mismatched' >&2; exit 66; }
# The transport may retry after this transfer finished and deleted its archive.
if deployed_healthy; then printf 'deployed\n'; exit 0; fi
exec 7>deploy/releases/.release.lock
flock -n 7 || { echo 'Another release apply is active' >&2; exit 75; }
if deployed_healthy; then printf 'deployed\n'; exit 0; fi
cleanup_apply() {
  local exit_code=$?
  # A competing deployment is retryable; keep the verified archive available.
  if [[ "$exit_code" -ne 75 ]]; then rm -f -- "$archive" "$stage/received"; fi
  return "$exit_code"
}
trap cleanup_apply EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

if ! image_matches; then
  # An already-loaded image without a recorded local ID can be adopted after content verification.
  if [[ -s "$local_id_file" ]] || ! docker image inspect "$image" >/dev/null 2>&1 || ! loaded_config_matches; then
    received_matches || { echo 'Verified release archive is missing' >&2; exit 66; }
    verify_archive || { echo 'Stored release archive checksum does not match' >&2; exit 65; }
    [[ "$(python3 deploy/image-config-id.py "$archive")" == "$image_id" ]] || { echo 'Release archive config digest does not match' >&2; exit 65; }
    if ! timeout --foreground 600s docker image load --input "$archive" > "$stage/load.log" 2>&1; then
      echo 'Image import failed; deployment was not started' >&2
      exit 1
    fi
    loaded_config_matches || { echo 'Imported image config does not match the requested release' >&2; exit 65; }
  fi
  record_local_id || { echo 'Cannot record the local image ID' >&2; exit 1; }
  image_matches || { echo 'Imported image ID does not match the requested release' >&2; exit 65; }
fi
# deploy.sh holds its own independent deployment lock and performs rollback.
bash deploy/deploy.sh --local "$image"
application_healthy || { echo 'Release did not reach the expected healthy state' >&2; exit 1; }
printf '%s\n' "$expected_metadata" > "$stage/applied.tmp.$$"
mv -- "$stage/applied.tmp.$$" "$stage/applied"
printf 'deployed\n'
