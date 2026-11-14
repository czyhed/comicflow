# 服务器数据库、Redis、MinIO连接配置

2026-09-18 19:20：服务器API与前端已部署，访问http://110.42.51.234:18080。外部项目列表、模型库接口200，浏览器显示空项目/配置版本0。旧本地项目/媒体/密钥尚未迁移；Worker/Beat未启用。数据库已有表，后续旧库恢复必须用独立目标。

2026-09-18最新：用户委托决定首次部署方案后，已在重新确认专用comicflow库public关系数0、comicflow_app为所有者后显式执行Alembic初始化。当前head=0002_model_registry、public表5张，不再是空schema；未恢复本地数据/媒体/主密钥，Worker/Beat未启动。后续旧数据恢复须使用独立目标，下文“保留空库”是此前只读连接阶段的历史。

2026-09-18部署恢复补充：当前Drone调用`backend-external.sh`，使用`backend_external_env`写入临时.env.server，并叠加`compose.external-production.yml`加入comicflow-edge、取消本机18002端口映射。仅API，先检查Alembic head，schema未就绪阻断；不自动迁移或启用Worker/Beat。下文原Drone内置栈说明保留历史用途，不再代表当前.drone.yml选择。本机独立配置入口不变。

2026-09-18：13A配置入口完成；13B三项服务只读认证通过，PostgreSQL为comicflow_app拥有的空库。共享Redis已补齐可配置的逻辑隔离，并通过离线测试；当前前缀扫描无已有键。临时Docker诊断容器可访问三个服务端口，未启动应用。MinIO应用签名GET探测不存在对象返回404/NoSuchKey，无签名错误；实际文件读写未验收。尚未初始化schema、切换运行环境或迁移旧数据。

## 选择启动方式

| 用途 | Compose文件 | 配置来源 | 数据服务 |
| --- | --- | --- | --- |
| 现有本地开发 | 根docker-compose.yml | 原.env中的模型等设置；数据库等使用Compose内部服务名 | 随本地栈运行 |
| 原Drone同机部署 | deploy/compose.backend.yml | backend_env写入runtime.env；Compose内部地址优先 | 随服务器栈部署 |
| 连接已有服务器数据服务（新增） | deploy/compose.external-data.yml | 根目录.env.server | 只连接，不创建PostgreSQL/Redis/MinIO |

新增文件是独立Compose，不与前两者使用多个-f合并。原两套启动文件保持原行为；不能以在原.env或backend_env添加DATABASE_URL作为已经切到外部服务的证据。原deploy/backend.sh仍部署内置基础设施，本次不改变Drone选择。

新方式的API、Worker、Beat、migrate通过同一YAML锚点获得一致配置。只有API默认启用；其他三个服务有独立profile，启动API不会迁移数据库或消费队列。默认API只监听本机127.0.0.1:18002，与现有18001区分。

## 在哪里填写

在仓库根目录，将模板复制为.env.server。已有文件时先编辑已有文件，不覆盖：

```powershell
if (-not (Test-Path -LiteralPath .env.server)) {
    Copy-Item -LiteralPath .env.server.example -Destination .env.server
}
```

本地.env.server已在原先不存在时从模板创建，地址/桶名已准备，真实凭据由用户填写，文件受Git忽略。不要覆盖已有文件，也不要把数据库密码填到前端或模型API控制台。

| 字段 | 填什么 |
| --- | --- |
| DATABASE_URL | PostgreSQL连接串，形如postgresql+asyncpg://用户:URL编码后的密码@地址:端口/专用数据库 |
| REDIS_URL | Redis连接串，形如redis://:URL编码后的密码@地址:端口/数据库编号；TLS按服务要求使用rediss:// |
| COMICFLOW_REDIS_NAMESPACE | 外部栈必填，环境专用且固定，1–64位ASCII字母/数字/下划线/连字符，首位字母或数字；例如comicflow-server-唯一后缀 |
| S3_ENDPOINT | 后端容器可访问的MinIO/S3 API源地址，不是MinIO管理界面 |
| S3_PUBLIC_ENDPOINT | 浏览器可访问同一桶和对象的S3地址或已正确配置的素材代理源地址，不带桶/对象路径 |
| S3_REGION | 与目标S3签名要求一致，默认us-east-1 |
| S3_BUCKET | ComicFlow专用桶名 |
| S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY | 具备该桶所需权限的凭据 |
| EXPORT_DOWNLOAD_SECRET | 本环境API与Worker共用的下载签名密钥；迁入旧数据时核对既有策略 |
| MODEL_CONFIG_ENCRYPTION_KEY | 旧数据库保存过模型配置时，必须是原生效的Fernet主密钥；真正空库可留空，后续在独立共享卷生成 |
| EXTERNAL_API_PORT | 本机API端口，默认18002；如已占用再调整 |

模板中必填地址/凭据留空，离线检查会拒绝不完整配置。模型等额外配置也可放在.env.server中，由env_file传给进程；容器内密钥文件路径固定为/app/var/config/model-config.key，API/Worker/Beat共用model-config卷。

当前shell同名环境变量优先于--env-file；切换前核对是否曾设置$env:DATABASE_URL等变量。在没有此类覆盖的新终端执行下面命令最清楚。密码含$等字符时在.env.server用单引号包住完整值，连接串中的密码还须URL编码。不要粘贴docker compose config的完整输出给别人，它包含展开后的秘密。

## 地址与网络

### 共享Redis的隔离

外部栈必须显式提供COMICFLOW_REDIS_NAMESPACE，API/Worker/Beat/migrate通过同一environment读取。Celery使用独立任务队列/交换器/路由键，并给broker数据键、未确认消息、锁及发布订阅通道加前缀；结果键、事件/控制交换器和生成临时状态也按环境隔离。未设置命名空间的旧本地栈保留原队列和状态键，不迁移或消费旧消息。

命名空间是应用逻辑隔离，不是ACL、容量或故障隔离；共享实例仍会共享内存/淘汰策略。当前REDIS_URL的/0不代表ComicFlow独占0号数据库，也不根据其他库暂时没有键就推断它无人使用。配置前缀后保持固定，改变前缀会使旧队列/临时状态对新环境不可见；不得作为清理失败任务的方式。实际运行前所有生产者和消费者须一起使用相同配置。

当前用户选择文件配置后由本机直连检查。PostgreSQL不支持TLS，MinIO为HTTP，尚无SSH隧道；正式使用推荐完善受保护访问。MinIO内部与公开端点目前相同；以后改成隧道/私网地址时须重新检查签名Host，不能简单改域名就认为媒体读取已通过。

- 最终后端在服务器时，推荐通过服务器私网或已配置的专用容器网络连接。Compose默认网络不能自动访问另一套Compose的服务名，须在13B明确真实可达地址/网络。
- 本机Docker连接服务器时，使用经过确认的私网或SSH隧道。Docker Desktop访问宿主机通常使用host.docker.internal；容器里的127.0.0.1指向容器自己。隧道的监听范围和可达性需验证，不能照抄主机回环地址，也不自动改成公网监听。
- 本机原生Python后端可用.env.server的标准环境字段，但地址必须对宿主进程可达；不要在Docker/宿主两种运行方式间盲目复用地址。原生进程需自行保证使用同一主密钥；Compose的共享卷不自动挂到宿主Python。
- S3_PUBLIC_ENDPOINT不是随便填写的前端地址。原前端Nginx使用固定内部MinIO上游；外部MinIO需要13B单独核对素材代理与签名，不能因为API连通就声称视频可以播放。内部/外部Host不同也要验证实际签名请求。
- 后端默认端口仅本机可访问。本配置不自动接入原生产comicflow-edge/Nginx；服务器正式发布与反向代理整合仍属于后续部署工作，不通过当前任务开放公网数据端口。

## 现在可以做的离线检查

填写.env.server后，在仓库根目录执行：

```powershell
docker compose --env-file .env.server -f deploy/compose.external-data.yml -p comicflow-server config --quiet
```

该命令只解析配置，不启动容器、不验证远端连通、不运行迁移、不会读取数据库或调用模型。不加--quiet会打印包含秘密的配置，不建议用于分享诊断。

真实连接检查13B还需确认：后端运行位置、专用数据目标、访问通道、数据库schema、桶、Redis队列隔离及模型配置主密钥来源。检查使用独立只读进程；普通/health仅证明API进程响应，不能代替数据库/Redis/MinIO连通检查。

## 目标核验后才使用的启动命令

以下命令会启动服务，本轮未执行。必须先通过13B，确认schema已就绪、目标与主密钥正确且不消费不明旧任务：

```powershell
docker compose --env-file .env.server -f deploy/compose.external-data.yml -p comicflow-server build api
docker compose --env-file .env.server -f deploy/compose.external-data.yml -p comicflow-server up -d api
```

前端开发代理届时改为VITE_API_PROXY_TARGET=http://127.0.0.1:18002并重启Vite；本轮未更改。前端永远访问API，不直连数据库。

Worker、Beat、migrate不能随API自动启动；只有确认相应操作范围后才显式指定服务名。数据库迁移命令会修改目标schema，Worker/Beat会消费和调度作业，不作为测试连接步骤。这里不提供一键迁移加启动所有服务的命令。

新的Compose项目使用独立model-config卷，不能凭新卷解密本地旧数据库。连接新空库也不会自动显示本机已有项目；旧数据库、历史视频与图片、加密主密钥的迁移见[迁移方案](../DATA_MIGRATION_PLAN.md)。环境里的mock/disabled不保证覆盖已保存模型库绑定，验证时不要点击生成或模型测试。

## 回到本地

原docker-compose.yml、.env和本地数据卷没有更改。若将来启动过独立API，先停止comicflow-server的应用服务并核查在途作业，再把前端代理切回18001。不要使用down -v，不覆盖旧数据库。若外部环境已产生新数据，切回本地不会自动合并这些数据，须另行备份处理。

## 离线验证记录

2026-09-18补充：命名空间/原Worker/状态存储/Compose聚焦检查44通过；后端全量回归652通过、3跳过（两项缺脱敏项目fixture，一项真实基础设施smoke未启用），对外socket连接已在该回归进程阻断且未加载真实.env.server。Ruff和三个改动源文件的Mypy通过。独立真实配置Compose config --quiet通过，不输出Secret，不启动服务。原有23项Compose测试现增至25项，新增缺失/空命名空间拒绝。

测试在临时目录使用虚构.example.invalid地址和测试凭据解析Compose，不依赖Docker引擎，不启动容器、不发模型请求。覆盖同一目标四进程一致、缺失/空字段拒绝、默认仅API、本地默认值保持、独立端口及模板无真实凭据。完整验证结果记录在HANDOFF及任务13中。
