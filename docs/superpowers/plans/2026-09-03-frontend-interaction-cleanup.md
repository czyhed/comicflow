# Frontend Interaction Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 清理创建、剧本和分镜工作区中的空按钮，确保可见控件都有真实行为或明确的不可用状态。

**Architecture:** 保持 React Query + Zustand 的现有结构。创建页只保留已支持的故事生成流程并把参数改成真实表单控件；剧本页保留已有保存/确认能力；分镜页移除没有后端契约支持的保存类空按钮，避免误导用户。

**Tech Stack:** React 19、TypeScript、Vite、React Query、Zustand、Playwright。

**Spec:** 用户确认的可灵平台风格工作台拆分；现有前端 API 契约 `frontend/src/api/client.ts`。

## Global Constraints

- 不新增未实现的后端 API，不伪造真实 Provider 能力。
- 不保留点击后无任何反馈的按钮。
- API Key 不写入生产代码或 localStorage。
- 每个交互修改必须有 Playwright 或类型检查证据。

---

### Task 1: Create Workspace Controls

**Files:**
- Modify: `frontend/src/features/create/CreateWorkspace.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/tests/e2e/create-project.spec.ts`

**Interfaces:**
- Consumes: `comicflowApi.createProject`, `comicflowApi.generateScript`.
- Produces: working duration/quality controls, reference image selection preview, and no-op-free creation UI.

- [ ] Add a failing browser assertion for duration selection, quality selection, and reference preview.
- [ ] Run the focused Playwright test and verify it fails because controls are not implemented.
- [ ] Implement the smallest controlled inputs and preview state.
- [ ] Run the focused test and frontend typecheck.

### Task 2: Script Workspace Feedback

**Files:**
- Modify: `frontend/src/features/script/ScriptWorkspace.tsx`
- Modify: `frontend/src/styles.css`
- Test: `frontend/tests/e2e/create-project.spec.ts`

**Interfaces:**
- Consumes: existing snapshot and `updateScript`/`confirmScript` mutations.
- Produces: visible save/confirm pending and error feedback; scene buttons remain truthful.

- [ ] Add a failing browser assertion for save failure feedback.
- [ ] Run the focused test and verify the expected failure.
- [ ] Add mutation error rendering and disable duplicate submission.
- [ ] Run the focused test and frontend typecheck.

### Task 3: Storyboard No-op Removal

**Files:**
- Modify: `frontend/src/features/storyboard/StoryboardWorkspace.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Test: `frontend/tests/e2e/create-project.spec.ts`

**Interfaces:**
- Consumes: existing snapshot and shot selection state.
- Produces: no empty create/copy/save controls; only supported shot selection remains.

- [ ] Add a failing browser assertion that unsupported controls are absent.
- [ ] Run the focused test and verify it fails against the current UI.
- [ ] Remove unsupported controls and retain truthful inspector fields.
- [ ] Run Playwright, typecheck and build.

### Task 4: Full Review Gate

**Files:**
- Read: all modified frontend files
- Test: full Playwright, TypeScript build, and `git diff --check`

- [ ] Run all frontend verification commands.
- [ ] Review the diff for empty handlers, secrets, and unrelated changes.
- [ ] Record the completed local frontend phase in the task notes.
