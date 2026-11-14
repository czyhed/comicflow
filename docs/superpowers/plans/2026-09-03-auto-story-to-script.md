# 自动故事文本与剧本拆分实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让全自动创建先生成可编辑故事文本，再由剧本模块显式拆分为结构化剧本，并补齐创建页的真实状态与输入持久化。

**Architecture:** 在现有 TextProvider 和 ProductionPipeline seam 上增加文本草稿与脚本拆分两个窄接口。项目 payload 保存文本、脚本和阶段 checkpoint；创建页只负责文本，剧本页负责拆分，自动生产会话在文本生成后等待拆分。

**Tech Stack:** FastAPI、Pydantic、React 19、React Query、pytest、Playwright、现有内存/PostgreSQL repository。

**Spec:** `docs/superpowers/specs/2026-09-03-auto-story-to-script-design.md`

## Global Constraints

- 故事输入长度为 10 到 2,000 字。
- 生成文本必须为非空文本，最大 8,000 字。
- `generatedStoryText` 和结构化 `script` 都写入项目事实来源。
- API Key 不进入浏览器存储、数据库、日志或任务参数。
- 自动会话在 `story-generated` 阶段不得生成视觉、音频或合成任务。
- 现有逐步确认和旧项目 Script 恢复行为必须保持。

---

### Task 1: Provider 文本生成与拆分契约

**Files:**
- Modify: `backend/src/comicflow/production/interfaces.py`
- Modify: `backend/src/comicflow/providers/mock.py`
- Modify: `backend/src/comicflow/providers/bailian_text.py`
- Test: `backend/tests/test_bailian_text.py`

**Interfaces:**
- `generate_story_text(story: str, project_id: str) -> str`
- `split_script(story_text: str, project_id: str) -> JsonObject`

- [x] 写失败测试：Mock/百炼 Provider 能返回非空故事文本；拆分仍能规范化完整 Script。
- [x] 运行 `uv run pytest backend/tests/test_bailian_text.py -q`，确认测试因接口缺失失败。
- [x] 实现两个 Provider 方法；百炼文本提示不使用 `response_format=json_object`，拆分提示继续使用结构化 JSON。
- [x] 对空文本、超长文本和无效拆分响应映射 `PROVIDER_RESPONSE_INVALID`。
- [x] 运行 `uv run pytest backend/tests/test_bailian_text.py -q` 与 `uv run ruff check backend/src backend/tests`。

### Task 2: 项目文本状态与 API

**Files:**
- Modify: `backend/src/comicflow/production/pipeline.py`
- Modify: `backend/src/comicflow/api/app.py`
- Modify: `backend/src/comicflow/api/schemas.py`
- Modify: `backend/src/comicflow/domain/models.py`
- Test: `backend/tests/test_generation_sessions.py`
- Test: `backend/tests/test_runtime_text_generation.py`

**Interfaces:**
- `POST /api/projects/{project_id}/story` returns `{project, storyText}`.
- `POST /api/projects/{project_id}/script/split` returns `{project, script}`.
- `ProductionPipeline.generate_story_text(project_id) -> JsonObject`.
- `ProductionPipeline.split_script(project_id) -> JsonObject`.

- [x] 写失败测试：自动项目可保存纯文本并进入 `story-generated`；没有文本时拆分返回 `STORY_TEXT_REQUIRED`；拆分成功递增版本。
- [x] 写失败测试：自动会话在 `story-generated` 不创建视觉任务，旧 `script-completed` 流程仍继续。
- [x] 运行针对测试并确认失败原因是缺少新状态/方法。
- [x] 在 `create_project` 初始化 `generatedStoryText: None` 与 `storyTextVersion: 0`。
- [x] 实现文本生成的审核、Credit 预留/释放、幂等键和错误映射；成功保存文本和阶段。
- [x] 实现拆分的版本检查、Provider 调用、脚本保存和阶段转换；失败不覆盖已有数据。
- [x] 调整自动会话 checkpoint，使 `story-generated` 只返回等待状态。
- [x] 运行 `uv run pytest backend/tests/test_generation_sessions.py backend/tests/test_runtime_text_generation.py -q`。

### Task 3: 前端 API 类型与创建页文本流程

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/app/App.tsx`
- Modify: `frontend/src/features/create/CreateWorkspace.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/tests/e2e/create-project.spec.ts`

**Interfaces:**
- `Snapshot.project.generatedStoryText?: string | null`。
- `comicflowApi.generateStoryText(projectId)`。
- `comicflowApi.updateStoryText(projectId, text, expectedVersion)`。

- [x] 写失败 E2E：自动创建请求只命中 `/story`，显示可编辑文本，不显示镜头概览。
- [x] 写失败 E2E：文本保存后刷新快照仍显示，生成失败保留错误和文本。
- [x] 运行目标 E2E 确认当前实现失败。
- [x] 把创建 mutation 从 `/script` 改为 `/story`，保留逐步模式的兼容路径。
- [x] 增加文本预览编辑器、保存按钮、保存中/失败状态和“进入剧本模块”按钮。
- [x] 将质量和参考图控件的当前限制写入界面状态，不提供未实现的假承诺；时长继续进入创建请求。
- [x] 运行目标 E2E、`npm run typecheck` 和 `npm run build`。

### Task 4: 剧本模块拆分入口

**Files:**
- Modify: `frontend/src/features/script/ScriptWorkspace.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/tests/e2e/create-project.spec.ts`
- Test: `frontend/tests/e2e/production-flow.spec.ts`

**Interfaces:**
- `comicflowApi.splitScript(projectId)` returns `{project, script}`。
- 无 `snapshot.script` 且有 `generatedStoryText` 时显示拆分面板。

- [x] 写失败 E2E：剧本模块展示文本并提供“拆分为剧本”；拆分成功后显示可编辑镜头。
- [x] 写失败 E2E：拆分失败时文本仍可见，点击重试可再次请求。
- [x] 运行目标 E2E 确认失败。
- [x] 实现拆分 mutation、状态反馈和成功后的脚本编辑器切换。
- [x] 保持已有保存、确认、版本冲突处理。
- [x] 运行全部前端 E2E、类型检查和构建。

### Task 5: 全量验证与审查

**Files:**
- Review: `backend/src/comicflow/production`, `backend/src/comicflow/providers`, `frontend/src/features/create`, `frontend/src/features/script`
- Test: `backend/tests`, `frontend/tests/e2e`

- [x] 运行 `uv run pytest -q`。
- [x] 运行 `uv run ruff check backend/src backend/tests` 与 `uv run mypy`。
- [x] 运行 `npm run typecheck`、`npm run build`、`npm run test:e2e -- --reporter=line`。
- [x] 检查自动会话在 `story-generated` 没有越过拆分阶段，且 API Key 未出现在 diff、浏览器 localStorage 或日志中。
- [x] 对照设计文档审查空按钮、错误恢复、旧项目兼容和响应字段一致性。
