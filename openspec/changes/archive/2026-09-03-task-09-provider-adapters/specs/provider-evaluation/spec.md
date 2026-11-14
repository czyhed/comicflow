## Purpose

为真实 Provider 选择提供可重复、可审计的证据，防止仅凭宣传信息切换生产模式，并让质量、成本与可靠性门禁可以在本地和试点环境复现。

## ADDED Requirements

### Requirement: Reproducible provider evaluation

评测 MUST 使用固定的中文双角色样例集，并输出质量、时延、并发、成本、许可证和失败率指标及其 Provider/model/config 版本信息。

#### Scenario: Evaluation produces an auditable report
- **WHEN** 使用同一版本样例集运行评测
- **THEN** 系统生成结构稳定的指标报告，包含每个样例的成功/失败和汇总指标

#### Scenario: Gate rejects incomplete evaluation
- **WHEN** 任一必需指标缺失、失败率超限或许可证未确认
- **THEN** Provider selector 拒绝 real mode，并保持默认 Mock mode

### Requirement: Credential and cost boundaries

评测和运行时 MUST 从环境或部署 Secret 读取凭据；凭据不得进入浏览器、数据库、日志或任务载荷，Mock 运行不得产生外部费用。

#### Scenario: Missing credential is rejected
- **WHEN** real mode 缺少所需 API key
- **THEN** 系统返回稳定配置错误且不发起外部请求

#### Scenario: Mock evaluation has no external charge
- **WHEN** 使用 Mock Provider 运行完整评测
- **THEN** 报告标记为 mock，外部成本为零，并且 selector 不把它标记为真实通过
