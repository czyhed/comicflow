#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
: "${APP_VERSION:?APP_VERSION must be the release commit}"
: "${BACKEND_EXTERNAL_ENV:?Configure Drone secret backend_external_env with the external data configuration}"
# Never replace a developer's existing configuration when run locally.
test ! -e .env.server || { echo 'Refusing to overwrite existing .env.server' >&2; exit 1; }
umask 077
trap 'rm -f .env.server' EXIT HUP INT TERM
printf '%s\n' "$BACKEND_EXTERNAL_ENV" > .env.server
compose() {
    docker compose --env-file .env.server -f deploy/compose.external-data.yml \
        -f deploy/compose.external-production.yml -p comicflow-server "$@"
}
compose config --quiet
compose build api
docker network inspect comicflow-edge >/dev/null 2>&1 || docker network create comicflow-edge || docker network inspect comicflow-edge >/dev/null
# Read-only schema check: preserve the empty database reserved for data restore.
# Never initialize tables or migrate local project data as a deployment side effect.
compose run --rm --no-deps api alembic current --check-heads
if [ "${DEPLOY_WORKERS:-false}" = true ]; then
    # Explicit release opt-in after checking the server's queue and outbox.
    compose up -d --no-build --wait --wait-timeout 180 api worker beat
    # Containers without a healthcheck are considered started before Celery is ready.
    # Retry only the readiness probe, never a production/generation task.
    worker_probe_attempt=1
    until compose exec -T worker celery -A comicflow.worker.celery_app:celery_app inspect ping --timeout 10; do
        if [ "$worker_probe_attempt" -ge 6 ]; then
            echo 'Worker did not become ready after 6 probes; release verification failed.' >&2
            exit 1
        fi
        echo "Worker is not ready yet (probe $worker_probe_attempt/6); retrying in 5s."
        worker_probe_attempt=$((worker_probe_attempt + 1))
        sleep 5
    done
else
    compose up -d --no-build --wait --wait-timeout 180 api
fi
compose exec -T api python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/api/projects")'
compose ps
