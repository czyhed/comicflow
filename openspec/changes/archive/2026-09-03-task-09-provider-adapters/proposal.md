## Why

任务 08 的本地 Mock 创作链路已经跑通，但任务 09 的图像/视频、音频、口型和审核 Provider 仍缺少统一的异步边界与评测门禁。现在补齐这些边界，可以在不改变默认 Mock 行为的前提下，为后续真实试点提供可测试、可回退、可审计的接入基础。

## What Changes

- 增加图像/视频 Provider 的异步提交、轮询、超时、失败分类和 2D 回退元数据。
- 增加 TTS 与 lip-sync Provider 的稳定资产和时间轴元数据契约。
- 增加审核 Provider 的 approve/block/review、超时和指标语义。
- 建立中文双角色样例的质量、时延、并发、成本、许可证和失败率评测输出。
- 评测门禁未通过时继续拒绝 real mode，默认运行时保持 Mock。

## Capabilities

### New Capabilities

- `provider-adapters`: 图像/视频、TTS、lip-sync 和审核 Provider 的稳定适配器契约。
- `provider-evaluation`: 可重复的 Provider 评测矩阵与 real mode 门禁。

### Modified Capabilities

无。

## Impact

- `backend/src/comicflow/providers/`：新增或扩展 Provider adapter、错误分类和评测实现。
- `backend/src/comicflow/production/`：保持现有 Protocol 兼容并接入 Provider 元数据。
- `backend/tests/`：增加异步轮询、媒体元数据、审核和评测门禁测试。
- `docs/adr/0006-model-provider-selection.md`、任务记录和本地回归证据。
