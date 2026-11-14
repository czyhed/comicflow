# Task 12 Migration Evidence

Updated: 2026-09-03

## New-stack replacements

| Legacy area | New-stack replacement | Verification |
| --- | --- | --- |
| `src/production-pipeline.js` | `backend/src/comicflow/production/pipeline.py` | backend pipeline and contract tests |
| `src/web/server.js`, `src/web/start.js` | `backend/src/comicflow/api/app.py`, `frontend/` | HTTPX and Playwright |
| `src/worker/worker.js` | `backend/src/comicflow/worker/tasks.py` and `celery_app.py` | worker/outbox tests |
| `src/infrastructure/*` | `backend/src/comicflow/infrastructure/`, `backend/migrations/` | SQLAlchemy and migration tests |
| `src/providers/*` | `backend/src/comicflow/providers/` | adapter and media tests |
| `src/timeline.js`, `src/export-delivery.js` | `backend/src/comicflow/media/`, Pipeline export manifest | media and contract tests |
| `test/*.test.js` | `backend/tests/`, `frontend/tests/e2e/` | 23 Python tests and 2 Playwright flows |
| `prototype/`, `scripts/upgrade_*.js` | React/Vite workspace and no replacement scripts | legacy-boundary test |

## Deletion rule

The legacy files already marked deleted in Git remain deleted. No additional deletion is authorized until Docker-backed PostgreSQL/Redis/S3/Celery smoke verification passes. The active package scripts and Drone pipeline contain no legacy runtime command; this is enforced by `backend/tests/test_legacy_boundary.py`.

## Evidence status

- Local Mock HTTP contract, type, lint, build and browser verification: passed on 2026-09-02. `COMICFLOW_RUNTIME=memory` is explicit and production defaults remain PostgreSQL; Uvicorn `/health` was checked on port 18000.
- Review follow-up: SSE authorization now runs before response streaming; the HTTP flow covers script edit/confirm; export UI consumes the manifest and triggers a signed URL or manifest download.
- Local Docker services are available and healthy: PostgreSQL migration `0001_initial`, Redis `PONG`, MinIO health, PostgreSQL-backed API project creation (`201`), and Celery Worker Redis connection were verified.
- Docker-backed smoke test (`COMICFLOW_INFRA_SMOKE=1`) passed on 2026-09-03: transactional outbox dispatch, Celery task wrapper execution against PostgreSQL, export manifest publication, MinIO object checks, and authenticated export read. Beat scheduling and a live broker-consumer process remain operational checks rather than test assertions.
- Follow-up verification: live broker Worker consumption, concurrent job claim, duplicate settlement protection, MinIO object upload, read-time presigned URL refresh, expanded legacy boundary scan, and Beat startup passed. On 2026-09-03 the full local gate passed with 55 Python tests plus one opt-in smoke skip, six Playwright tests, Ruff, mypy, TypeScript, and Vite build; API/Worker/Beat restart health checks also passed.
- UI/runtime follow-up: the guest session id is persisted and injected as `X-User-Id`, project snapshots refresh while jobs run, and Compose now gates API/Worker/Beat on a one-shot Alembic `migrate` service. These changes pass TypeScript, Vite build, Python tests, Ruff, mypy, and Compose config validation.
- Real email, provider evaluation, HTTPS, backup/restore and server UAT: outside local task 12 evidence and remain task 08/09/11 acceptance work.
