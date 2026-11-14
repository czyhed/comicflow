# 不调用真实模型的视频运行联调

## 拆分后完整贯穿（2026-09-22）

先确认frontend/dist已从当前源码构建。下面仅启动独立临时数据栈及假供应商，入口127.0.0.1:4184；不要混用业务Compose或env。输出目录参数同时用于Compose挂载和Playwright，保留历史报告时选择新目录。

```powershell
$verificationDir = 'var/verification/post-split-flow-20260922'
New-Item -ItemType Directory -Force $verificationDir | Out-Null
Set-Content "$verificationDir/empty.env" '# no business environment' -Encoding ascii
$env:COMICFLOW_VERIFY_OUTPUT = (Resolve-Path $verificationDir).Path.Replace('\', '/')
$verificationCompose = @('--env-file', "$verificationDir/empty.env", '-p', 'comicflow-verify-post-split-20260922', '-f', 'tests/integration/production-runtime.compose.yml')
try {
    docker compose @verificationCompose up -d
    if ($LASTEXITCODE -ne 0) { throw 'Test stack did not start' }
    pnpm --dir frontend exec playwright test -c playwright.integration.config.ts
    if ($LASTEXITCODE -ne 0) { throw 'Browser verification failed; preserve logs' }
    docker compose @verificationCompose exec -T verify /app/.venv/bin/python /workspace/tests/integration/verify_production_media.py
    if ($LASTEXITCODE -ne 0) { throw 'Export media verification failed' }
} finally {
    docker compose @verificationCompose down --volumes
    Remove-Item Env:COMICFLOW_VERIFY_OUTPUT -ErrorAction SilentlyContinue
}
```

仅删除这个明确命名的测试项目及其临时卷，不执行全局prune。`image-runtime.compose.yml`和`video-runtime.compose.yml`也接受相同输出变量，须使用各自独立目录/项目运行；它们验证Worker中断恢复，不能并入业务栈。验收结果和真实质量边界见[本批报告](../../docs/implementation/post-split-flow-verification-2026-09-22.md)。

## 迁移工具隔离演练（2026-09-22）

```powershell
uv run python -X utf8 tests/integration/verify_migration_runtime.py
```

脚本自建并清理专用 `comicflow-migration-rehearsal` 项目，勿并发运行。只使用合成数据、已有缓存镜像、独立临时PostgreSQL/Redis/MinIO，固定目标代理发布随机回环端口供宿主控制器访问。没有业务.env/卷、API/Worker/Beat或真实模型调用；不把整个宿主描述成无外网沙箱。PostgreSQL16客户端在测试容器执行，输出二进制dump；最终验证表/序列、完整桶、历史配置解密和新签名读取，失败保护覆盖非空目标、未知作业、损坏备份和上传中断。

证据写入 `var/verification/migration-时间/`。当前7表、9对象、2版配置通过；仓储重建不等于完整API重启。详情见[使用说明](../../docs/implementation/migration-tooling-usage-2026-09-22.md)和[验收记录](../../docs/implementation/migration-tooling-verification-2026-09-22.md)。清理只限本项目，不prune，不触碰业务数据。

## 视频作业运行联调

`video-runtime.compose.yml`只用于一次性隔离验证，不与业务Compose合并。需要Docker Desktop和已缓存的`comicflow-api:latest`、PostgreSQL16、Redis7、指定MinIO镜像；`pull_policy: never`缺镜像即失败。应用镜像须具备当前Python依赖和FFmpeg，测试始终挂载工作区当前源码。

在仓库根目录PowerShell执行：

```powershell
$verificationDir = 'var/verification/video-module-split-20260919'
New-Item -ItemType Directory -Force $verificationDir | Out-Null
Set-Content -Path "$verificationDir/empty.env" -Value '# no business environment' -Encoding ascii
$verificationCompose = @('--env-file', "$verificationDir/empty.env", '-p', 'comicflow-video-verify-20260919', '-f', 'tests/integration/video-runtime.compose.yml')
docker compose @verificationCompose up -d --wait --wait-timeout 60 postgres redis minio
if ($LASTEXITCODE -ne 0) { throw 'Test infrastructure not ready' }
try {
    docker compose @verificationCompose run --rm --no-deps verify
    if ($LASTEXITCODE -ne 0) { throw 'Video runtime verification failed; inspect logs' }
} finally {
    docker compose @verificationCompose down
}
```

不要添加业务env文件、业务网络或数据卷。测试网络无Internet出口且不发布端口；数据库和MinIO数据使用tmpfs。模型地址为验证容器内的假H3，密钥为测试值，业务模型库不会读取。

成功输出`runtime-report.json`：真实调用0、假提交1，Worker终止/API重启后沿用任务号恢复；下载失败可恢复；真实Redis/outbox、PostgreSQL保存、MinIO文件、FFmpeg首尾帧和签名下载均受检查。租约到期只在临时测试库中推进；Beat未启动，派发由真实Dispatcher显式触发。5秒测试媒体由FFmpeg生成，不能用于验收真实画质或供应商分辨率。

本轮结果和局限见[15A/09A验收报告](../../docs/implementation/video-module-split-verification-2026-09-19.md)。清理仅限上述Compose项目，不使用全局prune、不删除业务数据。

## 角色图片作业隔离验证（2026-09-21）

图片验证使用 `image-runtime.compose.yml` 和 `verify_image_runtime.py`；沿用相同隔离边界，输出独立目录 `var/verification/image-jobs-20260921/`。临时schema升到0004，假图片接口只绑定容器回环；实际PostgreSQL/Redis/Celery/MinIO验证断进程、配置切换、查询/下载恢复与候选保存，供应商生成提交仅1次。

```powershell
New-Item -ItemType Directory -Force var/verification/image-jobs-20260921 | Out-Null
Set-Content var/verification/image-jobs-20260921/empty.env '# no business environment' -Encoding ascii
$imageVerify = @('--env-file', 'var/verification/image-jobs-20260921/empty.env', '-p', 'comicflow-image-verify-20260921', '-f', 'tests/integration/image-runtime.compose.yml')
docker compose @imageVerify up -d --wait --wait-timeout 60 postgres redis minio
if ($LASTEXITCODE -ne 0) { throw 'Image test infrastructure not ready' }
try {
    docker compose @imageVerify run --rm --no-deps verify
    if ($LASTEXITCODE -ne 0) { throw 'Image verification failed' }
} finally {
    docker compose @imageVerify down
}
```

使用独立Compose项目和tmpfs，不与业务服务合并。不提供 `.env`/`.env.server`，不启用业务消费者。图片存储验证不代表真实人物画质通过。

2026-09-21原视频脚本已适配0004和候选显式采用，在新临时项目复核通过。通过env文件设置 `COMICFLOW_VERIFY_OUTPUT=../../var/verification/image-jobs-video-20260921` 可将报告写入独立目录，避免覆盖历史证据；默认输出路径保持兼容。
