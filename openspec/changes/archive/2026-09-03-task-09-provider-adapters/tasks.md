## 1. Visual Provider

- [x] 1.1 为异步提交、轮询完成、超时和失败分类编写失败测试；验证：`uv run pytest backend/tests/test_visual_provider.py -q`
- [x] 1.2 实现最小视觉 adapter、有限轮询和 2D fallback metadata；验证：上述专项测试通过且默认 Mock 不变
- [x] 1.3 运行 Ruff、mypy 和相关 Pipeline 回归；验证：`uv run ruff check backend/src backend/tests`、`uv run mypy --package comicflow`

## 2. TTS and Lip-sync

- [x] 2.1 为音频元数据、资产引用、时间轴一致性和失败保留旧资产编写失败测试；验证：`uv run pytest backend/tests/test_audio_provider.py -q`
- [x] 2.2 实现 adapter 结果映射和错误分类，不持久化原始 bytes；验证：专项测试与媒体测试通过

## 3. Moderation

- [x] 3.1 为 approve/block/review、超时和不扣 Credit 编写失败测试；验证：`uv run pytest backend/tests/test_moderation_provider.py -q`
- [x] 3.2 接入审核 adapter 和稳定指标；验证：审核专项、Credit 生命周期和 API 测试通过

## 4. Evaluation Gate

- [x] 4.1 为固定中文双角色样例、指标输出、凭据缺失和 gate 拒绝编写失败测试；验证：`uv run pytest backend/tests/test_provider_evaluation.py -q`
- [x] 4.2 实现可重复评测报告与 selector gate；验证：Mock 报告外部成本为零，未通过时 real mode 被拒绝

## 5. Local Verification and Review

- [x] 5.1 运行完整本地门禁：Compose、迁移、Docker smoke、pytest、Ruff、mypy、TypeScript、Vite 和 Playwright。
- [x] 5.2 请求代码审查并修复 Critical/Important 问题；验证：审查结论无未处理高优先级问题
- [x] 5.3 更新 ADR、任务记录和交接文档；验证：文档明确 real mode 仍需真实账号评测，未执行 Drone 部署
