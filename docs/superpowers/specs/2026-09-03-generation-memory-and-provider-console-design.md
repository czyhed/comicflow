# Generation Memory and Provider Console Design

**Status:** proposed for implementation

**Goal:** 让现有模型 API 控制台真正驱动文本剧本生成，并让逐步生产、全自动生产、短期生成会话和历史剧本共享可恢复的持久化状态。

## Scope

本次改造只让“文本 / 剧本 Provider”进入真实生成链路。画面、TTS、口型和视频 Provider 继续保留现有 Adapter 与 Mock 行为，不在本次改造中宣称已接入真实模型。

本地默认仍为 `PROVIDER_MODE=mock`。用户在控制台配置并启用文本 Provider 后，文本生成请求才允许使用该配置；未配置或配置不可用时保持 Mock 回退或返回明确的 Provider 错误，不静默伪造真实结果。

## Domain Modules and Seams

### Provider Configuration Module

`ProviderConfigStore` 是文本 Provider 配置的外部接口。它负责读取、保存、测试和删除配置，并隐藏配置存储方式。

非敏感字段：

```text
provider, baseUrl, model, timeoutMs, enabled
```

API Key 的第一阶段策略：

```text
只进入后端运行时内存
不进入浏览器存储、数据库、日志或 Celery payload
服务重启后需要重新输入
```

配置读取接口只返回 `configured`、非敏感字段和掩码状态，不返回明文 Key。

### Project State Module

PostgreSQL 是项目事实来源。现有 `project_states.payload` 继续保存项目、剧本、镜头、任务、Credit 和导出清单，避免把同一状态拆成多个事实来源。

新增的生成会话状态也应通过项目状态或独立持久化记录关联到 `projectId`，并包含版本号和阶段 checkpoint。Redis 只承担队列、事件和临时锁。

### Generation Session Module

生成会话接口应支持：

```text
create(projectId, mode)
advance(sessionId)
pause(sessionId)
cancel(sessionId)
retry(sessionId)
snapshot(sessionId)
```

会话状态必须可幂等恢复。每个阶段完成后先提交 PostgreSQL checkpoint，再发布下一阶段事件。

## Production Modes

### Guided Mode

```text
story
→ script-generated
→ 等待用户确认
→ storyboard-generated
→ visual-generated
→ audio-generated
→ composed
→ exported
```

用户确认、编辑、取消和重试都必须携带 `expectedVersion`，版本冲突返回明确错误。

### Automatic Mode

全自动流程由后端 Celery 工作流推进，不由前端模拟连续点击。每个阶段都写入 checkpoint；失败时状态为 `paused` 或 `waiting-retry`，并保留失败原因和重试次数。

前端必须提供暂停、取消、重试当前阶段和继续执行的状态反馈。全自动流程不得绕过审核、Credit 预留或幂等约束。

## Script and History Storage

历史剧本长期保存于 PostgreSQL 项目状态。每次剧本确认生成一个不可变的 `ScriptVersion` 快照，当前项目继续指向最新版本。

需要提供：

```text
GET  /api/projects
GET  /api/projects/{projectId}/versions
POST /api/projects/{projectId}/duplicate
```

继续生成恢复原项目；复制项目创建独立项目；旧版本只读，不覆盖历史内容。

短期未提交表单草稿只保存在浏览器 `sessionStorage`，不包含 API Key；已创建项目的正式输入和生成结果必须尽快写入 PostgreSQL。

## Provider Request Flow

```text
创建页选择文本 Provider
→ 后端读取 ProviderConfigStore
→ 文本 Adapter 发起请求
→ 校验结构化 Script
→ 写入 ProjectState 和 ScriptVersion
→ 返回 Snapshot
```

错误分类至少包括：

```text
PROVIDER_NOT_CONFIGURED
PROVIDER_AUTH_FAILED
PROVIDER_TIMEOUT
PROVIDER_UNAVAILABLE
PROVIDER_INVALID_RESPONSE
```

Provider 请求不得把 API Key 放入任务参数。异步任务只传 `projectId`、`sessionId` 或 `jobId`。

## Security and Storage Evolution

第一阶段使用后端内存保存 API Key，以尽快完成本地真实文本生成并避免错误设计持久化密钥。

第二阶段才引入 PostgreSQL 加密保存，前提是提供外部 `PROVIDER_CONFIG_ENCRYPTION_KEY`，并实现掩码读取、轮换、删除、备份恢复和权限审计。加密密钥不得与数据库数据放在同一信任边界内。

## Testing and Acceptance

后端必须覆盖：

```text
配置保存/读取/删除
API Key 不回传、不落库、不进入任务 payload
测试连接成功、认证失败、超时和无效响应
文本 Provider 选择与 Mock 回退
Script 结构校验和版本保存
逐步生产 checkpoint 恢复
全自动阶段推进、暂停、取消和重试
历史项目、复制项目和版本读取
```

前端必须覆盖：

```text
控制台分块配置文本 Provider
显示已配置/掩码状态
测试连接反馈
创建页显示当前 Provider 模式
真实生成中的加载、错误和重试
刷新后恢复当前项目和生成会话
```

完整端到端验收：

```text
配置文本 Provider
→ 测试连接
→ 创建故事
→ 真实生成结构化剧本
→ 进入剧本编辑器
→ 刷新页面恢复
→ 继续逐步或全自动流程
```

## Self-review

- 未改变现有 PostgreSQL 事实来源和 Mock-first 默认策略。
- 明确区分短期会话、长期项目和浏览器草稿，避免多处事实来源。
- 明确 API Key 第一阶段不落盘，第二阶段加密持久化需要独立密钥。
- 明确逐步生产和全自动生产共享 checkpoint、版本和幂等约束。
- 画面、TTS、口型和视频不在本次真实 Provider 范围内，避免虚假完成声明。

## Guided Editing Extension

### Editable script stages

剧本生成分为两个用户可编辑阶段：

```text
故事 → 剧本草稿 → 用户修改/保存 → 详细剧本 → 用户修改/确认
```

创建页右侧直接展示当前阶段的结构化剧本。标题、场景标题、镜头标题、动作、对白、画面描述和旁白均可编辑。点击下一步前必须先保存草稿；模型生成详细剧本时只能基于已保存草稿和问答记录生成新版本。

### Guided question limits

逐步确认使用模型动态提问，但必须收敛：

- 最多 9 个问题；
- 单个回答最多 400 字；
- 问答上下文最多 1,200 字，只保留当前生成会话；
- Provider 返回 `done=true` 时立即结束；
- 用户可以随时跳过问答并生成详细剧本；
- 达到上限后不得再请求问题，直接进入详细剧本生成。

问答记录保存在项目的 `generationSession.guided` 中，API Key 和原始 Provider 响应不得保存。详细剧本和草稿版本沿用项目状态与 `scriptVersions` 历史机制。

### Guided interfaces

新增接口：

```text
POST /api/projects/{projectId}/script/guidance
POST /api/projects/{projectId}/script/guidance/answer
POST /api/projects/{projectId}/script/detail
```

Provider 通过现有文本适配器 seam 提供动态问题和详细剧本生成能力，不引入 LangChain 作为业务层依赖。
