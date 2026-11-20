# 2026-09-23 宝塔服务器经理试用发布

## 范围与授权

用户明确要求推送到原宝塔服务器让经理试用，随后确认不需要本机已有项目和素材。复用原两套 GitHub 仓库、Drone、外部 PostgreSQL/Redis/MinIO 和前端 18080，不重新搭建数据服务。本批发布新版并启用同配置 API/Worker/Beat，不迁移本机数据、原解密密钥或旧队列，不删除业务数据，不调用真实模型。

本次授权覆盖试用发布，不代表原工单10的完整数据迁移已完成。数据库、MinIO、原解密密钥成套迁移及 Redis 干净命名空间/单一写入端正式切换继续保留。用户后续明确同意复用本机正在使用的模型连接、配置和API Key到原宝塔服务器；这只复制当前用途配置，不导入原历史库或原解密主密钥。

## 已执行的准备

- 实时盘点服务器 PostgreSQL 18.4：schema 为0002，5张表，业务记录全部0；模型库revision0；Redis专用命名空间无键、outbox无待执行记录。
- 使用官方postgres:18-alpine的pg_dump备份，7645字节，pg_restore目录读取及前后盘点通过。备份在私有`var/verification/server-pilot-20260923/server-before-0004.dump`，SHA256在同目录before.json；不上传数据库备份。
- 显式执行Alembic升级到0004_image_jobs，新增视频/图片作业表。升级后7表、业务仍0行。发布脚本仍只读检查schema，不隐式执行升级。
- `DEPLOY_WORKERS=true`由本次Drone显式启用，其他直接运行发布脚本默认保持API-only。API/Worker/Beat复用同一外部配置及模型密钥卷。
- 白名单导出保留JSON测试fixture，凭据扫描通过；使用独立Git克隆提交，未整体提交主工作区，也未reset/clean。

## 离线门禁

导出后端929通过/3跳过，Ruff与Mypy通过；前端build通过、Node40通过、Playwright81通过；部署脚本/外部连接34通过。测试使用模拟供应商，没有真实模型请求。

## 发布状态

后端提交`787f841a113b0cbe666f879234970bbc7f47eaa6`已 fast-forward 发布到内部 comicflow 仓库的 main，标签`deploy-20260923-manager-pilot`。Git直连失败后复用GitHub API发布工具，逐项校验blob/tree/commit SHA，未force push。Drone构建7在最后Worker单次ping检查超时，整轮结果failure；镜像构建、schema0004检查、API/Worker/Beat启动已执行，不能将构建失败等同旧版本未替换。

用户提供构建7完整部署日志后，使用相同服务器Redis/命名空间只发Celery inspect查询，真实Worker返回pong、运行159秒、prefork并发48。新版API/模型库均HTTP200且已包含xiangongyun-h3，MinIO桶读取正常。该证据排除持续不可用，支持首次就绪检查过早；未获取首次启动完整Worker日志，不把具体初始化耗时断言为已证实根因。Compose对没有healthcheck的Worker/Beat只确认进程已启动，原脚本只做一次ping，没有就绪等待。

新增发布脚本回归先复现延迟应答失败，再补最多6次、每次10秒ping和失败间隔5秒的就绪检查。只重试ping、不发生成任务；持续不可用仍失败，不继续API验收。相关38项通过。修复提交`bb2ac379d792aefccee0681bc34293ff404de967`已发布，标签`deploy-20260923-manager-pilot-readiness`，等待新Drone验收。业务代码未再改动。

2026-09-23 16:12:58（北京时间），后端Drone构建8成功，GitHub状态success；新Worker再次返回pong，调度检查正常。后端发布已完成。

随后已 fast-forward 推送前端`ead5d324a094745563ddf3e1b159eaed7e2b0f9f`到内部 comicflow-web 仓库的 main，保留标签`deploy-20260923-manager-pilot`。构建3运行过久后按用户要求取消；空提交`5de07de`触发的构建4也按要求取消。构建5（空提交`1b643c6`）的类型检查、生产构建及40项Node测试通过，但81项Playwright中80通过、1失败：视频播放/下载测试执行`ffmpeg`时报告ENOENT。原因是该E2E在运行时调用ffmpeg，而Drone的Playwright镜像不包含它；推送代码不会保证流水线通过，测试失败会阻止后续部署步骤。CI检查步骤增加ffmpeg后，提交`4db450a4b40c21e043b74f371f2de1edbbccde18`的Drone构建6于2026-09-23成功，检查与部署步骤均为success。只读验收确认线上JS/CSS与本地构建逐字节匹配，仙宫云控件存在；`/nginx-health`、`/health`、`/api/projects`及`/api/model-registry`均为200，模型库revision10，含4模型/7用途/5个已配置连接。验收未调用模型，详情见`var/verification/server-pilot-20260923/frontend.json`。

## 试用配置与后续

修复构建期间通过真实服务器API创建一个明确标注的“部署验收草稿（无模型调用）”`prj_66083bdd51a9`，手动保存故事并上传程序绘制的320×180 PNG（2421字节），版本1→3。重新GET读取文本成功，MinIO签名下载的SHA256与上传字节一致；记录及图片保留，未删除。私有证据在`var/verification/server-pilot-20260923/smoke-project.json`。这新增的一条验收记录不属于本机旧数据迁移；发布前盘点0行是当时真实状态。

后端更新后，故事及模型配置读取仍通过；约15分钟后复查创建页referenceImage.downloadUrl时返回403 / AccessDenied / Request has expired。已核实当前快照刷新仅覆盖visualAssets/audioAssets/lipSyncAssets，未刷新project.referenceImage的旧签名。这是已知参考图片链接有效期缺口，上传当时的字节验收仍成立，但不能宣称该参考图跨有效期访问通过。对象未删除，未为此重新上传或调用模型；前端发布继续，不再扩展后端业务修改。

访问入口：http://110.42.51.234:18080 。用户明确批准复制当前模型配置后，通过现有API离线CRUD完成4连接、4模型、7用途绑定，服务器revision0→9。源实时revision44，按当前绑定选择，协议chat-image/wan26-image/doubao-chat/xiangongyun-h3；故事、剧本、视频提示词、角色提示词、图片、图生图与视频用途均保留，参数与源逐项比对一致。源凭据只在受控进程内存中解密/传递，不打印、不落明文文件，由服务器自己的持久主密钥加密保存；没有复制原历史配置或原主密钥。私有映射与无密钥证据在`var/verification/server-pilot-20260923/model-config-copy.json`。

上线与真实生成验收分别记录；模型配置已可复用，但未调用真实文本/图片/视频验证，仙宫云实例仍需在线。模型库刚建立时revision0的记录保留为历史盘点，不再当作交付状态。

本机项目/素材/配置与旧成功视频完整保留。原数据迁移的历史表、Mock引用、旧未终结作业与Redis状态问题继续按原方案处理；不以本次无数据试用发布关闭工单10。
