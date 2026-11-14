## Why

用户首要目标是可操作、好看的漫剧前端演示。复用 iToVideo 完整项目，可保留已完成的页面和交互，减少接口翻译及重写。

## What Changes

- 在 `C:/Users/lmk/Documents/ChatGPT/itovideo-drama/` 建立独立副本并记录来源版本。
- 保留原画布、项目、配方、模型、Studio 和后期页面，调整品牌与漫剧内容。
- 用已有角色图片制作明确标识的示例项目，支持画布编辑、保存、视频预览、后期编辑和本地导出。
- 原后端连接隔离的本地 PostgreSQL 与素材存储；演示不调用收费模型。

## Capabilities

### New Capabilities

- `drama-demo`: 独立漫剧演示、持久示例项目、风格选择及后期导出。

### Modified Capabilities

无；ComicFlow 原产品行为保持。

## Impact

实现目录为用户明确授权的独立副本，覆盖 CLI 返回的 repo-local 实现目录建议；ComicFlow 仅维护本次规划及方向记录。原 iToVideo 和 ComicFlow 业务代码、数据不覆盖，不发布服务器。
