# provider-adapters Specification

## Purpose
为 ComicFlow 提供稳定、可回退且不泄露凭据的多媒体与审核 Provider 行为契约，使真实适配器可以替换 Mock 而不改变创作流水线的外部语义。

## Requirements

### Requirement: Asynchronous visual generation

图像/视频 Provider SHALL 支持提交任务、轮询状态、超时和可分类失败，并返回现有动态视觉资产契约要求的元数据。

#### Scenario: Polling completes successfully
- **WHEN** Provider 提交任务后轮询得到完成状态和资产引用
- **THEN** 系统返回包含 provider、model、request reference、媒体类型和有效时长的视觉资产元数据

#### Scenario: Polling times out
- **WHEN** Provider 在规定期限内没有完成
- **THEN** 系统返回稳定的超时错误分类，不发布无效资产，并保留可重试状态

#### Scenario: Provider failure falls back
- **WHEN** 真实视觉 Provider 返回不可恢复错误且启用 2D fallback
- **THEN** 系统返回标记为 fallback 的可用元数据，并不得伪装成真实 Provider 成功结果

### Requirement: Audio and lip-sync metadata

TTS 与 lip-sync Provider SHALL 返回可引用的资产和确定的时长、采样率、音色、起止时间元数据；业务状态 MUST NOT 保存原始音频 bytes。

#### Scenario: Audio asset is linked to timeline
- **WHEN** TTS 和 lip-sync 生成成功
- **THEN** 时间轴通过资产 ID 和时间范围引用结果，字幕时长与音频时长一致

#### Scenario: Audio generation fails
- **WHEN** TTS 或 lip-sync Provider 失败
- **THEN** 系统返回稳定失败分类，保留此前有效资产，并且不发布不完整时间轴

### Requirement: Moderation outcomes

审核 Provider SHALL 返回 `approve`、`block` 或 `review` 之一，并将超时归类为可审查失败；审核阻止 MUST NOT 扣除生成 Credit。

#### Scenario: Content is blocked
- **WHEN** 审核结果为 `block`
- **THEN** 项目进入阻止状态，生成接口返回稳定错误，且 Credit 账本没有生成扣费

#### Scenario: Content requires review
- **WHEN** 审核结果为 `review` 或 Provider 超时
- **THEN** 项目进入待审核状态，系统不启动付费生成作业
