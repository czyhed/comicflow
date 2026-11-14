# Creation, Script, and Reference Image Design

**Status:** proposed for implementation

**Goal:** 完善 ComicFlow 的创建与剧本前置流程，让故事输入能够生成有内容差异的多场景、多镜头剧本，并允许用户在创建阶段上传可恢复的参考图。

## Scope

本次切片只覆盖创建页和剧本页，不重做角色、画面、声音、时间轴或导出 UI。剧本输出必须为后续生产阶段提供稳定的场景、镜头、角色引用和对白基础，但后续阶段的具体生成能力保留现状。

参考图第一阶段只作为项目资产保存和展示，不参与文本剧本生成。后续画面阶段可以通过项目快照读取该资产。

## Script Contract

`Script` 继续作为项目当前剧本，包含 `title`、`scenes` 和 `shots`。本次扩展要求：

- `Scene` 至少包含 `id`、`title`、`time`、`location`、`narrativeGoal`、`conflict`、`turningPoint` 和 `shotIds`。
- `Shot` 至少包含 `id`、`sceneId`、`order`、`title`、`action`、`emotion`、`shotSize`、`durationSec`、`visualDescription`、`dialogue`、`narration` 和 `characterIds`。
- 每个镜头只能归属一个场景；每个场景的 `shotIds` 必须与镜头的 `sceneId` 双向一致。
- 总镜头数保持 6～12；总时长保持 30～90 秒。
- 目标时长影响剧本规模：30 秒偏向 6 个镜头，60 秒偏向 8～10 个镜头，90 秒偏向 10～12 个镜头。
- 生成内容必须读取故事文本，标题、场景、动作、对白和旁白不能使用与输入无关的固定模板。

### Content minimums

- 30 秒目标生成 2 个场景、6 个镜头；60 秒目标生成 3 个场景、8～10 个镜头；90 秒目标生成 4 个场景、10～12 个镜头。允许在相邻目标内浮动，但不能退化为单场景固定模板。
- 故事文本必须包含标题/主题、主要角色、场景设定、开端、发展、转折和结尾方向；按目标时长分别建议至少 300、600、900 个中文字符。
- 场景的 `narrativeGoal`、`conflict` 和 `turningPoint` 必须是有实际内容的句子，不能使用“待定”“无”或重复文本。
- 镜头的 `visualDescription` 至少描述主体、动作和环境；`action`、`dialogue` 或 `narration` 不能全部为空。

## Provider Message Contract

模型返回的 `message.content` 必须先经过适配器归一化，再进入生产流水线。适配器只接受纯文本或 JSON，不接受 Markdown、代码围栏、`<think>`、解释性前后缀或多个混合对象；无法解析时返回 `PROVIDER_INVALID_RESPONSE`。

每一种生成操作使用一个带版本的 JSON 消息。未知 `kind`、缺少必填字段、字段类型错误、超出长度或包含额外顶层对象时都视为无效：

```json
{"kind":"story_text","version":1,"content":{"title":"...","logline":"...","characters":[{"name":"...","goal":"..."}],"setting":"...","beats":[{"type":"setup","text":"..."},{"type":"development","text":"..."},{"type":"turn","text":"..."},{"type":"ending","text":"..."}],"text":"..."}}
```

```json
{"kind":"script","version":1,"content":{"title":"...","scenes":[...],"shots":[...]}}
```

```json
{"kind":"guided_question","version":1,"content":{"questionId":"...","questionType":"goal|conflict|turn|ending|character|constraint","question":"...","missingFields":["..."],"options":["..."],"done":false}}
```

约束：

- `story_text` 的 `text` 必须与结构化字段一致；`beats` 必须按 `setup → development → turn → ending` 排序，至少 4 项。
- `script` 的 `content` 必须满足本设计的 Script Contract，并由服务端再次校验，不信任模型自报的数量和时长。
- `guided_question` 每次只能有一个问题；问题最多 80 个中文字符，`options` 最多 3 个；`done=true` 时 `question` 必须为空且不得要求用户继续回答。
- `questionId` 和 `questionType` 用于去重和记录缺失信息；Provider 不得重复已经回答的目标字段。
- 适配器必须从响应中移除 `<think>` 和代码围栏后再解析；清理后仍有非 JSON 内容、多个 JSON 对象或空内容时拒绝响应。
- 服务端保存的是归一化后的 `StoryDraft`、`Script` 或 `GuidedQuestion`，不保存原始模型消息。

## Creation Flow

### Automatic mode

```text
故事输入 → 生成故事文本 → 用户可编辑/保存 → 拆分为多场景剧本 → 剧本编辑器
```

创建页只负责故事文本生成和参考图上传；剧本拆分在剧本页执行，避免创建页同时承担两个版本的事实来源。

### Guided mode

```text
故事输入 → 生成剧本草稿 → 自适应问题 → 用户回答或提前结束 → 生成详细剧本 → 编辑/确认
```

问题由 Provider 根据当前剧本和已有回答选择，优先补齐角色目标、核心冲突、关键转折和结局。最多 9 轮仍作为上限，但不要求固定问满 9 轮；问题必须带有目标字段和去重 ID，用户可以回答、选择建议、跳过当前问题或直接生成详细剧本。

Mock Provider 必须使用故事和问答记录生成确定性的内容差异，不能直接返回原草稿作为详细剧本。若当前草稿已经具备足够信息，应提前返回 `done=true`；若信息不足，只询问最影响成片的一个字段。

## Reference Image Upload

新增项目参考图上传接口：

```text
POST /api/projects/{projectId}/reference-image
Content-Type: multipart/form-data
```

约束：

- 只接受常见图片类型（PNG、JPEG、WebP）。
- 限制单文件大小，超限返回稳定错误码。
- 匿名项目允许临时上传；项目权限沿用现有访问校验。
- 对象存储保存二进制，项目状态只保存资产 ID、媒体类型、大小、摘要、对象键和有效状态。
- 内存运行时保存等价的元数据和测试用占位内容。
- API 不返回供应商密钥或原始文件内容；快照返回可展示的元数据和短期访问地址（若配置对象存储）。
- 重新上传替换当前参考图并使旧图失效，但保留历史元数据。

前端创建页在上传成功前显示本地文件名和进度，成功后显示已保存状态；上传失败不清空故事输入，也不阻止继续编辑。

## Script Workspace

剧本页需要支持：

- 场景列表选择和场景级字段编辑。
- 场景新增、复制、删除和排序。
- 当前场景下的镜头列表和镜头字段编辑。
- 镜头新增、复制、删除和排序，排序只更新 `order`，不改变镜头 ID。
- 保存草稿、版本冲突提示和确认剧本。
- 显示镜头数量、总时长以及逐项校验错误。

确认前必须校验：

- 场景数量和镜头数量在允许范围内。
- 每个场景有标题、时间、地点和叙事目标。
- 每个镜头有动作或画面描述，并有对白或旁白。
- 所有镜头 ID 唯一，场景引用无遗漏、无重复、无孤立镜头。
- 总时长在 30～90 秒内。

剧本保存或确认后，项目版本递增；受影响的下游资产标记失效，历史剧本版本保留。现有认证、Credit 和生成作业幂等规则不变。

## API and Data Flow

```text
CreateWorkspace
  ├─ POST /api/projects
  ├─ POST /api/projects/{id}/story
  ├─ PATCH /api/projects/{id}/story
  └─ POST /api/projects/{id}/reference-image

ScriptWorkspace
  ├─ POST /api/projects/{id}/script/split
  ├─ PATCH /api/projects/{id}/script
  ├─ POST /api/projects/{id}/script/detail
  └─ POST /api/projects/{id}/script/confirm
```

Provider 只通过现有 `TextProvider` seam 工作。图片上传通过 `AssetStore` seam 工作；Celery 任务只传项目 ID、资产 ID 或作业 ID，不传文件内容。

## Testing and Acceptance

后端：

- 两个不同故事生成不同的剧本主题、场景或镜头内容。
- 30、60、90 秒生成的镜头规模符合目标区间。
- 全自动故事文本包含结构化四段 beats、角色和结尾方向，并达到对应时长的最小内容量。
- 多场景 `sceneId` 与 `shotIds` 双向一致。
- 模型消息的 `kind/version/content` 格式、字段类型、长度和禁止内容校验正确；畸形响应不会写入项目状态。
- 引导问题带有 `questionId/questionType/missingFields`，不会重复已回答目标，并可回答、跳过或提前结束。
- 引导回答会改变详细剧本，且可提前结束。
- 剧本校验拒绝孤立镜头、无效场景和超范围时长。
- 图片类型、大小、权限、替换和快照恢复行为正确。

前端 Playwright：

- 创建故事、上传参考图并保持输入内容。
- 自动模式生成故事文本、进入剧本页拆分并编辑保存。
- 逐步模式问答可提前结束，详细剧本可编辑。
- 多场景选择和镜头编辑不会覆盖其他场景。
- 刷新后恢复项目、参考图元数据和剧本草稿。

## Non-goals

- 本次不实现参考图的视觉理解或图片到剧本的自动推理。
- 本次不重做角色库、动态画面、TTS、口型、时间轴或 FFmpeg 多镜头合成。
- 本次不引入新的前端状态管理或第三方 AI 编排框架。

## Self-review

- 参考图只保存、不参与剧本生成，边界与已确认决策一致。
- 剧本契约增加场景上下文和镜头归属，但保留现有接口名称和版本机制。
- Mock 与真实 Provider 共用同一结构化输出校验，模型消息不会直接写入项目状态。
- 全自动输出有结构化内容量下限，逐步问题有类型、目标字段、去重 ID 和提前结束条件。
- 创建页、剧本页和上传接口形成单一可恢复数据流，没有新增浏览器事实来源。
- 后续生产阶段只消费已确认剧本，不在本次切片中声称画面或导出已完成。
