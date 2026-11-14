# ComicFlow 数据流与架构文档

**目的：** 清晰定义系统中数据如何流转，各模块职责边界，避免混乱的依赖关系。

**使用规则：**
- 新增功能前必须先确认数据流向
- 修改接口前必须评估对下游的影响
- 跨模块调用必须通过明确的接口

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                         Frontend (React)                     │
│  - 创建向导 (CreateWorkspace)                                │
│  - 剧本编辑器 (ScriptWorkspace)                              │
│  - 分镜编辑器 (StoryboardWorkspace)                          │
│  - 资产管理 (Visual/Audio Workspace)                         │
│  - 导出管理 (ExportWorkspace)                                │
└─────────────────┬───────────────────────────────────────────┘
                  │ HTTP/REST API
                  │ SSE (实时进度)
┌─────────────────▼───────────────────────────────────────────┐
│                      FastAPI Application                     │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              API Layer (app.py)                     │    │
│  │  - 路由定义                                          │    │
│  │  - 请求验证 (Pydantic Schemas)                       │    │
│  │  - 错误处理                                          │    │
│  │  - 权限校验                                          │    │
│  └─────────────────┬───────────────────────────────────┘    │
│                    │                                         │
│  ┌─────────────────▼───────────────────────────────────┐    │
│  │         Production Pipeline (核心业务逻辑)          │    │
│  │  - 项目生命周期管理                                  │    │
│  │  - 生成会话管理                                      │    │
│  │  - 状态机流转                                        │    │
│  │  - 额度管理                                          │    │
│  └─────┬───────────────────────────────────┬───────────┘    │
│        │                                   │                │
│  ┌─────▼──────────┐              ┌────────▼─────────┐      │
│  │  Repository    │              │   Provider       │      │
│  │  - Project     │              │   Adapters       │      │
│  │  - Character   │              │   - Text         │      │
│  │  (数据持久化)   │              │   - Visual       │      │
│  └────────┬───────┘              │   - TTS          │      │
│           │                      │   - LipSync      │      │
│           │                      │   - Moderation   │      │
│           │                      │   - Composition  │      │
│           │                      └──────────┬───────┘      │
└───────────┼─────────────────────────────────┼──────────────┘
            │                                 │
┌───────────▼────────┐            ┌───────────▼────────────┐
│    PostgreSQL      │            │  百炼 API / FFmpeg     │
│  - projects        │            │  - qwen-plus (文本)    │
│  - characters      │            │  - wanx2.1 (图像)      │
│  - generation_jobs │            │  - qwen3-tts (语音)    │
└────────────────────┘            │  - FFmpeg (视频合成)   │
                                  └────────────────────────┘
┌────────────────────┐
│   Redis            │
│ - Celery 队列      │
│ - 生成状态缓存     │
│ - 分布式锁         │
└────────────────────┘

┌────────────────────┐
│   MinIO (S3)       │
│ - 视觉资产         │
│ - 音频文件         │
│ - 导出视频         │
└────────────────────┘
```

---

## 二、核心数据流

### 2.1 项目创建流程

```
用户输入 (Frontend)
  → POST /api/projects (API)
    → ProductionPipeline.create_project()
      → 验证输入 (story 长度、duration 范围)
      → 生成 project_id, guest_id
      → 初始化项目状态
        {
          id: "prj_xxx",
          stage: "story",
          input: { story, durationSec, mode },
          creditLedger: [{ type: "grant", amount: 100 }],
          generationSession: { ... }
        }
      → ProjectRepository.save()
        → PostgreSQL INSERT projects
  ← 返回 { project, guestSession, estimate }
```

**关键数据结构：**
```python
# Project 核心字段
{
  "id": "prj_xxx",
  "stage": "story" | "story-generated" | "script-completed" | ...,
  "version": 1,  # 乐观锁版本号
  "input": {
    "inputType": "idea" | "story",
    "story": "用户输入的故事",
    "durationSec": 60,
    "mode": "automatic" | "import_story" | "import_script"
  },
  "ownerUserId": null | "usr_xxx",
  "generatedStoryText": "AI 扩展后的故事" | null,
  "script": { ... } | null,
  "creditLedger": [
    { "type": "grant", "amount": 100 },
    { "type": "reservation", "amount": -2 }
  ],
  "visualAssets": [...],
  "audioAssets": [...],
  "exportManifest": { ... } | null
}
```

### 2.2 Automatic 模式完整数据流

```
1. 创建项目
   stage: story → story-generating

2. 生成故事文本
   POST /api/projects/{id}/story
   → TextProvider.generate_story_text()
     → 百炼 API (qwen-plus)
     → 流式返回文本片段
   → 写入 project.generatedStoryText
   stage: story-generating → story-generated

3. 拆分剧本
   POST /api/projects/{id}/script/split
   → TextProvider.split_script()
     → 百炼 API
     → 返回结构化剧本 JSON
   → 契约验证 (normalize_script_message)
   → 写入 project.script
   stage: story-generated → script-completed

4. 确认剧本
   POST /api/projects/{id}/script/confirm
   → 验证剧本结构 (_validate_script)
   → 设置 scriptConfirmedVersion
   stage: script-completed → storyboard-ready

5. 自动生成会话推进
   POST /api/projects/{id}/generation-session/advance
   → advance_generation_session()
     → 串行生成所有镜头的视觉资产
       for shot in shots:
         generate_shot_visual()
           → DynamicVisualProvider.generate()
             → 百炼 wanx2.1 API
           → 写入 project.visualAssets[]
     stage: storyboard-ready → visual-completed
     
     → 串行生成所有镜头的音频资产
       for shot in shots:
         generate_shot_audio()
           → TtsProvider.generate()
             → 百炼 qwen3-tts API
           → LipSyncProvider.generate()
           → 写入 project.audioAssets[], lipSyncAssets[]
           → 构建 timeline
     stage: visual-completed → audio-completed
     
     → 请求合成
       request_composition()
         → 创建 composition job
         → 发布 outbox 事件
     stage: audio-completed → composition-queued

6. Celery Worker 执行合成
   → run_job(job_id)
     → CompositionProvider.compose()
       → FFmpeg 合成视频
       → 上传到 MinIO
     → 写入 project.exportManifest
   stage: composition-queued → exported
```

### 2.3 数据写入时机

| 操作 | 写入位置 | 写入时机 | 事务性 |
|------|---------|---------|--------|
| 创建项目 | PostgreSQL projects | 立即 | 单次 |
| 生成故事 | PostgreSQL + Redis | 流式更新 | 最终一致 |
| 拆分剧本 | PostgreSQL | 立即 | 单次 |
| 生成视觉 | PostgreSQL + MinIO | 单个完成时 | 单个原子 |
| 生成音频 | PostgreSQL + MinIO | 单个完成时 | 单个原子 |
| 合成导出 | PostgreSQL + MinIO | 完成时 | 单次 |

---

## 三、模块职责边界

### 3.1 Frontend (React)

**职责：**
- 用户交互界面
- 表单验证（客户端）
- 状态展示
- SSE 进度订阅

**不负责：**
- ❌ 业务逻辑计算
- ❌ 数据持久化
- ❌ AI 调用

**对外接口：**
- 调用 Backend REST API
- 订阅 SSE 事件流

### 3.2 API Layer (FastAPI)

**职责：**
- HTTP 路由
- 请求/响应验证（Pydantic）
- 权限校验
- 错误码映射
- SSE 推送

**不负责：**
- ❌ 业务逻辑实现
- ❌ 直接访问数据库
- ❌ 直接调用 AI API

**对外接口：**
- REST API 端点
- SSE 事件流

### 3.3 ProductionPipeline (核心业务)

**职责：**
- 项目生命周期管理
- 状态机流转
- 生成会话协调
- 额度管理
- 版本控制（乐观锁）

**不负责：**
- ❌ HTTP 细节
- ❌ SQL 语句
- ❌ AI API 实现细节

**对外接口：**
```python
class ProductionPipeline:
    async def create_project(command: CreateProject) -> JsonObject
    async def generate_story_text(project_id: str) -> JsonObject
    async def split_script(project_id: str) -> JsonObject
    async def confirm_script(project_id: str, expected_version: int) -> JsonObject
    async def generate_shot_visual(project_id: str, shot_id: str, expected_version: int) -> JsonObject
    async def generate_shot_audio(project_id: str, shot_id: str, expected_version: int) -> JsonObject
    async def request_composition(project_id: str, expected_version: int) -> JsonObject
```

### 3.4 Repository Layer

**职责：**
- 数据持久化
- 查询封装
- 事务管理

**不负责：**
- ❌ 业务逻辑
- ❌ 状态验证

**对外接口：**
```python
class ProjectRepository:
    async def save(record: ProjectRecord) -> None
    async def get(project_id: str) -> ProjectRecord | None
    async def list_projects() -> list[ProjectRecord]
```

### 3.5 Provider Adapters

**职责：**
- AI API 调用封装
- 响应格式归一化
- 错误处理统一化
- 重试逻辑

**不负责：**
- ❌ 业务状态管理
- ❌ 数据持久化

**对外接口：**
```python
class TextProvider:
    async def generate_story_text(story: str, project_id: str) -> str
    async def split_script(story_text: str, project_id: str) -> JsonObject

class DynamicVisualProvider:
    async def generate(shot: JsonObject, characters: list[JsonObject]) -> JsonObject

class TtsProvider:
    async def generate(shot_id: str, speaker_id: str, text: str) -> JsonObject
```

---

## 四、关键接口契约

### 4.1 Script 结构

```typescript
interface Script {
  kind: "script";
  version: 1;
  title: string;
  summary?: string;
  scenes: Scene[];
  shots: Shot[];
}

interface Scene {
  id: string;
  title: string;
  time?: string;
  location?: string;
  narrativeGoal?: string;
  shotIds: string[];
}

interface Shot {
  id: string;
  sceneId?: string;
  order?: number;
  title: string;
  visualDescription: string;
  dialogue?: string;      // 对白
  narration?: string;     // 旁白
  action: string;
  emotion: string;
  shotSize: string;
  durationSec: number;
  characterIds?: string[];
}
```

### 4.2 Asset 结构

```typescript
interface VisualAsset {
  id: string;
  shotId: string;
  type: "image" | "video";
  url?: string;
  objectKey?: string;
  durationMs?: number;
  valid: boolean;
  inputVersion: number;
}

interface AudioAsset {
  id: string;
  shotId: string;
  speakerId: string;
  text: string;
  durationMs: number;
  url?: string;
  objectKey?: string;
  valid: boolean;
}
```

### 4.3 Timeline 结构

```typescript
interface Timeline {
  shotId: string;
  durationMs: number;
  visualTrack: VisualTrackItem[];
  audioTrack: AudioTrackItem[];
  subtitleTrack: SubtitleItem[];
  lipSyncTrack?: LipSyncItem[];
}
```

---

## 五、状态机

### Project Stage 状态流转

```
Automatic 模式:
story 
  → story-generating 
  → story-generated 
  → script-completed 
  → storyboard-ready 
  → visual-completed 
  → audio-completed 
  → composition-queued 
  → exported

Import Story 模式:
story-generated 
  → script-completed 
  → storyboard-ready 
  → ...

Import Script 模式:
storyboard-ready 
  → visual-completed 
  → ...

错误状态:
  - story-failed
  - script-failed
  - moderation-blocked
  - moderation-review
  - cancelled
```

### Generation Session Status

```
ready → running → ready (循环)
ready → failed → waiting-retry → ready
ready → paused → ready
ready → cancelled (终止)
ready → completed (完成)
```

---

## 六、数据一致性保证

### 6.1 乐观锁机制

```python
# 所有修改操作都需要 expectedVersion
async def update_script(project_id: str, script: JsonObject, expected_version: int):
    project = await repository.get(project_id)
    if project.version != expected_version:
        raise DomainError("VERSION_CONFLICT")
    
    project.script = script
    project.version += 1
    await repository.save(project)
```

### 6.2 资产失效机制

```python
# 重新生成视觉资产时，旧资产标记为 invalid
for asset in project.visualAssets:
    if asset["shotId"] == shot_id and asset.get("valid"):
        asset["valid"] = False

new_asset = {"id": "...", "shotId": shot_id, "valid": True}
project.visualAssets.append(new_asset)
```

### 6.3 事务边界

- 单个项目修改：单个 `save()` 调用
- 批量生成：每个资产独立 `save()`
- 合成作业：独立事务，失败不影响项目状态

---

## 七、错误传播

```
Provider Error (RuntimeError)
  → ProductionPipeline 捕获并映射
    → DomainError (业务错误码)
      → API Layer 捕获
        → HTTP Status Code + Error JSON
          → Frontend 显示中文提示
```

**错误码示例：**
- `PROVIDER_TIMEOUT` → 504
- `PROVIDER_UNAVAILABLE` → 503
- `PROVIDER_INVALID_RESPONSE` → 502
- `VERSION_CONFLICT` → 409
- `INSUFFICIENT_CREDIT` → 409

---

## 文档更新记录
- 2026-09-07: 初始创建
