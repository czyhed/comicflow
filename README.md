# ComicFlow

ComicFlow 将故事整理为可编辑剧本，并通过角色资产、分镜生产、任务队列和媒体导出完成动态漫剧制作。

- 文档导航：[docs/README.md](docs/README.md)
- 架构与领域约束：[工程规约](docs/PROJECT_ENGINEERING_RULES.md)、[数据流](docs/DATA_FLOW.md)
- 部署与运维：[Drone 部署说明](docs/DRONE_DEPLOYMENT.md)

## 本地开发

```bash
pnpm install
pnpm test
pnpm dev:web
pnpm dev:worker
```

当前基础切片使用确定性的 Mock 运行时和本地 JSON 存储，验证 `ProductionPipeline` 的公共行为。浏览器访问 `http://127.0.0.1:3000/health` 可检查 Web 服务。

设置 `.env` 中的 `DATABASE_URL`、`REDIS_URL` 和 `S3_ENDPOINT` 后，先执行 Alembic 迁移，再启动 Web；API 通过 SQLAlchemy 基础设施适配器使用 PostgreSQL 持久化业务状态。生产默认 `COMICFLOW_RUNTIME=postgresql`。

本地无 Docker 依赖时可显式使用内存运行时验证 HTTP 流程：将 `COMICFLOW_RUNTIME=memory` 后启动 API。该模式只用于本地 Mock 验收，不改变生产持久化配置。

```bash
uv run alembic upgrade head
uv run uvicorn comicflow.api.app:app --app-dir backend/src --port 8000
uv run celery -A comicflow.worker.celery_app:celery_app worker --loglevel=INFO
uv run celery -A comicflow.worker.celery_app:celery_app beat --loglevel=INFO
```

Web 与 Worker 使用 `EXPORT_DOWNLOAD_SECRET` 签发短时下载地址；生产环境必须配置同一个高强度随机值。FFmpeg 临时输出目录可通过 `EXPORT_OUTPUT_DIR` 调整，完整导出包会原子发布到对象存储。

启动 PostgreSQL、Redis 和 S3 兼容对象存储：

```bash
docker compose up -d
```

Drone 现按前后端独立仓库的发布标签流水线部署到同一服务器。前端 18080，
后端通过 Docker 内网访问。后端 Drone Secret 使用 `backend_env`，配置与上传方法见
[部署说明](docs/DRONE_DEPLOYMENT.md)。本地开发 Compose 不受影响。

真实模型和生产存储不会在前端暴露；优云免费模型通过 Provider Adapter 接入，Mock 仅用于开发、测试和故障降级。
