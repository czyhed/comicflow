# Creation, Script, and Reference Image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完善创建与剧本前置流程，使模型输出有严格格式、有足够内容、逐步问答可自适应，并支持项目参考图上传与恢复。

**Architecture:** 保留现有 React/Vite + FastAPI + ProductionPipeline + Provider seam。先在后端建立统一的模型消息归一化与剧本质量校验，再让 Mock/真实文本 Provider 共用该契约；参考图通过现有 AssetStore 接口保存为项目资产。前端创建页和剧本页只消费归一化后的项目快照，不自行推断剧本状态。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、pytest、HTTPX、React 19、TypeScript、TanStack Query、Playwright、S3/MinIO AssetStore。

**Spec:** `docs/superpowers/specs/2026-09-04-creation-script-image-upload-design.md`

## Global Constraints

- 参考图第一阶段只保存和展示，不参与文本剧本生成。
- 30 秒目标为 2 个场景/6 个镜头，60 秒目标为 3 个场景/8～10 个镜头，90 秒目标为 4 个场景/10～12 个镜头。
- 模型消息必须使用带版本的 `kind/version/content` 格式；Markdown、代码围栏、`<think>`、解释性前后缀和多个 JSON 对象必须拒绝。
- PostgreSQL 是长期项目事实来源；内存运行时提供等价行为；Celery payload 不携带文件内容或 API Key。
- 现有 Mock、认证、Credit、版本和导出测试必须继续通过。

---

### Task 1: Script Contract and Provider Message Normalization

**Files:**
- Create: `backend/src/comicflow/providers/message_contract.py`
- Modify: `backend/src/comicflow/production/interfaces.py`
- Modify: `backend/src/comicflow/production/pipeline.py:203-302,1269-1329`
- Modify: `backend/src/comicflow/providers/bailian_text.py`
- Test: `backend/tests/test_provider_message_contract.py`
- Test: `backend/tests/test_script_contract.py`

**Interfaces:**
- Produces `normalize_story_message(body: object, target_duration_sec: int) -> JsonObject`, `normalize_script_message(body: object, target_duration_sec: int) -> JsonObject`, and `normalize_guided_question_message(body: object) -> JsonObject`.
- Produces `validate_script_content(script: object, target_duration_sec: int) -> list[JsonObject]`.
- `TextProvider` methods return normalized `str`/`JsonObject`; story/script generation methods receive `target_duration_sec: int`; raw model envelopes never cross the adapter boundary.

- [ ] **Step 1: Write failing contract tests**

  Cover valid `story_text`, `script`, and `guided_question` envelopes; reject unknown `kind`, wrong `version`, missing `content`, Markdown fences, `<think>`, multiple JSON objects, invalid field types, overlong questions, and `done=true` with a non-empty question. Add script tests for scene/shot bidirectional references, content minimums, target-duration shot counts, and total duration.

- [ ] **Step 2: Run the focused tests and verify failure**

  Run `uv run pytest backend/tests/test_provider_message_contract.py backend/tests/test_script_contract.py -v`. Expected: FAIL because the normalizers and stricter validator do not exist.

- [ ] **Step 3: Implement the normalizers and validators**

  Parse only one JSON object after removing code fences and `<think>` blocks. Normalize `story_text` to `{title, logline, characters, setting, beats, text}` and `guided_question` to `{questionId, questionType, question, missingFields, options, done}`. Enforce the content minimums from the spec and return stable `PROVIDER_INVALID_RESPONSE` or validation codes.

- [ ] **Step 4: Route Provider output through the contract**

  Update `BailianTextProvider` parsing and `ProductionPipeline.split_script`, `generate_script`, `ask_guided_question`, and `generate_detailed_script` to call the normalizers/validator. Preserve existing public API response shapes after normalization.

- [ ] **Step 5: Run focused and existing backend tests**

  Run `uv run pytest backend/tests/test_provider_message_contract.py backend/tests/test_script_contract.py backend/tests/test_bailian_text.py backend/tests/test_project_flow.py -v` and `uv run ruff check backend/src backend/tests`.

- [ ] **Step 6: Commit**

  `git add backend/src/comicflow/providers/message_contract.py backend/src/comicflow/providers/bailian_text.py backend/src/comicflow/production/interfaces.py backend/src/comicflow/production/pipeline.py backend/tests/test_provider_message_contract.py backend/tests/test_script_contract.py && git commit -m "feat: enforce structured script message contracts"`

### Task 2: Story-Conditioned Mock and Flexible Guided Generation

**Files:**
- Modify: `backend/src/comicflow/providers/mock.py`
- Modify: `backend/src/comicflow/production/pipeline.py:549-631`
- Modify: `frontend/src/types.ts`
- Test: `backend/tests/test_mock_script_generation.py`
- Test: `backend/tests/test_generation_sessions.py`

**Interfaces:**
- `MockTextProvider.generate_story_text(story, project_id, target_duration_sec) -> str` returns a deterministic expanded story draft.
- `MockTextProvider.generate_script(story, project_id, target_duration_sec) -> JsonObject` returns story-conditioned multi-scene content.
- `MockTextProvider.generate_guided_question(...) -> JsonObject` returns typed, deduplicated questions and can return `done=true` before nine rounds.
- `MockTextProvider.generate_detailed_script(...) -> JsonObject` incorporates transcript answers.

- [ ] **Step 1: Write failing behavior tests**

  Assert two distinct stories produce different titles, scenes, shot descriptions, and dialogue. Assert target duration changes scene/shot counts and content length. Assert guided questions use `questionId/questionType/missingFields`, do not repeat answered targets, can finish early, and detailed script contains an answer-specific phrase.

- [ ] **Step 2: Run focused tests and verify failure**

  Run `uv run pytest backend/tests/test_mock_script_generation.py backend/tests/test_generation_sessions.py -v`. Expected: FAIL because Mock currently discards story input and returns the original detailed script.

- [ ] **Step 3: Implement deterministic story-conditioned generation**

  Derive stable keywords from the input story and choose from multiple scene/shot templates keyed by those keywords and duration. Generate 2/3/4 scenes for 30/60/90 seconds, distribute 6/8-10/10-12 shots, populate scene context and `sceneId`, and ensure the generated story draft contains the four ordered beats.

- [ ] **Step 4: Implement flexible guided questioning**

  Track completed targets from transcript. Ask only the highest-priority missing target, return a unique `questionId`, and return `done=true` once goal/conflict/turn/ending are present. Accept a skip path by recording a skipped target without fabricating an answer. Merge transcript answers into title, scene conflict/turning point, and at least one shot field in detailed output.

- [ ] **Step 5: Update session state for typed questions and skip/finish**

  Extend `GuidedSession` with question metadata and skipped targets; keep the nine-question ceiling and existing API paths. Ensure `generate_detailed_script` can run with an empty transcript.

- [ ] **Step 6: Run focused and full backend checks**

  Run the focused tests, `uv run pytest`, `uv run mypy`, and `uv run ruff check backend/src backend/tests`.

- [ ] **Step 7: Commit**

  `git add backend/src/comicflow/providers/mock.py backend/src/comicflow/production/pipeline.py frontend/src/types.ts backend/tests/test_mock_script_generation.py backend/tests/test_generation_sessions.py && git commit -m "feat: make script generation story conditioned"`

### Task 3: Reference Image Asset Upload

**Files:**
- Create: `backend/src/comicflow/api/uploads.py`
- Modify: `backend/src/comicflow/api/schemas.py`
- Modify: `backend/src/comicflow/api/app.py`
- Modify: `backend/src/comicflow/domain/models.py`
- Modify: `backend/src/comicflow/production/pipeline.py`
- Test: `backend/tests/test_reference_image_upload.py`

**Interfaces:**
- Adds `POST /api/projects/{project_id}/reference-image` accepting multipart `file` and returning `{asset, projectVersion}`.
- Adds `ProductionPipeline.upload_reference_image(project_id, filename, content_type, content, user_id) -> JsonObject`.
- Asset metadata includes `id`, `type`, `mediaType`, `sizeBytes`, `sha256`, `objectKey`, `valid`, and optional `downloadUrl`.

- [ ] **Step 1: Write failing upload tests**

  Cover PNG/JPEG/WebP success, unsupported type, size limit, anonymous project access, owned project access, unauthorized access, replacement invalidation, memory runtime metadata, and configured AssetStore byte upload without raw bytes in project state.

- [ ] **Step 2: Run focused tests and verify failure**

  Run `uv run pytest backend/tests/test_reference_image_upload.py -v`. Expected: FAIL because no upload route or pipeline method exists.

- [ ] **Step 3: Implement file validation and hashing**

  Validate MIME type and a fixed 10 MiB limit in `uploads.py`; compute SHA-256 and create a project-scoped asset ID. Reject empty files and unsupported types with stable error codes.

- [ ] **Step 4: Persist metadata through AssetStore and project snapshot**

  Add `referenceImages`/`referenceImage` metadata to project state. Use the configured AssetStore for bytes and the memory runtime for deterministic metadata-only storage. Mark the previous current image invalid when replacing it.

- [ ] **Step 5: Add the FastAPI route and access check**

  Use `UploadFile`, call `require_project_access`, pass project/user context to the pipeline, and return only metadata plus a short-lived URL when available.

- [ ] **Step 6: Run backend checks**

  Run focused upload tests, `uv run pytest backend/tests/test_local_http_flow.py backend/tests/test_infrastructure_smoke.py -v` with the smoke opt-in only when Docker is available, plus Ruff and mypy.

- [ ] **Step 7: Commit**

  `git add backend/src/comicflow/api/uploads.py backend/src/comicflow/api/schemas.py backend/src/comicflow/api/app.py backend/src/comicflow/domain/models.py backend/src/comicflow/production/pipeline.py backend/tests/test_reference_image_upload.py && git commit -m "feat: persist project reference image uploads"`

### Task 4: Creation API and State Flow

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/features/create/CreateWorkspace.tsx`
- Modify: `backend/src/comicflow/production/pipeline.py`
- Modify: `backend/src/comicflow/api/app.py`
- Test: `backend/tests/test_creation_script_flow.py`

**Interfaces:**
- `comicflowApi.uploadReferenceImage(projectId, file) -> Promise<ReferenceImageAsset>`.
- Creation flow preserves the existing automatic `story -> split` and guided `draft -> guidance -> detail` commands.
- Story generation accepts the project's target duration so content sizing is deterministic.

- [ ] **Step 1: Write failing HTTP flow tests**

  Assert automatic mode creates a story draft with all four beats, split returns multiple scenes and correct references, guided mode can answer one question then finish, and every response is editable before save. Assert the project snapshot contains uploaded reference image metadata.

- [ ] **Step 2: Run focused tests and verify failure**

  Run `uv run pytest backend/tests/test_creation_script_flow.py -v`. Expected: FAIL on content shape, duration propagation, or missing upload state.

- [ ] **Step 3: Propagate target duration through Provider calls**

  Update every in-repo `TextProvider` implementation and call site to accept `target_duration_sec: int`; do not retain a second compatibility signature. Pass the value from `project.input.durationSec`, never through Celery payloads, and save normalized story/script versions with the project version.

- [ ] **Step 4: Make automatic and guided transitions explicit**

  Automatic mode stops after editable story text until the user enters the script module; guided mode starts from a script draft, records typed question metadata, and allows finish/skip before detailed generation. No path should silently call the old fixed-template method.

- [ ] **Step 5: Run backend flow tests and static checks**

  Run the focused flow tests, existing project/script/session tests, Ruff, and mypy.

- [ ] **Step 6: Commit**

  `git add backend/src/comicflow/production/pipeline.py backend/src/comicflow/api/app.py frontend/src/api/client.ts frontend/src/features/create/CreateWorkspace.tsx backend/tests/test_creation_script_flow.py && git commit -m "feat: connect creation flow to rich script generation"`

### Task 5: Creation Workspace and Upload UX

**Files:**
- Modify: `frontend/src/features/create/CreateWorkspace.tsx`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/styles.css`
- Test: `frontend/tests/e2e/create-project.spec.ts`

**Interfaces:**
- The create page displays story title/logline/beats where available, upload progress/status, and a recoverable reference image state.
- API keys remain absent from this flow; reference image bytes are sent only in the upload request.

- [ ] **Step 1: Write failing Playwright tests**

  Assert upload sends multipart data, displays success metadata, preserves story text after upload failure, automatic mode shows a substantial editable story draft, and guided mode supports answer, skip/finish, and detailed script transition.

- [ ] **Step 2: Run the focused browser tests and verify failure**

  Run `pnpm --dir frontend test:e2e --grep "reference image|story draft|guided"`. Expected: FAIL until the new request and states are wired.

- [ ] **Step 3: Implement upload mutation and local UI state**

  Add a file input mutation using `FormData`, show filename, pending, success, and error states, and never clear the story/editor state on upload failure. Invalidate the project snapshot after success.

- [ ] **Step 4: Render structured story and guidance state**

  Render story title/logline/beats without exposing raw model envelopes. Show the current typed question, optional choices, skip, and finish actions. Preserve existing draft save and version-conflict behavior.

- [ ] **Step 5: Run browser and frontend checks**

  Run the focused Playwright tests, the full frontend E2E suite, `pnpm --dir frontend typecheck`, and `pnpm --dir frontend build`.

- [ ] **Step 6: Commit**

  `git add frontend/src/features/create/CreateWorkspace.tsx frontend/src/api/client.ts frontend/src/types.ts frontend/src/styles.css frontend/tests/e2e/create-project.spec.ts && git commit -m "feat: improve creation story and image upload UX"`

### Task 6: Scene-Aware Script Workspace

**Files:**
- Modify: `frontend/src/features/script/ScriptWorkspace.tsx`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/styles.css`
- Test: `frontend/tests/e2e/create-project.spec.ts`
- Test: `frontend/tests/e2e/production-flow.spec.ts`

**Interfaces:**
- Script editor maintains `selectedSceneId` and edits only the selected scene plus its shots.
- Existing shot mutation endpoints remain the persistence boundary; all saves carry the current project version.

- [ ] **Step 1: Write failing scene-editing tests**

  Assert multiple scenes render, selecting a scene changes the editor, editing one scene does not alter another, scene metadata and shot fields save together, and invalid references display actionable errors.

- [ ] **Step 2: Run focused browser tests and verify failure**

  Run `pnpm --dir frontend test:e2e --grep "scene|script editor"`. Expected: FAIL because the current editor always edits the first scene and does not expose scene operations.

- [ ] **Step 3: Implement scene selection and grouped shot editing**

  Add scene state, render scene metadata fields, filter shots by `shotIds`, and keep the global shot order stable. Add add/copy/delete/reorder controls only where the corresponding API exists.

- [ ] **Step 4: Add client-side validation and server error display**

  Show scene/shot count, duration, missing content, and reference errors before confirmation; keep server validation as the authority and display its stable codes.

- [ ] **Step 5: Run browser and frontend checks**

  Run focused and full Playwright, TypeScript, and Vite build checks.

- [ ] **Step 6: Commit**

  `git add frontend/src/features/script/ScriptWorkspace.tsx frontend/src/api/client.ts frontend/src/types.ts frontend/src/styles.css frontend/tests/e2e/create-project.spec.ts frontend/tests/e2e/production-flow.spec.ts && git commit -m "feat: add scene-aware script editing"`

### Task 7: Full Verification and Documentation

**Files:**
- Modify: `docs/release/task-08-readiness.md`
- Modify: `docs/superpowers/specs/2026-09-04-creation-script-image-upload-design.md`
- Test: all backend and frontend suites

- [ ] **Step 1: Run the complete local gate**

  Run `pnpm test`, `uv run ruff check backend/src backend/tests`, `uv run mypy`, `pnpm --dir frontend test:e2e`, and `git diff --check`. Run `COMICFLOW_INFRA_SMOKE=1 uv run pytest backend/tests/test_infrastructure_smoke.py -v` only when Docker services are available.

- [ ] **Step 2: Verify the exact user flows**

  Manually or through Playwright verify: story input → reference image upload → automatic story draft → script split → multi-scene edit/save; and story input → guided draft → adaptive question → skip/finish → detailed script edit/save.

- [ ] **Step 3: Update evidence without overclaiming**

  Record only verified local behavior in release docs. Keep real Provider evaluation, visual reference-image consumption, and downstream multi-shot composition explicitly outside this slice.

- [ ] **Step 4: Review the diff**

  Confirm no API keys, raw model envelopes, image bytes, generated schedules, or unrelated dependency changes are committed.

- [ ] **Step 5: Commit**

  `git add docs/release/task-08-readiness.md docs/superpowers/specs/2026-09-04-creation-script-image-upload-design.md && git commit -m "docs: record creation and script slice verification"`
