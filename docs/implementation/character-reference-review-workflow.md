# 角色参考图确认与三视图

状态：已实现，已完成万象候选图和 `wan2.6-image` 三视图受控验证

## 真实验证记录（2026-09-12）

候选图确认后，将 Provider 切换为 `wan2.6-image` / `wan26-image`，按正面、三分之四侧面、侧面执行 3 次图生图请求。3 张图片全部成功写入 MinIO，角色状态为 `views-ready`；每张图都使用同一张已确认主参考图作为输入。未调用文本或视频 API，未自动重试。免费额度的实际消耗需在百炼控制台确认。

## 用户流程

1. 在角色页保存完整的名称、外观、服装和性格。
2. 点击“生成候选角色参考图”。图片只保存为候选，不会成为正式参考图，也不会自动进入视频。
3. 用户确认候选图后，候选图才写入 `referenceImageUrl` / `referenceImageObjectKey`。
4. 点击“基于确认图片生成三视图”，按顺序生成正面、三分之四侧面和侧面图。
5. 三视图分别保存到角色卡的 `referenceViews`，并带有 `view` 和 `viewLabel`。

候选图可以重复生成。重新生成候选图不会覆盖当前已确认图片；角色外观、服装或参考图提示词发生变化时，候选图和三视图会失效。

## 图片协议

三视图使用百炼 `wan2.6-image` 的图像编辑模式：

- `enable_interleave=false`
- 每次输入 1 张已确认参考图
- `n=1`
- `prompt_extend=true`
- `watermark=false`

后端优先按 `referenceImageObjectKey` 从 MinIO 读取图片并转为 Base64，再发送给图片 Provider，避免向上游暴露本机 MinIO 地址。每个视角使用独立的明确提示词，避免三张图互相覆盖视角含义。

当前 `openai-image` Adapter 仍是 Chat Completions 文生图协议，遇到图生图请求会返回 `IMAGE_EDIT_UNSUPPORTED`，不会忽略输入图并错误地生成独立图片。若用户使用其他图片平台，需按该平台的图像编辑协议新增 Adapter。

## 数据状态

角色卡新增以下可选字段，旧角色仍可读取旧字段：

- `referenceImageCandidate`：候选资产，状态为 `candidate`。
- `referenceImageStatus`：`none`、`candidate`、`approved`、`views-partial` 或 `views-ready`。
- `referenceViews`：带 `front`、`three-quarter`、`profile` 标签的正式视角资产。

现有 `referenceImageUrl` 和 `referenceImageObjectKey` 继续表示唯一已确认的主参考图。确认新候选会清空旧三视图，但不会删除对象存储中的旧文件。

## 接口

- `POST /api/projects/{project_id}/characters/{character_id}/reference-candidate`
- `POST /api/projects/{project_id}/characters/{character_id}/reference-candidate/approve`
- `POST /api/projects/{project_id}/characters/{character_id}/reference-views`

三视图接口默认只补齐缺失视角；实现中每个成功视角立即持久化，后续失败会保留已生成视角并返回 `REFERENCE_VIEWS_PARTIAL`。

## 验证

离线验证使用假图片 Provider 和 `httpx.MockTransport`，未连接百炼或其他图片服务：

```text
25 个角色/图片相关后端测试通过
Ruff 通过
Mypy 通过
前端构建通过
角色 Playwright 测试 2 项通过
```

真实验证前只需先配置并启用 `wan2.6-image` 图片 Provider，确认一张候选图，再由用户明确确认后生成三视图。三视图每张都是一次图片生成请求，不能自动重试。
