# Creation Runtime Stabilization Implementation Plan

> **For agentic workers:** Execute one task at a time. Each task must pass its acceptance gate before the next task starts.

**Goal:** Make the creation and script entry flows reliable from local startup through automatic and guided script confirmation without breaking downstream consumers.

**Architecture:** Keep the existing React/Vite + FastAPI modular monolith and Provider Adapter seams. PostgreSQL remains the project fact source for formal runtime; memory is explicit test-only infrastructure. Generation commands return validated domain-shaped results, while the frontend renders persisted snapshots and generation events.

**Tech Stack:** React, TypeScript, Vite, FastAPI, Python 3.12, SQLAlchemy, PostgreSQL, Redis, Celery, pytest, HTTPX, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-04-creation-script-image-upload-design.md`, `docs/superpowers/specs/2026-09-03-generation-memory-and-provider-console-design.md`

## Global Constraints

- PostgreSQL is the formal project-state source of truth; Redis stores only queues, locks, events, and temporary generation state.
- `COMICFLOW_RUNTIME=memory` is explicit test infrastructure, never a silent production fallback.
- Automatic and guided generation use separate commands and state transitions.
- Provider Adapter output is normalized and validated before entering project state.
- No fixed story filler, unvalidated model response, or frontend-only workflow simulation.
- Do not modify storyboard, visual, audio, composition, or export behavior until the final integration gate passes.
- Every behavior change follows RED → GREEN → focused regression → full regression.

## Task 0: Local Startup and Creation Baseline

**Files:**
- Verify: `package.json`, `README.md`, `frontend/vite.config.ts`
- Verify: `backend/src/comicflow/api/app.py`
- Test: `backend/tests/test_local_http_flow.py`, `frontend/tests/e2e/create-project.spec.ts`

**Acceptance:**
- Frontend responds at `http://127.0.0.1:5173`.
- API `/health` responds 200.
- Automatic project creation and story generation respond without 5xx.
- Guided project creation and script generation respond without 5xx.
- Automatic project calling the guided script endpoint returns `WORKFLOW_MODE_MISMATCH`.
- Guided project calling the automatic story endpoint returns `WORKFLOW_MODE_MISMATCH`.
- No code change is required for this task unless startup itself is broken.

**Handoff:** Record exact commands, URLs, runtime mode, and baseline results. Any later failure must be attributable to a later task.

## Task 1: Durable Project Runtime and Recovery

**Files:**
- Modify: `backend/src/comicflow/api/app.py`
- Modify: `backend/src/comicflow/infrastructure/database.py`
- Modify: `backend/src/comicflow/infrastructure/memory.py`
- Modify: `backend/src/comicflow/production/interfaces.py`
- Modify: `frontend/src/api/client.ts`, `frontend/src/app/App.tsx`, `frontend/src/stores/workspace.ts`
- Test: new restart, project-list, and runtime-selection tests

**Acceptance:**
- Formal runtime uses PostgreSQL without silently falling back to memory.
- App import does not eagerly fail because an optional asset store is unconfigured.
- Creating a project, restarting API, and reading the same ID returns the same project state.
- Story text, script, generation session, versions, and reference-image metadata survive restart.
- `GET /api/projects` lists recoverable projects.
- Explicit memory tests still pass.
- Downstream commands receive the same persisted project shape before and after restart.

**Handoff:** A project created in this task is a valid input fixture for automatic and guided flow tasks.

## Task 2: Provider Contract Closure

**Files:**
- Modify: `backend/src/comicflow/providers/message_contract.py`
- Modify: `backend/src/comicflow/providers/bailian_text.py`
- Modify: `backend/src/comicflow/providers/runtime_config.py`
- Modify: `backend/src/comicflow/api/app.py`
- Test: provider contract, malformed response, adapter selection, and provider-test tests

**Acceptance:**
- Story, script, and guided-question responses share one strict normalized interface.
- Unknown envelope fields, invalid fields, invalid counts, invalid durations, and broken references are rejected.
- Guided metadata is preserved end to end.
- No unvalidated model object is persisted.
- Provider selection matches the configured adapter.
- Provider connection testing does not require a full production script.

**Handoff:** Both Mock and real-compatible adapters produce the exact objects consumed by Task 3 and Task 4.

## Task 3: Automatic Creation Vertical Slice

**Files:**
- Modify: generation command/session module and `ProductionPipeline`
- Modify: `frontend/src/features/create/CreateWorkspace.tsx`
- Test: automatic API, streaming, idempotency, retry, and Playwright tests

**Acceptance:**
- `create → story → edit/save story → script split → script editor` works.
- Streaming deltas are visible, cumulative chunks are not duplicated, and structured JSON is not shown as UI noise.
- Invalid streaming output uses the formal Provider repair path.
- Short output is regenerated or rejected; fixed filler is not used.
- Repeated requests do not duplicate cost, version, or provider calls.
- Saved story and split script survive refresh and are valid downstream inputs.

## Task 4: Guided Creation Vertical Slice

**Files:**
- Modify: generation session module and guided Provider calls
- Modify: `frontend/src/features/create/CreateWorkspace.tsx`
- Test: guidance metadata, answer, skip, early finish, cap, and Playwright tests

**Acceptance:**
- `create → draft script → adaptive question → answer/skip → detail script → edit/confirm` works.
- Guided mode never calls automatic story generation.
- Questions do not repeat completed targets and may finish before nine rounds.
- Empty transcript and skipped targets are valid detail-generation inputs.
- Detailed script incorporates saved draft and transcript.
- Refresh restores the exact guided session.

## Task 5: Script Domain and Editor Completion

**Files:**
- Modify: script validation and mutation methods in `ProductionPipeline`
- Modify: `frontend/src/features/script/ScriptWorkspace.tsx`, `frontend/src/api/client.ts`
- Test: scene/shot CRUD, ordering, validation, version conflict, and Playwright tests

**Acceptance:**
- Scene and shot add/copy/delete/reorder operations are available.
- IDs remain stable across reorder and references remain bidirectionally consistent.
- Field-level validation errors are returned and rendered.
- Save and confirm increment versions and preserve immutable script history.
- Confirmed output is consumable by the existing storyboard module.

## Task 6: Reference Image Upload and Recovery

**Files:**
- Modify: upload route and asset handling
- Modify: `frontend/src/api/client.ts`, `frontend/src/features/create/CreateWorkspace.tsx`
- Test: type, size, permission, progress, replacement, and restart-recovery tests

**Acceptance:**
- PNG/JPEG/WebP upload succeeds with metadata and progress states.
- Oversized or invalid files fail before unbounded memory use.
- Failed upload preserves story and script drafts.
- Replacing an image invalidates the old asset and preserves history.
- Reference metadata survives refresh and restart.

## Task 7: Final Creation-to-Production Gate

**Files:**
- Verify all creation, script, worker, and integration surfaces

**Acceptance:**
- Automatic and guided flows both reach confirmed-script state.
- Confirmed scripts pass existing storyboard/visual/audio entry contracts.
- PostgreSQL restart recovery passes.
- Mock and real-compatible Provider contract tests pass.
- Backend tests, Ruff, mypy, frontend typecheck/build, and Playwright all pass.
- No non-goal module regression is introduced.

## Execution Rule

Do not start a task whose handoff acceptance is not satisfied. A failed gate returns to root-cause investigation; it does not receive a second fallback path or a UI-only workaround.

## 验收状态（2026-09-06）

Task 0-7 门禁已在本地 Docker 正式栈（postgresql runtime）验收通过：全栈健康 + Alembic 迁移、infra smoke 1 passed、
pytest 130 passed / ruff / mypy / typecheck / build / Playwright 33 passed、automatic 与 import 两条主流程实测到
confirmed-script（storyboard-ready）、API 容器重启后项目/剧本/版本历史恢复。证据与命令见
`docs/release/2026-09-06-local-docker-stack-acceptance.md`。

注意：本计划中的 guided（Task 4）与创建页现状存在差异——创建页已收敛为 automatic + import 两个入口，
guided 仅对旧项目续聊（见 `docs/PROJECT_ENGINEERING_RULES.md` 09-05 决策与
`docs/superpowers/audits/2026-09-05-creation-flow-reverse-audit.md`）。guided 的完整移除属后续清理切片，不在本次收口范围。
