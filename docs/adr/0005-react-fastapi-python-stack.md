# 采用 React 前端与 FastAPI/Python 后端

ComicFlow 后续正式技术基线采用 React + TypeScript + Vite 单页前端，以及 Python 3.12+、FastAPI、Pydantic、SQLAlchemy 2 和 Alembic 构建的模块化单体 API；独立 Python Worker 使用 Celery + Redis 传递作业，并以 PostgreSQL 持久化生产状态和 transactional outbox。相比继续扩展 Next.js/Node.js 原型，该选择增加了任务 01～07 的迁移成本，但能让业务 API、异步生成和 PyTorch/Transformers/Diffusers 模型生态共享 Python 类型与运行时，同时保留 ADR 0001～0004 确立的模块化单体、独立 Worker、持久化生产流水线、Provider Adapter、Mock 优先、MinIO/S3 和 FFmpeg 边界。

## 影响

任务 01～07 的 Node.js 实现作为外部行为、接口语义、导出格式和测试场景的迁移参考，不再承载后续生产功能。身份与额度、真实模型接入和 Drone 生产部署应以迁移后的 React/FastAPI/Python 基线为目标；迁移需重建路由、持久化、作业编排、测试和 CI，但不得改变已经验收的领域行为。
