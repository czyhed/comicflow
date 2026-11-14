#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
: "${APP_VERSION:?APP_VERSION must be the release commit}"

# Secrets are written at runtime, never passed as Docker build arguments.
if [ -n "${BACKEND_ENV:-}" ]; then
    umask 077
    trap 'rm -f deploy/runtime.env' EXIT HUP INT TERM
    printf '%s\n' "$BACKEND_ENV" > deploy/runtime.env
fi
test -s deploy/runtime.env || { echo 'Configure the backend_env Drone secret first.' >&2; exit 1; }

compose() {
    docker compose --env-file deploy/runtime.env -f deploy/compose.backend.yml -p comicflow-backend "$@"
}
compose config --quiet
# Reuse cached base images; missing images still require registry access.
compose build
docker network inspect comicflow-edge >/dev/null 2>&1 || docker network create comicflow-edge || docker network inspect comicflow-edge >/dev/null
compose up -d --wait --wait-timeout 180 postgres redis object-store
compose run --rm --no-deps object-store-init
compose run --rm --no-deps migrate
compose up -d --no-build --wait --wait-timeout 180 api worker beat
compose ps
