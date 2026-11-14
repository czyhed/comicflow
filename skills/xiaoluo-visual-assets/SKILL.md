---
name: xiaoluo-visual-assets
description: Apply XiaoLuo visual asset rules to character prompts, character reference images, independent character views, scene backgrounds, spatial anchors, and cross-shot identity locks.
---

# XiaoLuo Visual Assets Adapter

来源：`zhurui0523/XiaoLuo-AI-Drama-Skill`，审查版本 `fc2852b62c88eac1084d99d5db7fac316ab20e5c`。
这是 ComicFlow 的视觉资产阶段 Skill，图片 Provider、模型、协议和 API 地址仍由项目配置决定。

整张正面/严格侧面/背面参考板（character-board）只读取 [整板规则](references/character-board.md)，不套用主图的单人正面构图。

## 路由

- `character-prompt`：读取 `references/character-prompt-writing.md`，按调用方用途输出角色设定或主图提示词。
- `character-reference`：读取 `references/character-assets.md`。
- `character-view`：读取 `references/character-assets.md`。
- `character-board`：读取 `references/character-board.md`，以已确认主图进行单次图生图。
- `character-text-board`：读取 `references/character-text-board.md`，从角色外观/服装和项目风格直接文生图，输出脸部特写+正面/侧面/背面全身整板。
- `scene-background`：读取 `references/scene-assets.md`。

## 共同约束

- 用户保存的提示词是创意来源，Skill 追加可执行的一致性约束。
- 主图与整板均先保存候选，经用户明确确认才用于视频。图生图整板以确认主图锁定身份；文字整板创建新的视觉身份，不声称保留旧主图的脸。
- 两种整板各读取对应规则，不叠加主图的单一正面/竖版构图。文字整板使用已保存外观/服装，不继承旧主图提示词；旧 `front`、`three-quarter`、`profile` 分图保持历史读取与恢复。
- 角色锁和场景锚点输出为结构化元数据，供图片请求和 H3 Prompt 编译使用。
