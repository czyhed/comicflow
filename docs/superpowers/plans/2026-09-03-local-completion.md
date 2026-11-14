# Local Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 完成本地 ComicFlow 运行闭环并取得新鲜、可复现的验证证据；Drone、Tag 和服务器发布不在本计划范围内。

**Architecture:** 保持现有 React/Vite + FastAPI + Celery + PostgreSQL/Redis/MinIO 架构与 Mock-first Provider 策略。先验证基础设施和迁移，再验证 API/Worker/导出及前端流程，最后补齐本地 UAT 文档与状态记录。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy、Celery、PostgreSQL、Redis、MinIO、React 19、Vite、Playwright、pytest、Ruff、mypy、TypeScript。

**Spec:** `.scratch/ai-manhua-drama/spec.md`、`docs/release/task-08-readiness.md`、`docs/release/task-12-migration-evidence.md`

## Global Constraints

- `PROVIDER_MODE=mock` 在真实 Provider 评测前保持不变。
- PostgreSQL 是业务事实来源；Redis/Celery 只负责队列和事件传递。
- 不提交 API key、生产 Secret 或运行时生成的 `celerybeat-schedule.*` 文件。
- Drone、Tag、HTTPS、服务器备份恢复和线上 UAT 延后到部署阶段。

---

### Task 1: Fresh Local Regression

**Files:**
- Read: `docker-compose.yml`, `README.md`, `backend/tests/`, `frontend/tests/e2e/`
- Test: existing backend and frontend test suites

**Interfaces:**
- Consumes: current Compose services and project test commands.
- Produces: fresh pass/fail evidence for infrastructure, backend, frontend, lint, types and build.

- [x] **Step 1: Start or verify local dependencies**

Run `docker compose up -d` and wait for PostgreSQL, Redis and MinIO health checks.

- [x] **Step 2: Apply migrations**

Run `uv run alembic upgrade head`.

- [x] **Step 3: Run backend and static checks**

Run `uv run pytest`, `uv run ruff check backend/src backend/tests`, and `uv run mypy`.

- [x] **Step 4: Run frontend checks**

Run `pnpm --dir frontend typecheck`, `pnpm --dir frontend build`, and `pnpm --dir frontend test:e2e` with the local API available.

- [x] **Step 5: Record failures as focused TDD tasks**

Do not change production code unless a failing test reproduces the defect.

### Task 2: Local UAT and Runtime Evidence

**Files:**
- Modify: `docs/release/task-08-readiness.md`
- Modify: `.scratch/ai-manhua-drama/issues/08-identity-credits-and-release-readiness.md`
- Test: `backend/tests/test_local_http_flow.py`, `frontend/tests/e2e/production-flow.spec.ts`

**Interfaces:**
- Consumes: passing local API, Worker, Beat and browser checks from Task 1.
- Produces: a repeatable local UAT checklist covering identity, credits, generation, export and recovery.

- [x] **Step 1: Exercise the local HTTP flow**

Run the existing HTTP flow test and confirm claim, authorization, credit reservation/refund, job polling and signed export download.

- [x] **Step 2: Exercise the browser production flow**

Run the production Playwright scenario and confirm the UI reaches a completed export state without exposing secrets.

- [x] **Step 3: Update local evidence only**

Append the fresh command outputs and date to the release/readiness documents. Keep server-only items explicitly deferred.

### Task 3: Review and Completion Gate

**Files:**
- Read: all changed files and plan checklist
- Test: full `pnpm test` plus the Docker smoke test

**Interfaces:**
- Consumes: implementation and evidence from Tasks 1-2.
- Produces: verified local completion statement with remaining external blockers listed.

- [x] **Step 1: Run the complete verification command set again**

Run `pnpm test`, the Docker smoke test, and the frontend Playwright suite after all edits.

- [x] **Step 2: Review the diff**

Confirm no secrets, generated schedules, unrelated refactors or deployment changes are included.

- [x] **Step 3: Mark only locally completed work**

Update issue documentation to distinguish local completion from server/real-provider work; do not mark external acceptance as complete.
