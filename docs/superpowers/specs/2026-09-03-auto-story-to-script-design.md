# 自动故事文本与剧本拆分设计

## 目标

将创建页与剧本页的职责分开：创建页负责生成可编辑的故事文本/剧情梗概，剧本页负责把文本拆分为结构化场景与镜头。全自动入口不再要求文本模型一次返回完整 `Script` JSON，从而避免普通文本响应被误判为 `PROVIDER_INVALID_RESPONSE`。

## 现状与问题

当前创建页的“全自动”仍调用 `POST /api/projects/{projectId}/script`，该接口要求 Provider 返回 `title/scenes/shots`。真实模型返回自然语言文本时，Provider 的 JSON 解析或脚本规范化会失败；即使成功，也让创建页承担了剧本拆分职责。自动生产会话还把脚本生成完成直接当作 `script-completed`，没有文本生成与剧本拆分之间的 checkpoint。

## 设计

### 工作流

```text
创建页输入故事
  -> POST /api/projects
  -> POST /api/projects/{id}/story
  -> 保存 generatedStoryText，项目阶段 story-generated
  -> 创建页展示可编辑文本
  -> 进入剧本模块
  -> POST /api/projects/{id}/script/split
  -> 保存结构化 Script，项目阶段 awaiting-confirmation/script-completed
  -> 现有剧本编辑、确认、分镜和生产流程
```

旧项目中的 guided 会话仅做兼容读取；新创建流程不再进入逐步问答，统一走全自动生成或导入内容流程。

“全自动”在创建阶段表示自动生成故事文本。后续脚本拆分必须是一个明确动作，不能在创建页隐式触发。项目进入自动生产会话后，在 `story-generated` 阶段暂停等待脚本拆分；拆分成功后才允许继续现有的 storyboard/visual/audio/composition checkpoints。

### Provider 契约

文本 Provider 增加两个窄接口：

```python
generate_story_text(story: str, project_id: str) -> str
split_script(story_text: str, project_id: str) -> Script
```

`generate_story_text` 接受普通文本或兼容 JSON 文本响应，返回非空且有长度上限的文本；`split_script` 保留现有结构化 JSON 校验和规范化。旧 `generate_script` 保留为兼容入口，内部可委托“生成文本 + 拆分”或继续供逐步模式使用，但新创建页不得依赖它完成自动文本生成。

### 项目状态与存储

项目 payload 增加：

```text
generatedStoryText: string | null
storyTextVersion: number
```

`script` 在拆分前可以为空。正式生成文本和结构化剧本都写入项目事实来源；浏览器只保留未提交输入草稿，不保存 API Key。每次拆分前使用当前文本，成功后递增项目版本并清空下游导出状态。

阶段约束：

```text
story -> story-generated -> script-splitting -> awaiting-confirmation/script-completed
```

自动会话在 `story-generated` 返回可继续状态，不调用需要脚本的视觉/音频阶段。

### 创建页功能审查

- 故事输入：继续限制 10 到 2,000 字；生成按钮展示真实请求状态和稳定错误码。
- 模型选择：只展示已配置且可用的文本模型；未配置时明确显示 Mock，不伪装成真实模型。
- 时长：保留 30/60/90 秒选择并随项目输入持久化，后续拆分提示必须使用该值。
- 质量：在当前后端未消费质量参数前，显示为“预设”并在请求契约中保留，不宣称已经影响模型输出。
- 参考图：当前文本 Provider 不使用图片时，保留选择状态但在界面明确“剧本阶段暂不参与”，不得上传后静默丢弃；后续视觉阶段再接入文件存储。
- 文本预览：可编辑、保存为故事草稿；保存失败保留本地修改并显示错误。
- 下一步：只有存在已保存文本且项目 ID 有效时可进入剧本模块；剧本模块提供“拆分为剧本”和重试。
- 空状态和错误：没有文本、生成失败、拆分失败、旧项目只有 Script 时分别展示可执行操作，不显示无效按钮。

### 错误处理

Provider 错误继续映射为 `PROVIDER_TIMEOUT`、`PROVIDER_UNAVAILABLE`、`PROVIDER_INVALID_RESPONSE`、`PROVIDER_NOT_CONFIGURED`。文本生成失败不写入半成品脚本；拆分失败不覆盖上一版文本或脚本，并允许重试。版本冲突沿用现有 `expectedVersion` 机制。

## 验收标准

1. 全自动创建请求在 Provider 返回普通文本时成功，项目保存 `generatedStoryText`，不要求 `scenes/shots`。
2. 创建页显示并可编辑生成文本；保存后刷新仍能恢复。
3. 剧本模块在没有结构化脚本时显示“拆分为剧本”；点击后生成并显示场景/镜头。
4. 拆分失败不丢失文本，错误可见且可重试。
5. 自动生产会话不会在 `story-generated` 阶段越过脚本拆分直接生成视觉资产。
6. 现有逐步确认、旧项目恢复、模型控制台和脚本编辑回归测试继续通过。
