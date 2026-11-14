---
name: manju-laoli-drama
description: Apply the manju-laoli drama planning rules to Chinese story planning, script splitting, shot continuity, dialogue timing, and production quality checks while preserving ComicFlow's JSON Script Contract.
---

# Manju Laoli Drama Adapter

来源：`lixiaoxiao9888-create/manju-laoli-skill`，审查版本 `aa20fb60054ae52553a4b13f8810ed2fcd89ba70`。
这是 ComicFlow 的阶段适配 Skill，不能替换 H3 视频 Skill，也不能把外部 Seedance 输出格式直接写入项目。

## 路由

- `story`：只读取 `references/story-planning.md`，输出故事正文及故事元数据。
- `script`：读取 `references/script-planning.md`，将故事拆成可执行场景和镜头。
- `continuity`：读取 `references/continuity-and-quality.md`，生成动作状态、对白语速和连续性信息。
- `quality`：读取 `references/continuity-and-quality.md`，执行 P0/P1/P2 质量规则。

## 共同约束

- 面向用户的内容使用简体中文，继续遵守 ComicFlow 的 Script Contract。
- 保留用户指定的人物、事件、台词和结尾方向；以调用方本次任务的字段和时长为准。
- 故事阶段组织叙事正文；镜头字段、数量与连续性规则只用于剧本及后续阶段。
- 输出结构化字段供下游使用，不直接输出外部 Skill 的 Markdown 分镜格式。
