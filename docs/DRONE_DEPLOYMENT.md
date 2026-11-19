# ComicFlow 前后端分仓部署

日常提交请先读[Drone 下次提交操作手册](DRONE_SUBMISSION_RUNBOOK.md)（2026-09-24）。该手册只描述当前外部服务路径，含干净导出、两仓提交、ffmpeg/Worker故障处理和验收；下文包含历史内置栈，不混用。

## 2026-09-23 经理试用更新

用户授权新版部署到原宝塔服务器，不迁本机旧项目/素材。沿用两仓main/push、`backend_external_env`、`comicflow-server`与`comicflow-web`及18080。服务器空业务库0002/Redis专用命名空间0键已重新核对；先备份并显式升级0004，再发布。

后端Drone现在显式设置`DEPLOY_WORKERS=true`，通过已有schema检查后同版更新API/Worker/Beat并验证Worker ping。无healthcheck的Worker容器启动不等于Celery已就绪，ping最多尝试6次，每次10秒，失败间隔5秒；持续无应答仍阻断验收，不重试生成任务。独立运行发布脚本未设置该变量时仍只更新API；脚本不执行schema升级或数据导入。旧记录中的“Worker/Beat未启用”不再是本次发布目标。服务器模型库初查revision0，配置与真实生成是否可用须单独如实验收，不复制本机历史数据或旧付费队列。

## 2026-09-18 当前发布入口：宝塔外部数据服务

构建3实测clone成功，安装uv时files.pythonhosted.org下载超时。后续CI和Docker构建使用HTTPS阿里云PyPI镜像；uv版本仍0.11.25，`uv export --frozen --no-emit-project`导出原锁文件的版本/哈希，再`uv pip sync --require-hashes`安装。生产导出排除dev，CI包含dev；测试用`uv run --no-sync`避免再次按原海外URL下载。没有跳过Ruff/Mypy/pytest；Debian apt也采用HTTPS阿里云镜像并保留Debian签名验证。两仓pipeline全局GIT_CONFIG_PARAMETERS指定HTTP/1.1，解决实测GitHub HTTP/2检出中断；构建6已完成检出和镜像索引下载。

用户恢复部署。当前后端 `.drone.yml` 已改为执行 `deploy/backend-external.sh`，从新 Secret **backend_external_env** 读取外部配置，格式见根 `.env.server.example`。可将本机已配置的 `.env.server` 全文填入该 Secret；不要提交文件、不要贴进聊天或构建日志。旧 backend_env 不作为回退配置。

脚本组合 `compose.external-data.yml` 和 `compose.external-production.yml`，使用独立项目 `comicflow-server`；仅API加入 `comicflow-edge` 并提供 `comicflow-api` 别名，无宿主端口映射。前端继续18080与原API代理。不新建PostgreSQL/Redis/MinIO、不自动启动Worker/Beat、不搬旧队列。

部署顺序：配置校验 → 构建API → 网络就绪 → `alembic current --check-heads`只读检查 → 更新API → 请求项目列表。Secret缺失、schema空或版本不匹配时阻断，避免把预留恢复库自动建表。2026-09-18已按用户委托，在确认专用comicflow库无表后显式初始化至0002_model_registry；当前public有5张表，尚未迁入本地旧数据。后续恢复必须使用独立目标，不直接覆盖此库。Git推送/构建通过均不代表已经可正式生成。

现有外部S3配置使用MinIO直接地址，内部/公开签名Host应一致；旧Nginx的`/comicflow/`代理仅适用于旧内置MinIO，不把新签名URL改到此路径。正式域名/HTTPS整合后再单独核验。

下方内置数据栈、backend_env、自动迁移/启动worker的操作是历史兼容说明，**不适用于当前Drone入口**。本轮真实数据迁移、模型调用继续不执行。

更新：2026-09-17。依据用户提供的 Drone Docker socket 模板；两套服务部署在同一台服务器。

## 历史内置栈说明（当前Drone不执行）

以下段落用于旧内置栈维护；当前项目名称、Secret与启动范围以上方“宝塔外部数据服务”为准。

### 仓库与端口

| 用途 | GitHub 仓库 | 流水线文件 | Compose 项目 |
| --- | --- | --- | --- |
| 后端、Worker、Beat、数据库和对象存储 | https://github.com/leifengyang/comicflow | 本工作区 `.drone.yml` | `comicflow-backend` |
| 前端、Nginx | https://github.com/leifengyang/comicflow-web | 本工作区 `deploy/drone.web.yml`，导出后为 `.drone.yml` | `comicflow-web` |

前端默认 `http://服务器IP:18080`。Nginx 同源代理 `/api`、`/health` 到 `comicflow-api:8000`，
并代理 `/comicflow/` 到 MinIO，完整保留签名路径/查询及签名 Host。
API、PostgreSQL、Redis、MinIO API 和控制台均不映射宿主机端口。
两个 Compose 项目通过外部网络 `comicflow-edge` 连接。

当前本地 `docker-compose.yml` 保留原样，本配置不会搬运本地项目、图片或视频。
生产新建卷前缀是 `comicflow-backend_`；禁止用 `down -v` 做更新。

## 先配置 Drone

1. 在 Drone 同步并启用两个 GitHub 仓库，配置其 webhook。两个仓库均设置为 **Trusted**，
   因为流水线挂载 `/var/run/docker.sock`。只给可信提交者写入权限。
2. Docker Runner 必须运行在目标部署服务器上；样例没有 SSH 远程部署能力。
   如果 Drone 有多个 Runner，给这台 Runner 设置例如 `DRONE_RUNNER_LABELS=comicflow:production`，
   同时在两份流水线顶层添加 `node: { comicflow: production }`，避免被调度到不同主机。
3. 宿主 Docker 支持 Linux 容器。部署步使用 `docker:28-cli` 的 Compose 插件；所需镜像/包仓库要能访问。
4. 在**后端仓库**的 Drone Secrets 添加 `backend_env`，值是填写好的
   `deploy/backend.env.example` 全文。只允许可信 main 分支构建使用该 Secret，不向 PR 暴露。
5. 先部署后端，后部署前端。前端部署最后会经过 Nginx 请求 `/health`；后端未就绪会明确失败。

## 填写服务端配置

本页和backend_env用于内置数据服务部署。若要连接服务器已有的专用数据库/Redis/MinIO，新增的[独立外部数据配置](implementation/server-data-connections.md)使用.env.server与compose.external-data.yml；原backend.sh不自动切换该文件。不要仅向backend_env添加DATABASE_URL就认为已覆盖Compose内部地址。本次13A不更改Drone部署流程。

`backend_env` 至少必须填写：

| 字段 | 内容 |
| --- | --- |
| `POSTGRES_PASSWORD` | 长随机十六进制字符串；用于数据库 URI，不使用 `@`、`/` 等保留字符 |
| `MINIO_ROOT_USER` | 默认 `comicflow` |
| `MINIO_ROOT_PASSWORD` | 长随机值，至少 8 字符 |
| `EXPORT_DOWNLOAD_SECRET` | 独立长随机值，API/Worker 必须相同 |
| `S3_PUBLIC_ENDPOINT` | 浏览器及模型服务可访问的前端源地址，例如 `https://drama.example.com` 或 `http://服务器IP:18080`；不带路径 |

生产环境的 `.env` **不会**从本地自动上传。部署脚本从 Secret 写入临时 `deploy/runtime.env`，
权限 600，退出删除；Docker build 排除该文件。API、Worker、Beat 从同一配置文件获取模型参数。
不要把任何模型 Key 填到前端 `VITE_*` 中。

模板明确以 `PROVIDER_MODE=mock`、禁用图片/视频开始，首次部署和健康检查不调用收费模型。
真实调用时按现有 Provider 说明填写模型、地址、Key、`PROVIDER_MODE=real` 和
`PROVIDER_EVALUATION_GATE=passed`，以及对应图片/视频启用参数；不替你自动启用。
H3 默认 `768P`、`context-ir`。环境支持项可添加到这个 Secret，不需要修改 Compose 的逐项转发名单。

新版模型库将连接、模型和用途绑定保存到 PostgreSQL，凭据由独立主密钥加密；API/Worker/Beat
共享 `model-config` 卷，也可通过 Secret 设置 `MODEL_CONFIG_ENCRYPTION_KEY`。只有旧双槽配置仍是进程内临时状态，
长期配置请在模型管理中保存并按用途绑定。备份数据库时必须单独备份实际生效的主密钥。
**已有数据卷的数据库密码不能只通过修改 Secret 轮换**，
需先在数据库中执行相应账户密码变更并同步配置，否则服务无法连接。

当前应用尚沿用开发身份机制，部署文件不增加用户登录或控制台权限隔离。
因此在安全组中先把 18080 限制给自己；准备公开使用前须补齐身份认证/访问控制。
素材 URL 必须允许模型服务读取；正式对外访问建议在宿主反向代理配置 HTTPS，并让
`S3_PUBLIC_ENDPOINT` 使用相同 HTTPS 源，防止混合内容导致素材不可用。

## 每次发布

### 镜像缓存与网络

Drone各步骤设置 `pull: if-not-exists`，服务器已有同名镜像时复用缓存。前后端部署脚本执行
`docker compose build`，不使用强制更新基础镜像的 `--pull`。镜像缺失时仍需下载；这不是离线构建。
Python/uv/pip、Debian apt、Node/pnpm和Playwright相关包源也必须可访问或有可用缓存。
不要把服务器已有的 `python:3.12-slim` 当成 `python:3.12-bookworm`，也不要将PostgreSQL18替代16。

部署主机需准备与配置完全一致的镜像：

- 后端检查和构建：`python:3.12-bookworm`。
- 前端检查：`mcr.microsoft.com/playwright:v1.62.1-noble`；构建：`node:24-alpine`、`nginx:1.28-alpine`。
- 两端部署步骤：`docker:28-cli`。
- 后端基础设施：`postgres:16-alpine`、`redis:7-alpine`、`minio/minio:RELEASE.2025-04-22T22-12-26Z`、`minio/mc:RELEASE.2025-04-16T18-13-26Z`。

在部署服务器执行 `docker image ls --format '{{.Repository}}:{{.Tag}}'` 可只读盘点缓存。
Drone自动克隆步骤由Runner管理，也需要其克隆镜像及GitHub网络可用。
需要更新缓存镜像时由维护者显式拉取；复用缓存不会自动取得基础镜像的安全更新。

### GitHub授权失败

`Unable to start a new build: Bad credentials` 表示创建构建过程中GitHub鉴权失败，
与数据库/MinIO的 `backend_env` 无关。已通过Drone读写权限检查不等于GitHub凭据有效。
应由仓库关联授权账号重新登录Drone刷新GitHub授权；若仍失败，由管理员核查仓库使用的授权账号。
不要删除数据库卷、重建Secret、禁用签名校验或循环推送来处理鉴权错误。

### 发布顺序

两仓库都是 **main 分支 push**：检查 → 构建镜像 → 部署；Git 发布标签仅用于回溯，不重复触发部署。
首次发布先推后端 main 并通过健康检查，再推前端 main；分别为发布提交保留 Git 标签。每套流水线并发限制为 1，
镜像 tag 使用本次构建的提交 SHA。

后端：Ruff、Mypy、pytest → 构建 → 基础设施就绪 → 建桶 → Alembic 迁移 → 更新 API/Worker/Beat。
任一检查或迁移失败，脚本退出，不继续更新应用；不自动回滚数据库迁移。
前端：类型检查、构建、Node 测试、Playwright → Nginx 镜像 → 健康检查 → API 代理检查。
两仓库间没有自动部署顺序；首次使用按后端、前端顺序手动触发。

部署后只读验收：

```bash
curl -fsS http://127.0.0.1:18080/nginx-health
curl -fsS http://127.0.0.1:18080/health
curl -fsS http://127.0.0.1:18080/api/projects
docker ps --filter label=com.docker.compose.project=comicflow-backend
docker ps --filter label=com.docker.compose.project=comicflow-web
```

之后在页面确认路由刷新、已有素材预览和 SSE 正常。不要以“生成视频”作为部署健康检查。
改变前端端口时修改前端 Compose 的默认值，或在 Drone deploy 步增加 `WEB_PORT` 环境变量，
并同步 `S3_PUBLIC_ENDPOINT`、安全组和宿主反向代理。

## 从当前工作区导出两个干净目录

```powershell
uv run python scripts/package_deployment.py --output var/releases/2026-09-17
```

输出 `comicflow/` 和 `comicflow-web/`，分别包含自己的 `.drone.yml`、README、源码和部署文件。
脚本只复制白名单，不执行 Git、不复制历史、不覆盖已有目录；保留 frontend/ 拓扑以复用冻结锁文件。
发布前比较本地环境中的凭据并扫描常见密钥格式，发现风险只报文件名，不打印密钥。
该扫描不能代替人工检查；上传只对导出目录进行，不对原工作区运行 `git add .`。

已存在远端提交时，先 clone，再把导出文件合入并检查差异，不能 force push。
数据库和 MinIO 的迁移/备份是独立操作，本次只发布代码。后续直接在分仓修改时，相应仓库的
`.drone.yml` 才是生效配置，不要误改另一仓库。

## 本次验证与上线状态

当前生产依赖已修正：`httpx` 从开发依赖移至运行依赖，镜像不再先安装尚未 COPY 的项目，
生产命令直接使用虚拟环境可执行文件，避免启动时再次联网同步开发依赖。

本轮检查结果见 [验证记录](DRONE_VERIFICATION.md)，上传提交记录见原工作区 `status/HANDOFF.md` 的 2026-09-17 条目。
发布前执行完整门禁，**流水线保留阻断检查，不跳过以强行上线**。
仓库上传、Drone 配置、构建通过和服务器健康是四个独立状态；上传成功不等于上线成功。

## 先部署，再迁移数据

用户已确认先部署空数据服务，验证首页、API 与素材代理，再单独实施本地数据迁移。
首次部署产生的是服务器独立新数据卷，不会带上本机已有项目。此阶段先不要正式创建内容；
如目标已有数据，不得当成空库覆盖。迁移时需暂停自动部署与应用写入，先备份目标并使用独立空库恢复，
不能把 dump 直接灌进已经运行 Alembic 的同名表。完整步骤与验收见 [数据迁移方案](DATA_MIGRATION_PLAN.md)。
