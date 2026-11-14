# 本地页面测试启动流程

## 2026-10-08当前：图片执行器恢复与自动重启

本地API能访问不代表图片任务能执行。角色图片创建只写入作业/outbox，还需要Worker执行和Beat周期派发。2026-10-08卡住的根因是Worker/Beat停止、restart=no；本次已恢复同一套 `local-runtime`，API/Worker/Beat改为 `unless-stopped`，并同步到下面的本地Compose。Docker Desktop启动后，这三个未被手动停止的容器会自动恢复；显式stop的服务仍需手动start，迁移服务不会自动运行。

用户批准的本次图片作业已成功，仅一次生图调用，图片内容读取通过。5个历史未完成作业保留，8条历史outbox和本次1条重复事件标记held，不会由Beat自动派发。后续点击生成产生的pending事件正常处理；要继续历史作业，用页面针对该作业的恢复入口，不要清空队列、重建作业或批量释放held记录。详情见[恢复记录](character-image-runtime-recovery-2026-10-08.md)。

日常只读检查（仓库根目录PowerShell）：

```powershell
docker compose -p local-runtime -f var/verification/ui-validation-20260921/local-runtime/compose.json ps -a
Invoke-RestMethod http://127.0.0.1:18002/health
docker exec local-runtime-worker-1 /app/.venv/bin/python -m celery -A comicflow.worker.celery_app:celery_app inspect ping --timeout 5
```

Worker收到pong且Beat为running才具备完整异步执行环境。当前Worker单进程执行长作业时，ping可能暂时超时，应结合持久作业状态判断，不借超时重复提交生图。电脑重启恢复仍复用下方local-runtime入口，不启用另一套历史消费者；启动执行器前检查是否有等待执行的付费任务。

## 2026-09-23运行入口：local-runtime 与仙宫云

实际运行入口已核对并更新：`local-runtime-api-1` / `local-runtime-worker-1` / `local-runtime-beat-1`，API仍为18002，前端5173。使用 `var/verification/ui-validation-20260921/local-runtime/compose.json`、项目名 `local-runtime`，Redis命名空间为 `comicflow-local-validation-20260921`，原数据库、MinIO与模型解密密钥卷保留。不要同时启动下方历史 `comicflow-local-validation` 的API/消费者。

已加载仙宫云协议，视频模型库revision40，分辨率在「模型API→编辑模型→仙宫云分辨率」下拉自选，保存后刷新准备单。远端ready/config只读请求目前503，本机准备单通过不代表仙宫云应用就绪。详见[运行记录](xiangongyun-h3-runtime-2026-09-23.md)。

电脑重启后的恢复，先打开Docker Desktop并只恢复原数据服务。确认没有会自动执行的旧排队生成任务后，在仓库根目录使用当前入口：

```powershell
docker compose up -d --no-deps postgres redis object-store
docker compose -p local-runtime -f var/verification/ui-validation-20260921/local-runtime/compose.json start api worker beat
Invoke-RestMethod http://127.0.0.1:18002/health
```

前端仍按下方5173、代理18002的命令启动。当前容器已经创建且启动，不需要现在再次执行命令。无需迁移schema，也不要运行旧 `scripts/start-local.ps1` 混启另一套Worker。

## 2026-09-19当前：本机已有项目首次试用

已备份本机数据库和模型解密密钥卷，升级至`0003_video_jobs`；153项目、26角色保留。用户明确同意启用验证专用Worker/Beat，目前前端、API和验证执行器均运行。后续真实生成由用户点击。详见[本轮验收报告](video-module-split-verification-2026-09-19.md)。

| 组件 | 本次地址/运行方式 |
| --- | --- |
| 前端 | http://127.0.0.1:5173 |
| API | http://127.0.0.1:18002/health |
| 本机数据服务 | 原comicflow-postgres/redis/object-store容器，未连接服务器库 |
| API/Worker/Beat | `comicflow-local-validation`专用Compose项目，当前源码只读挂载 |
| Redis命名空间 | `comicflow-local-validation-20260919`，不消费旧命名空间 |
| 模型配置 | 复用原数据库模型库revision29及原解密密钥卷，重启不需重填 |

本次本地Compose保存在忽略目录`var/verification/video-module-split-20260919/local-runtime/compose.json`，含本机绝对路径，不是可直接部署到服务器的配置。`.env`中的密钥仍在本地，未写入文档。

若电脑重启后需要恢复本次环境，先打开Docker Desktop。在仓库根目录执行：

```powershell
docker compose up -d --no-deps postgres redis object-store
$localValidation = @('--env-file', 'var/verification/video-module-split-20260919/empty.env', '-p', 'comicflow-local-validation', '-f', 'var/verification/video-module-split-20260919/local-runtime/compose.json')
docker compose @localValidation up -d --no-build api worker beat
docker compose @localValidation ps
Invoke-RestMethod http://127.0.0.1:18002/health
```

当前schema已升级，不重复迁移。原`comicflow-api-1`、`comicflow-worker-1`、`comicflow-beat-1`应保持停止；不要用无服务名的`docker compose up -d`或旧`start-local.ps1`混启旧消费者。以后如果存在未完成任务，恢复执行器前先核对任务状态，不清空或重放旧队列。

前端若未运行，另开PowerShell：

```powershell
cd C:\Users\lmk\Documents\ChatGPT\comicflow\frontend
$env:VITE_API_PROXY_TARGET = 'http://127.0.0.1:18002'
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

若提示端口占用，先复用现有页面，不启动第二份。API改代码后当前源码挂载会生效，但进程仍需显式重启；有正在执行的真实作业时先核对任务号和状态，不直接重启。

本次操作：刷新页面→顶部「打开已有项目」→搜索“便利店”→选择《深夜便利店诡事》（编号`prj_8386abe590d7`，不是《凌晨一点的便利店惊魂》）→「画面」→第1镜“推门进入便利店”→刷新准备单，确认H3/768P/5秒、文本0/视频1、人物主图1张。打开/搜索不调用生成模型，无需在开发者控制台粘贴代码；选定后刷新会保留项目。用户只点击一次「重新生成」，不点击「生成全部」。本轮不重画图片。记录供应商任务号和新视频结果；已知任务中断用「继续查询 / 保存已有任务」，未知提交先核查供应商。

需要停止时，在无运行中真实作业的前提下停止前端终端，再在仓库根目录执行：

```powershell
docker compose --env-file var/verification/video-module-split-20260919/empty.env -p comicflow-local-validation -f var/verification/video-module-split-20260919/local-runtime/compose.json stop beat worker api
```

该命令保留数据库、MinIO、配置密钥及历史素材，不删除卷。

## 历史启动记录（不用于本次视频作业）

以下为2026-09-10/18的旧API端口与运行策略，仅作追踪。本次使用上方18002和验证执行器方案；进程内配置、重启丢配置及仅API启动的描述均已被新版持久模型库/作业流程替代。

2026-09-18补充：本页命令继续使用本地内置数据库/Redis/MinIO。连接已有服务器数据服务请使用[独立配置说明](server-data-connections.md)，不要直接改本页Compose中的服务地址。本页下方关于进程内模型配置的描述为2026-09-10历史状态；新版持久模型库见persistent-model-console.md，本次没有启动或切换服务。

2026-09-10 已验证。先打开 Docker Desktop，等待引擎启动。

在 PowerShell 启动后端及依赖：

```powershell
cd C:\Users\lmk\Documents\ChatGPT\comicflow
docker compose up -d api
docker compose ps
Invoke-RestMethod http://127.0.0.1:18001/health
```

该命令同时启动 PostgreSQL、Redis、MinIO，运行迁移和对象存储初始化。无需每日重新构建镜像。

另开一个 PowerShell 启动前端，保持该终端开启：

```powershell
cd C:\Users\lmk\Documents\ChatGPT\comicflow\frontend
$env:VITE_API_PROXY_TARGET = 'http://127.0.0.1:18001'
npm run dev -- --host 127.0.0.1 --strictPort
```

访问 http://127.0.0.1:5173/ 。API健康检查为 http://127.0.0.1:18001/health 。若5173已占用，先检查是否已有前端运行，不要再启动第二份。首次安装或依赖变化时才需在 frontend 下执行 `npm install`。

此流程用于页面、剧本和直接调用 API 的角色/场景/镜头测试。Worker/beat 不启动，后台排队合成或自动作业不会执行；当前页面模型设置也未共享给已有 Worker，不能当作完整自动生产启动方案。

API重启后页面配置会恢复环境变量。打开“模型 API”，在图片/视频中选择测试套，填写自己的模型、地域地址、API Key与参数，勾选启用并保存，再切换使用测试配置。确认“当前”模型符合预期后再点击生成；保存与切换不调用模型。

2026-09-10 启动后实际默认值为图片 wanx2.1-t2i-plus 未启用、视频 MiniMax-H3 已启用；测试套未配置。没有替用户切换、没有真实生成验证。

前端手动启动的终端按 Ctrl+C 停止；在项目根目录执行 `docker compose stop api postgres redis object-store` 停止本测试流程启动的服务，保留数据卷。后端源码变更需要更新镜像时使用 `docker compose up -d --build api`，注意这会重启API并清空页面内存配置。
