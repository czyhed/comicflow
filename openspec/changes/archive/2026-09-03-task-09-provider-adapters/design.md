## Context

当前 ProductionPipeline 依赖已有 Provider Protocol 和确定性 Mock 实现；文本 Provider 已有 OpenAI-compatible 边界，图像/视频、TTS/lip-sync 与审核的真实适配器仍需统一错误、轮询、资产和评测语义。所有实现必须继续兼容现有 API 与时间轴结构。

## Goals / Non-Goals

**Goals:**

- 在 Provider adapter 内封装外部 API、超时、重试、轮询和错误分类。
- 通过资产引用和版本化元数据连接媒体结果，不把二进制内容放入业务状态。
- 用固定样例和门禁报告控制 real mode 的启用。

**Non-Goals:**

- 本 change 不切换默认 Mock，不提交真实 API key，不执行线上部署。
- 本 change 不改变 React 工作区交互或数据库迁移模型。

## Decisions

### Adapter-first boundary

外部 HTTP 调用只允许出现在 `providers` adapter；Pipeline 只消费现有 Protocol。相比在 Pipeline 中直接调用供应商，这能隔离凭据、便于 stub 测试，并保持 Mock/real 可替换。

### Explicit state machine for async jobs

视觉任务使用 `submitted -> polling -> completed|failed|timed_out` 状态机，轮询策略在 adapter 内实现。相比无界等待，显式超时能保证任务最终可重试且不会阻塞 Worker。

### Metadata-only persistence

媒体 bytes 通过 asset store 保存，项目和时间轴只保存 asset ID、provider/model、时长和请求引用。相比将 bytes 写入 JSON/数据库，这保持状态可恢复并限制敏感数据扩散。

### Evaluation gate before real mode

selector 只有在完整评测报告通过且凭据齐全时才允许 real mode；缺失指标、成本或许可证证据一律拒绝。默认值继续为 Mock，以避免本地测试产生费用。

## Risks / Trade-offs

- [外部 Provider 状态不稳定] -> 使用有限重试、明确超时和可分类错误，并保留 fallback metadata。
- [不同 Provider 返回格式不一致] -> adapter 内做 schema 校验，Pipeline 只接收统一 Protocol 结果。
- [评测样本不足以代表所有内容] -> 固定样例仅作为门禁基线，真实试点继续记录扩展样本，不把本地 Mock 结果当作真实通过。

## Migration Plan

先实现并测试 adapter 与 selector，保持 `PROVIDER_MODE=mock`；在真实账号和资源完成评测后，单独更新配置启用 real mode。回滚时恢复 Mock selector，不需要回滚业务数据结构。
