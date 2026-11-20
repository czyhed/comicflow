# 分仓部署验证记录（2026-09-17）

## 2026-09-23 经理试用更新：后端成功，前端构建中

后端Drone8于16:12:58（北京时间）成功，main为bb2ac379d792aefccee0681bc34293ff404de967，标签deploy-20260923-manager-pilot-readiness。构建7已更新服务但最后单次Worker ping超时；修复为有界就绪检查，相关38项通过，新Worker实测pong及正常调度。数据库已备份并显式0002→0004，未导入旧数据。

前端ead5d324a094745563ddf3e1b159eaed7e2b0f9f已推送并保留deploy-20260923-manager-pilot，Drone3于16:17:26启动。等待前端完成与外部资源核验；不把已推送等同已部署。

用户批准复用当前模型配置后，服务器revision9已有4连接/4模型/7用途，API Key由服务器主密钥加密保存。保留1条无模型验收草稿及PNG；文本保存/初次上传下载校验通过，创建页参考图旧签名15分钟后过期的缺口已记录。无真实模型调用，无本机数据/历史密钥/旧队列迁移，无删除；完整记录见[本轮验收](implementation/manager-pilot-deployment-2026-09-23.md)。

## 2026-09-18 19:20：前后端首次部署完成，旧数据迁移仍待执行

访问入口：http://110.42.51.234:18080 。前端Drone构建2全绿（8分09秒），后端构建6全绿。前端main/tag deploy-20260918-6为21da436b364b1ff22b195786c121e755ce4b2fb1；后端同名tag/main为5d150d6e1d4429ccf0b64e8067681f5e385eda7d。本轮使用现有版本Restart，未新增代码提交或发布标签。

用户确认Playwright镜像下载完成后重跑：clone经历Empty reply/443超时，最后一次重试成功；镜像缓存命中并开始npm/pnpm，类型检查、生产构建、Node测试、54项Playwright通过。测试日志含未拦截辅助请求到127.0.0.1:8000的ECONNREFUSED，但54项测试全部通过，这不是生产API连接失败。生产镜像构建完成，comicflow-web-web-1 healthy，0.0.0.0:18080->80；部署脚本经Nginx检查后端/health成功。

外部只读验收：首页、/nginx-health、/health、/api/projects、/api/model-registry全部HTTP200。浏览器中文创建页正常，控制台无error/warn；模型管理可打开，显示数据库保存/配置版本0、尚无连接。/api/projects返回空列表。服务器仍为Mock默认，旧项目/媒体/模型密钥未迁移；Worker/Beat未启用，不能把本次上线等同付费视频生产全流程验收。真实模型调用0，未创建项目、未点击测试连接或生成。

下一步：先进行本地旧数据库、MinIO对象、模型配置生效主密钥只读盘点，再制定隔离备份/恢复与切换方案。服务器数据库现已有0002_model_registry和5表，后续恢复用独立目标，禁止直接覆盖或重放旧Redis队列。部署已完成，不再盲目重跑前端构建1；后续新提交走main/push，保留版本标签。用户可先打开入口查看，真实模型配置与后台消费者启用须作为后续步骤明确处理。

## 2026-09-18 本轮重试准备

2026-09-18 19:11更新：用户确认服务器Playwright镜像下载完成，继续部署。Drone仓库详情一度显示resource not found，首页仍列仓库；同步并重新进入后恢复。New Build提交未观察到新记录，随后原构建Restart成功创建前端构建2（21da436，Drone 前端构建 #2）。当前clone首次Empty reply后自动重试，尚未验证镜像缓存使用；没有代码提交、重复推送、模型调用或数据库操作。后端构建6已部署状态保持。

2026-09-18 17:19最新：用户服务器docker images mcr.microsoft.com/playwright为空，curl -I https://mcr.microsoft.com/v2/返回HTTP/2 200；仅证明仓库入口可达，不证明Docker daemon能下载manifest/layers。Drone前端构建1在frontend-checks镜像拉取16分10秒仍仅Pulling无进度，已取消（killed，deploy skipped；总22分49秒）。后端构建6/API保持健康状态，无业务改动。下一步请用户在宝塔终端直接docker pull mcr.microsoft.com/playwright:v1.62.1-noble，提供实际层进度/错误；缓存完成后再恢复前端构建，不跳过门禁。

当前边界：后端构建6全绿且API健康；前端构建1检出已通过，但测试镜像首次拉取超过10分钟无layer进度，未到测试命令/部署，未观察到终止错误。官方manifest存在不代表服务器能下载layers。18080尚不可用。宝塔面板访问被证书校验阻止，已请用户手动登录以只读核查Docker；无证书绕过/重复部署/跳过检查。

前端21da436/tag deploy-20260918-6已上传并触发构建1。clone经历github.com:443连接超时（curl28）及Empty reply from server后，最后一次内置重试成功，检出共6分38秒。HTTP/1.1已配置，不能将网络故障归为之前HTTP/2错误。当前frontend-checks正在首次拉取Playwright镜像，deploy尚未执行。后端构建6已成功运行，不因前端clone失败回滚。

构建6 deploy通过：生产镜像5d150d6构建完成，Alembic0002_model_registry(head)，comicflow-server-api-1 Healthy，脚本GET /api/projects成功，compose ps仅API且无端口映射。使用新Secret成功；前端发布与外部HTTP验收进行中。没有Worker/Beat、旧数据迁移或真实模型调用。

构建6服务器backend-checks完成：Ruff通过，Mypy70源文件通过，pytest656 passed/3 skipped/1 warning（62秒）。跳过2个需本地脱敏fixture测试和1个需显式基础设施smoke。尚待deploy及API健康，不调用真实模型。

构建6（5d150d6，deploy-20260918-6）检出已通过（1分45秒）；uv镜像下载26.3MB用约74秒，Debian镜像索引9.4MB用25秒。两个网络修复已出现服务器正向证据，完整依赖/测试/部署仍在后续步骤验证。前端已准备e6cd208，未发布。

构建5的clone连续在约90秒报HTTP/2 stream 1关闭错误，尚未进入依赖安装；两仓pipeline顶层加入GIT_CONFIG_PARAMETERS强制HTTP/1.1。Drone Docker Runner上游compiler源码确认顶层Environment合并到内置clone，Git本机读取验证HTTP/1.1生效；不关闭TLS校验，不修改认证，不再单纯增加重试次数。实际服务器检出仍由新构建验证。

构建4（6ec43aa、deploy-20260918-4）已证明Python镜像有效：uv26.3MB下载并安装成功，用时约107秒；随后Debian海外包索引下载超过数分钟无推进，已取消尚未deploy的构建（killed，deploy skipped），并改系统包源为HTTPS阿里云镜像。保留原Debian GPG签名验证，不使用trusted=yes。两条Debian/bookworm与security的镜像InRelease本机返回200和签名正文，服务器完整安装仍由下一构建验证。用户已添加backend_external_env且UI名称存在；按用户委托，专用空库已复核后显式初始化到0002_model_registry，public5表，无旧数据迁移，无Worker/Beat。

构建3最终失败：clone成功41秒；backend-checks拉取python镜像成功，pip下载uv==0.11.25从files.pythonhosted.org超时（仅下载2.4/26.3MB，约9.4kB/s），exit2；deploy被跳过。不是业务测试失败，也尚未执行Secret或数据库检查。修复安装来源为阿里云PyPI镜像，原uv.lock版本/哈希通过frozen export和require-hashes保持；本机验证该Linux uv wheel可读取，CI导出67个、生产56个带哈希锁定条目，没有海外URL。服务器镜像安装及后续步骤待下一构建。

后续结果：后端4a6cc87b7ceb1628affc197f69c2a60362bc4d28及deploy-20260918-2已推送并核对。GitHub返回Drone构建3的pending/Build is running，已触发新构建；部署健康仍待验收。干净后端导出656通过/3跳过，干净前端安装/构建/54项E2E通过；前端f91ecb9仅本地提交和标签，待后端健康后推送。本轮无模型调用或真实数据迁移。以下准备阶段“待推送”已被本段更新。

GitHub远端可读取，后端main仍f74b48a、前端main仍1616948；Drone已登录但仅见旧构建1/2。用户恢复发布后，当前代码改用外部数据API部署及backend_external_env，不自动初始化预留空库、不启动Worker/Beat。离线部署测试：原连接配置25项通过，新增发布顺序/Secret清理/失败阻断/网络覆盖5项通过。全后端Ruff通过，业务全量和前端验证见本轮12A记录（656/3 skip、54 E2E、27 Node）；部署改动未触及业务实现。实际推送/构建状态待本次操作后补录。

## 2026-09-18 最新状态

- 用户截图已明确手动创建构建失败原因为 `Bad credentials`；下方关于错误详情不明的记录已被补充。
- 两仓 Drone 步骤优先复用缓存镜像，部署脚本不再强制 `build --pull`。镜像版本、main/push、Secret 和全部检查保持不变；缺镜像和包依赖仍需网络。
- 本轮 YAML 语义比较、Git Bash 语法检查、隔离 Docker 替身验证正常顺序/构建失败停止/临时配置清理、diff 检查全部通过；没有真实 Docker 或模型调用，没有重新执行全套应用测试。
- 后端 main `f74b48a8a3dcda4377ad3f6571e5009f8cd03653` 与标签 `deploy-20260918-1` 已推送并核对远端。前端 `15fc6fd` 本地已提交，待后端验收成功后推送。
- 尚需恢复 Drone 仓库关联 GitHub 授权、检查服务器缓存镜像、观察后端真实构建与健康状态；未宣称部署成功。完整操作要求见 DRONE_DEPLOYMENT.md。
- 本次推送后刷新 Drone 页面仍为 Total Builds 2，最新旧构建2（fab575be），没有观察到新构建；未重复提交 NEW BUILD。

## 最新状态 22:32

22:40补充：已在Drone页面实际提交一次NEW BUILD/main，返回 `Unable to start a new build:`，无详细错误、无新构建。需要服务器对应请求日志才能继续定位；未重复提交。

用户确认按Mario恢复main/push触发，两仓YAML/README/部署文档已同步。YAML解析与语义比较确认仅trigger改变，阻断检查、Secret、挂载和部署步骤未改变；diff检查通过。后端 `2bda9b1` 和版本标签 `deploy-20260917-3` 已推送；前端 `9129d6e` 本地已提交但未推送。Drone仍只有旧构建1/2，GitHub statuses为空，自动触发和上线均未通过验收。下面关于仅标签策略的结果为历史记录。

## 已通过

- 前后端 Compose 使用离线占位配置解析；后端没有发布端口，前端默认 18080。
- 缺少生产密码/公开素材地址时明确拒绝部署；两份 Drone YAML 发布标签触发、并发 1 和部署步骤结构正确。
- 两个部署 shell 脚本语法检查。
- 后端独立导出目录冻结依赖安装成功；Python 3.12 Linux 容器按生产参数安装 56 个冻结运行依赖成功，
  包含 `cryptography`、`httpx`、Celery、PostgreSQL/Redis/S3 依赖。
- 前端原工作区构建，以及独立前端导出目录的 `pnpm install --frozen-lockfile`、构建成功。
- 前端 Linux 镜像构建、Nginx 配置检查成功。
- 后端独立导出目录：636 passed、3 个显式条件跳过；Ruff 通过；Mypy 69 个源码文件通过。
- 前端独立导出目录：Node 响应测试 24 passed；Playwright 46 passed；类型检查和构建通过。
- 发布目录白名单导出与凭据扫描通过；排除本地环境、数据库、媒体和调试载荷。

## 本轮修复

- Mock 动态画面 Provider 不再被误套 H3 尾帧级联要求；H3 缺尾帧仍严格拒绝。
- Mock/测试 Provider 改为当前结构化剧本契约；提示词测试按实际章节标题断言。
- SQLite 持久恢复测试隔离本机 Redis，生产 Redis 行为不变。
- FFmpeg 抽帧移出异步事件循环，并有并发回归测试。
- 百炼 i2v 仅发送官方支持的首帧/首尾帧/续写媒体类型；H3 式多参考图在提交前明确拒绝，
  不发送虚构 `reference` 类型，也不静默丢弃素材。
- 旧浏览器测试改为当前模型管理页面、中文错误提示和真实的未生成/已生成状态转换。
- 所有 Drone 阻断门禁保持启用，没有 `ignore_failure`、跳过测试或生产降级。

## GitHub 发布状态

2026-09-17 20:47：用户要求再次触发，已推送并核对新标签 `deploy-20260917-2`，目标仍为 `ed70fe5`；没有修改应用代码或旧标签。GitHub statuses 仍为空，推送后读取 Drone 页面仍显示 Total Builds 2、最新为旧构建2，本次未观察到新构建。

最新状态（2026-09-17 20:25）：后端 main 与发布标签 `deploy-20260917-1` 已推送至 `ed70fe55a825ff2f2ccc14c3b471597ff165c2cf`，远端解引用已核对。Drone Secret 页面确认 `backend_env` 存在、PR 禁用；未读取其值。Drone 构建页仍仅有旧构建1/2，新提交 statuses 为空，不能称本次已触发构建。Drone健康正常；当前GitHub账号无仓库admin权限，hooks API 404，需要管理员核对 tag push webhook 投递。前端本地 `af8bd5f` 与标签尚未推送；服务器部署未验收。以下为此前历史记录。

- 后端初始干净发布提交为`1510308ed7524173e10a7ec3ca2b1d60e0f623e4`；镜像拉取修复后远端`main`和HEAD均为`fab575bea435b2e073f818911f51f1b9652830ac`。
- 前端干净发布提交`c8bc6bc`已准备，远端`main`仍为`1616948b22d45c0d95335e554a47bd2afa50696a`；等待后端Drone成功后再推送。
- Drone构建1因Runner找不到GHCR uv镜像失败；该标签的Linux amd64 manifest实际存在。CI与生产Dockerfile现改用Docker Hub Python并固定安装`uv==0.11.25`。构建2在执行步骤前因GitHub HTTP/2流中断且默认零次重试而失败；两仓库现配置官方`clone.retries: 3`。后续改为发布标签触发，前端端口改为18080；这些变更尚未推送或在服务器验收。

## 尚未验证

当前后端完整镜像重复构建在 Debian FFmpeg 依赖低速下载时人工停止；此前同 Dockerfile 的 Linux 镜像
已构建成功，本轮又验证了新增冻结依赖及挂载最终源码后的 API 健康、Worker/tasks 导入。服务器上的
实际完整镜像仍以 Drone 构建结果为准。Drone 仓库启用状态、Trusted、Runner 调度、`backend_env`
Secret、域名/安全组仍需核对。私有步骤日志需要通过GitHub OAuth登录Drone查看；后端构建2失败，
前端尚未推送。服务器新服务尚未上线，不能把GitHub上传或pending构建表述为部署成功。

用户确认先部署空数据服务并验证，再迁移本机数据。首次部署只做 `/nginx-health`、`/health`、
空项目列表和容器状态检查；不调用测试连接或生成，不导入本地数据库/MinIO/模型主密钥。
迁移方案见 `DATA_MIGRATION_PLAN.md`。

本轮模型 API 调用数为 **0**；未迁移、删除或上传本地数据库和已有图片/视频。
