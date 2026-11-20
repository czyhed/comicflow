# Drone 下次提交操作手册

更新：2026-09-24。用于现有宝塔服务器的日常代码发布；依据 2026-09-23 成功发布记录和当前脚本整理。本次编写未推送或部署。

## 当前入口

| 项目 | 后端 | 前端 |
| --- | --- | --- |
| GitHub | 内部 comicflow 仓库 | 内部 comicflow-web 仓库 |
| 触发 | `main` 分支的 `push` | `main` 分支的 `push` |
| 本工作区流水线来源 | `.drone.yml` | `deploy/drone.web.yml`，导出后变成 `.drone.yml` |
| 部署脚本 | `deploy/backend-external.sh` | `deploy/web.sh` |
| Compose 项目 | `comicflow-server` | `comicflow-web` |
| 配置 | Drone Secret `backend_external_env` | 同源 `/api`、`/health` 代理 |
| 上次成功提交 | `bb2ac379d792aefccee0681bc34293ff404de967`，Drone 8 | `4db450a4b40c21e043b74f371f2de1edbbccde18`，Drone 6 |

上次访问入口：`http://110.42.51.234:18080`。这是历史成功基线，不代替提交当天的服务器检查。

沿用服务器外部 PostgreSQL、Redis、MinIO；后端使用 `compose.external-data.yml` 和 `compose.external-production.yml`，Drone 显式设置 `DEPLOY_WORKERS=true`，更新同版 API/Worker/Beat。两端通过 `comicflow-edge` 网络及 `comicflow-api:8000` 通信。不要套用旧 `backend_env`、`comicflow-backend` 或 `deploy/backend.sh` 内置栈流程。

## 1. 确定本次发布范围

- 仅前端页面修改：只提交前端仓库；仅后端修改：只提交后端仓库。
- 涉及新 API 或新协议：后端成功且验收后，再提交前端。
- 风格预设目录在后端 `production/visual_styles.py`。新增“港风武侠胶片”需要后端发布，现有前端会从目录读取，无需为了新增选项单独修改前端。
- 确认待发布差异和旧构建状态。取消旧构建需在 Drone 中停止对应 running/pending 构建并核实，不要连续空提交制造排队。
- 本机项目、素材、模型配置主密钥及 Redis 正式切换是独立迁移任务，普通代码发布不执行这些操作。服务器已有模型配置保留；不因代码更新重新导入本机模型库。

## 2. 从主工作区导出干净文件

在本工作区根目录运行 PowerShell。下列命令仅导出，不提交：

```powershell
$releaseId = Get-Date -Format 'yyyyMMdd-HHmmss'
$releaseRoot = Join-Path (Get-Location) "var/releases/$releaseId"
uv run python scripts/package_deployment.py --output "$releaseRoot/packages"
```

输出 `packages/comicflow` 和 `packages/comicflow-web`。导出路径必须不存在；脚本按白名单复制、扫描凭据，不包含本机数据库、输出图片和私有运行配置。出现凭据扫描错误时停下检查，不绕过。当前未提交工作很多，导出读取的是工作区文件，必须核对范围。

主工作区不要执行 `git add .`。两个发布仓库应从各自远端最新 main 单独克隆，保留其历史：

```powershell
git clone --branch main <内部 comicflow 仓库地址> "$releaseRoot/backend-git"
git clone --branch main <内部 comicflow-web 仓库地址> "$releaseRoot/web-git"
```

只发布一端时只克隆那一端。把对应导出目录的文件合入该克隆，随后检查 `git diff` 和未跟踪文件。下面以“仅前端”为例，逐文件覆盖，不移动或删除远端既有文件：

```powershell
$exportDir = Join-Path $releaseRoot 'packages/comicflow-web'
$publishDir = Join-Path $releaseRoot 'web-git'
Get-ChildItem -LiteralPath $exportDir -Recurse -File | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($exportDir, $_.FullName)
    $destination = Join-Path $publishDir $relative
    New-Item -ItemType Directory -Force -Path (Split-Path $destination) | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $destination
}
git -C "$publishDir" status --short
git -C "$publishDir" diff --stat
git -C "$publishDir" diff -- .drone.yml
git -C "$publishDir" diff --check
```

后端把 `exportDir` 改为 `packages/comicflow`，`publishDir` 改为 `backend-git`。逐文件复制不会同步源码删除；若本次确有删除，必须逐项核对再在发布克隆中处理。特别检查远端已有、本工作区尚未同步的修复，不能用旧模板覆盖它们。2026-09-24 已将前端 ffmpeg 安装步骤同步回 `deploy/drone.web.yml`。

## 3. 检查并提交

在发布克隆里检查源码、锁文件和流水线差异，只暂存本次审核过的具体路径：

```powershell
# 示例：仅修改前端流水线时；其他改动逐项加入实际路径。
git -C "$publishDir" add -- .drone.yml
git -C "$publishDir" diff --cached --stat
git -C "$publishDir" diff --cached --check
git -C "$publishDir" commit -m "fix(ci): install ffmpeg for video browser tests"
```

提交信息按实际内容填写，不照抄示例。离线检查使用 mock/隔离测试环境，不加载业务凭据，不用真实生成验证发布。

| 后端 CI 门禁 | 前端 CI 门禁 |
| --- | --- |
| uv 0.11.25、冻结锁文件和哈希安装；Ruff、Mypy、完整 pytest | Playwright v1.62.1-noble、安装 ffmpeg；pnpm 11.19.0 冻结安装、typecheck、build、Node 测试、Playwright |

本地检查通过后，在明确执行发布的这一步推送（**会触发 Drone 自动部署**）：

```powershell
git -C "$publishDir" push origin main
```

如提示 non-fast-forward，先 fetch 并审查远端新增提交、正常合并后重新检查；不 force push。需要发布标签时对已确认成功的提交创建唯一标签；当前流水线只响应 push/main，标签不是重跑入口。

## 4. 查看 Drone 结果及服务器状态

在对应仓库构建页核对提交 SHA、构建号、checks 和 deploy 两个步骤。前后端各自并发为 1，两仓没有自动发布先后顺序。推送成功、测试成功、部署成功、线上可用是不同状态。

后端脚本实际顺序：配置校验 → 构建 API 镜像 → 网络就绪 → `alembic current --check-heads` 只读核查 → 更新 API/Worker/Beat → Worker ping → API 项目读取。脚本不自动 `alembic upgrade`。上次已到 `0004_image_jobs`，不要重复初始化；未来有新迁移时先备份、单独安排升级，再发布。

前端脚本实际顺序：构建 Nginx 镜像 → 网络就绪 → 更新前端并等待健康 → 容器内请求 `/health`，验证 API 代理。

在宝塔服务器终端进行只读验收：

```sh
curl -fsS http://127.0.0.1:18080/nginx-health
curl -fsS http://127.0.0.1:18080/health
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/api/projects
docker ps --filter label=com.docker.compose.project=comicflow-server
docker ps --filter label=com.docker.compose.project=comicflow-web
docker inspect --format '{{.Config.Image}}' comicflow-server-api-1 comicflow-server-worker-1 comicflow-server-beat-1 comicflow-web-web-1
docker exec comicflow-server-worker-1 celery -A comicflow.worker.celery_app:celery_app inspect ping --timeout 10
```

最后在浏览器检查首页、项目列表、页面刷新和已有素材读取。镜像 SHA 应对应各自目标提交；真实生图/视频不作为部署健康检查。将提交 SHA、Drone 构建号、检查结果和已知缺口记录到发布文档。

## 5. 上次遇到的故障

| 日志/现象 | 处理 |
| --- | --- |
| `spawnSync ffmpeg ENOENT`，80通过/1失败 | Playwright 检查容器缺少 ffmpeg；安装必须发生在 `frontend-checks` 执行 E2E 之前。在后端或 Nginx 安装无效。修复源模板再导出，不能跳过测试。 |
| `Error: No nodes replied within time constraint` | 先看 Worker 日志及 ping。Compose started 不等于 Celery 就绪；现有脚本最多6次、每次10秒、间隔5秒等待。持续失败应查 Redis、命名空间、Worker 配置和启动错误，不反复提交生成。 |
| deploy 失败但容器已经变成新版本 | 部署后验收可能失败；先核对实际镜像 SHA/健康状态，不假设仍是旧版，不盲目重推。 |
| GitHub HTTP/2 检出失败 | 保留流水线全局 `GIT_CONFIG_PARAMETERS` 的 HTTP/1.1 设置及 clone 重试；先区分网络和鉴权。 |
| `Bad credentials` | 刷新 Drone 所关联 GitHub 账号的授权，核对仓库权限；无需重建数据库或更换模型 Key。 |
| Python 包下载超时 | 保留已有 HTTPS 镜像源、冻结版本与哈希校验；镜像缺失仍需联网，缓存不等于完全离线。 |
| schema 不在 head | 发布会阻断。先核对当前版本与待发布迁移，备份后单独处理，不跳过校验或覆盖数据库。 |

若需回退代码，在发布仓库对具体变更做可审查的 revert 并重新走 CI；先核对数据库兼容性，代码回退不等于数据库降级。禁止 `down -v`、清库或清队列作为发布修复。

## 相关记录

- [上次经理试用完整发布记录](implementation/manager-pilot-deployment-2026-09-23.md)
- [部署配置与历史内置栈说明](DRONE_DEPLOYMENT.md)
- [验收记录](DRONE_VERIFICATION.md)
- [后续数据迁移方案](DATA_MIGRATION_PLAN.md)

下次可直接交代：先读本手册和 HANDOFF，核对远端 main，导出并审查本次差异；说明拟发布哪一端、等待明确发布指令后再 push，不迁数据、不调用模型。
