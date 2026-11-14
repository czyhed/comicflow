# Generation Memory and Provider Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让模型 API 控制台的文本配置实际驱动剧本生成，并为逐步/全自动生产、生成会话和历史剧本建立可恢复的本地持久化闭环。

**Architecture:** 在后端增加一个小而深的 ProviderConfigStore seam，隐藏文本 Provider 配置的运行时存储；API 层只返回掩码状态。项目 PostgreSQL 状态继续作为长期事实来源，生成会话和脚本版本以独立表保存并由项目 ID 关联；Celery 只传 ID。前端控制台通过后端接口保存配置，创建页读取 Provider 状态，Mock 作为未配置时的明确回退。

**Tech Stack:** FastAPI、SQLAlchemy async、PostgreSQL、Celery/Redis、React 19、React Query、Zustand、TypeScript、pytest、Playwright。

**Spec:** `docs/superpowers/specs/2026-09-03-generation-memory-and-provider-console-design.md`

## Global Constraints

- `PROVIDER_MODE=mock` remains the default when no enabled text configuration exists.
- API keys never enter browser storage, database, logs or Celery payloads in this phase.
- PostgreSQL is the durable source of truth; Redis/Celery carries queue and event delivery only.
- Do not claim real provider success without a configured endpoint and an integration test.
- Existing Mock flows and existing frontend routes must remain working.

---

### Task 1: Runtime Provider Configuration Store

**Files:**
- Create: `backend/src/comicflow/providers/runtime_config.py`
- Test: `backend/tests/test_runtime_provider_config.py`

**Interfaces:**
- Produces `ProviderConfigStore.configure_text(profile, api_key)`, `get_text()`, `masked_text()`, `clear_text()` and `text_enabled()`.
- `get_text()` is server-only and returns the key; `masked_text()` never returns it.

- [x] Write failing tests for configure/read/mask/clear and disabled behavior.
- [x] Run `uv run pytest backend/tests/test_runtime_provider_config.py -v` and verify failure.
- [x] Implement an in-process store with immutable copies and masked key output.
- [x] Run the focused tests and `uv run ruff check backend/src/comicflow/providers/runtime_config.py backend/tests/test_runtime_provider_config.py`.

### Task 2: Provider Configuration HTTP Interface

**Files:**
- Modify: `backend/src/comicflow/api/schemas.py`
- Modify: `backend/src/comicflow/api/app.py`
- Test: `backend/tests/test_provider_config_api.py`

**Interfaces:**
- Adds `GET /api/provider-config`, `PUT /api/provider-config/text`, `POST /api/provider-config/text/test`, `DELETE /api/provider-config/text`.
- GET returns provider/baseUrl/model/timeout/enabled/configured/apiKeyMasked only.
- PUT accepts the key but never echoes it; test endpoint performs one adapter request through an injected transport.

- [x] Write failing HTTP tests for redacted GET, save, delete, invalid input and test connection failure.
- [x] Run the focused tests and verify failure.
- [x] Implement schemas, a runtime store dependency on `Runtime`, and endpoint error mapping.
- [x] Run focused tests, Ruff and mypy.

### Task 3: Text Provider Runtime Selection

**Files:**
- Modify: `backend/src/comicflow/infrastructure/memory.py`
- Modify: `backend/src/comicflow/api/app.py`
- Modify: `backend/src/comicflow/production/pipeline.py`
- Test: `backend/tests/test_runtime_text_generation.py`

**Interfaces:**
- `Runtime` exposes the shared `ProviderConfigStore` and a text-provider factory seam.
- Script generation uses configured text Provider only when enabled; otherwise uses Mock.
- Provider errors map to `PROVIDER_NOT_CONFIGURED`, `PROVIDER_AUTH_FAILED`, `PROVIDER_TIMEOUT`, `PROVIDER_UNAVAILABLE`, or `PROVIDER_INVALID_RESPONSE`.

- [x] Write failing tests proving configured text Provider is selected and unconfigured mode uses Mock.
- [x] Run the focused tests and verify failure.
- [x] Implement runtime selection without passing API keys through job payloads.
- [x] Run focused tests and the existing script/pipeline tests.

### Task 4: Frontend Console Integration

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/components/ModelApiSettings.tsx`
- Modify: `frontend/src/features/create/CreateWorkspace.tsx`
- Modify: `frontend/src/model-api.ts`
- Test: `frontend/tests/e2e/model-api-console.spec.ts`

**Interfaces:**
- Console reads/writes only through the provider-config endpoints.
- API keys are held only in the form while editing and are cleared on close/save.
- Create page displays the active text Provider mode and uses the backend-selected Provider.

- [x] Write failing Playwright tests for save, masked status, connection test and create-page status.
- [x] Run the focused tests and verify failure.
- [x] Implement query/mutation state, validation, success/error feedback and remove localStorage as the source of truth.
- [x] Run focused Playwright, TypeScript and Vite build.

### Task 5: Script Versions and Generation Sessions

**Files:**
- Modify: `backend/src/comicflow/infrastructure/database.py`
- Modify: `backend/migrations/versions/0001_initial.py` or add a new migration
- Modify: `backend/src/comicflow/production/pipeline.py`
- Modify: `backend/src/comicflow/api/app.py`
- Test: `backend/tests/test_script_history.py`

**Interfaces:**
- Adds durable `script_versions` and `generation_sessions` records keyed by project ID.
- Adds `GET /api/projects`, `GET /api/projects/{project_id}/versions`, and `POST /api/projects/{project_id}/duplicate`.
- Script confirmation creates an immutable version; session snapshots expose stage/status/retry metadata.

- [x] Write failing repository/API tests for version creation, history listing, duplicate isolation and session snapshot.
- [x] Run focused tests and verify failure.
- [x] Implement project-state version/session methods and pipeline checkpoint writes.
- [x] Run focused tests and existing project flow tests.

### Task 6: Guided and Automatic Session Control

**Files:**
- Modify: `backend/src/comicflow/worker/tasks.py`
- Modify: `backend/src/comicflow/worker/celery_app.py`
- Modify: `backend/src/comicflow/production/pipeline.py`
- Modify: `backend/src/comicflow/api/app.py`
- Test: `backend/tests/test_generation_sessions.py`
- Test: `frontend/tests/e2e/production-flow.spec.ts`

**Interfaces:**
- Guided mode stops at confirmation checkpoints.
- Automatic mode advances persisted stages through Celery using project/session IDs only.
- Adds pause/cancel/retry/resume operations with idempotent version checks.

- [ ] Write failing tests for automatic stage advancement through Celery, plus pause/resume, cancel and retry.
- [ ] Run focused tests and verify failure.
- [x] Implement the session control surface around existing pipeline stages (pause/resume/cancel/retry).
- [x] Run focused backend tests for the implemented session controls.
- [x] Implement and verify multi-stage automatic Celery orchestration in a follow-up slice.

### Task 7: Full Verification and Documentation

**Files:**
- Modify: `docs/release/task-08-readiness.md`
- Modify: `.scratch/ai-manhua-drama/issues/08-identity-credits-and-release-readiness.md`
- Read: all changed implementation and test files

- [x] Run `uv run pytest`, `uv run ruff check backend/src backend/tests`, `uv run mypy`.
- [x] Run `pnpm --dir frontend typecheck`, `pnpm --dir frontend build`, and full Playwright.
- [x] Run Docker smoke with `COMICFLOW_INFRA_SMOKE=1` and apply migrations.
- [x] Review diff for secrets, generated schedules and deployment changes.
- [x] Record only verified local behavior and leave real-provider credentials/evaluation explicitly external.
