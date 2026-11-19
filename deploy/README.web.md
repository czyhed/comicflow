# ComicFlow 前端

React + TypeScript + Vite，生产使用 Nginx。后端仓库：
https://github.com/leifengyang/comicflow

部署说明：[部署说明](../docs/DRONE_DEPLOYMENT.md)。
多模型配置：[模型控制台说明](../docs/implementation/persistent-model-console.md)。
推送 main 后先检查，再通过 Drone Runner 的 Docker socket 部署到 18080；Git 版本标签仅用于回溯，不重复触发部署。
`/api`、`/health` 通过同源代理连接后端。当前外部MinIO素材使用后端签发的直接地址；`/comicflow/`代理只兼容旧内置MinIO，不要改写新素材的签名URL。

保留 `frontend/` 目录以复用 pnpm lockfile。
本地开发：`pnpm install --frozen-lockfile`、`pnpm dev`。
默认开发 API 为 127.0.0.1:8000；如需更改，在 `frontend/.env.local` 中设置
`VITE_API_PROXY_TARGET=http://127.0.0.1:你的端口`。
不要在 Vite 环境变量中放模型 API Key。

构建：`pnpm build`。页面测试：构建后执行 `pnpm --dir frontend test:e2e`。
生产后端地址由 `deploy/nginx.conf` 的 Docker 服务别名确定。
