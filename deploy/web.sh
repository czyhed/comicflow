#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
: "${APP_VERSION:?APP_VERSION must be the release commit}"
compose() {
    docker compose -f deploy/compose.web.yml -p comicflow-web "$@"
}
compose config --quiet
# Reuse cached base images; missing images still require registry access.
compose build
docker network inspect comicflow-edge >/dev/null 2>&1 || docker network create comicflow-edge || docker network inspect comicflow-edge >/dev/null
compose up -d --no-build --wait --wait-timeout 90
compose exec -T web wget -q -O /dev/null http://127.0.0.1/health
compose ps
