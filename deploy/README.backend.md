# ComicFlow 后端

FastAPI + Celery + PostgreSQL + Redis + MinIO。配套前端：
https://github.com/leifengyang/comicflow-web

部署说明：[部署说明](../docs/DRONE_DEPLOYMENT.md)。
多模型配置：[模型控制台说明](../docs/implementation/persistent-model-console.md)。
推送 main 后先检查，再通过 Drone Runner 的 Docker socket 部署；Git 版本标签仅用于回溯，不重复触发部署。
当前发布连接宝塔已有数据服务，使用 Drone Secret `backend_external_env`，格式参考 `.env.server.example`。
部署入口 `deploy/backend-external.sh` 仅更新 API，不新建数据服务，不启动 Worker/Beat。
数据库须已恢复/初始化到当前 Alembic head；空库或旧版本会阻断部署，不自动建表。
旧 `backend_env` 与 `deploy/backend.sh` 仅保留给内置栈，当前 Drone 不再调用。
后端默认仅在 Docker 内网监听 8000；前端统一使用 18080 代理。

本地开发：`uv sync --frozen`，显式设置测试用 `COMICFLOW_RUNTIME=memory` 与
`PROVIDER_MODE=mock` 后执行 `uv run uvicorn comicflow.api.app:app --app-dir backend/src --port 8000`。
测试：`uv run pytest backend/tests -q`；静态检查：`uv run ruff check backend/src backend/tests`、
`uv run mypy --package comicflow`。

这是当前工作区源码的白名单导出；不包含原工作区的密钥、项目数据库、图片、视频和 Git 历史。
