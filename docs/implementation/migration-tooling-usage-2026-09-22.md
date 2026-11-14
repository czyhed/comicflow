# 7B 迁移工具使用说明

日期：2026-09-22。当前只完成工具及合成数据演练，正式服务器迁移仍暂停。入口为 `scripts/migrate_data.py`，不启动应用、不读取 `.env`、不启动 Worker/Beat，也不调用生成模型。

## 1. 准备显式配置

在仓库根目录使用现有 `uv` 环境。需要 PostgreSQL 16 的 `pg_dump`/`pg_restore`，以及能访问指定数据库、Redis 和 MinIO 的连接。只处理当前 `0004_image_jobs` 的专用数据库和未启用版本控制的专用桶。

将配置保存在 Git 忽略的 `var/migration/source.json`、`target.json`。下例全部是占位值，不能直接连接；JSON 不会展开环境变量。密码中的 URL 保留字符需要百分号编码。文件路径建议用绝对路径和正斜杠。

```json
{
  "label": "comicflow-source",
  "database_url": "postgresql://USER:PASSWORD@127.0.0.1:15432/comicflow_source",
  "s3_endpoint": "http://127.0.0.1:19000",
  "s3_bucket": "comicflow-source",
  "s3_access_key": "REPLACE_LOCALLY",
  "s3_secret_key": "REPLACE_LOCALLY",
  "s3_region": "us-east-1",
  "redis_url": "redis://:PASSWORD@127.0.0.1:16379/0",
  "redis_namespace": "comicflow-source",
  "key_file": "C:/private/comicflow-source.key",
  "pg_sslmode": "prefer",
  "pg_command": [],
  "pg_timeout": 600
}
```

目标配置使用新 label、空数据库、空桶及空 Redis 命名空间，`key_file` 指向单独保存的**原模型解密主密钥**。工具不自动创建库/桶、不生成新主密钥。若原密钥只存在运行环境，正式停写时通过受保护方式导出到文件；本次工具开发没有读取真实密钥。

`pg_sslmode` 同时用于盘点连接和 PostgreSQL 客户端。按实际 TLS 或 SSH 隧道方案配置，不能把公网明文连接当正式迁移方案。数据库 URL 暂不支持查询参数；`pg_host`/`pg_port` 仅在 PostgreSQL 客户端运行于另一网络视角时指定，必须指向**同一实例**。

本机有 PostgreSQL 16 客户端时保留 `pg_command: []`。也可使用已有专用客户端容器：

```json
{
  "pg_command": ["docker", "exec", "-i", "-e", "PGHOST", "-e", "PGPORT", "-e", "PGUSER", "-e", "PGPASSWORD", "-e", "PGDATABASE", "-e", "PGSSLMODE", "-e", "PGCONNECT_TIMEOUT", "YOUR_CLIENT_CONTAINER"],
  "pg_host": "DATABASE_HOST_VISIBLE_INSIDE_CONTAINER",
  "pg_port": 5432
}
```

这是补充字段示例，需合入完整配置。PG 环境变量只按名称转发，不把密码写进命令行。工具通过二进制文件流传递 dump，不经过 PowerShell 文本管道。`pg_command` 会执行本机命令，仅使用自己审核过的配置。

## 2. 四个操作

2026-09-22增补：`inventory --projects`可附加项目分组（文本/镜头/角色、各类保留媒体、作业、共享引用与同名组），不删除数据。该选项只允许inventory；其他操作拒绝。当前真实源含额外历史表，标准工具仍会拒绝，不能靠此选项绕过，见[真实盘点及阻塞](prompt-inventory-verification-2026-09-22.md)。

以下是后续停写演练/正式迁移时的操作模板，当前不要用真实配置执行。每次使用新的报告路径；备份目录必须不存在，主密钥副本必须是备份目录外的新文件。

```powershell
uv run python scripts/migrate_data.py inventory --config var/migration/source.json --report var/migration/inventory-01.json
uv run python scripts/migrate_data.py backup --config var/migration/source.json --bundle var/migration/backup-01 --key-backup var/private-keys/migration-01.key --report var/migration/backup-01.json --writers-stopped
uv run python scripts/migrate_data.py restore --config var/migration/target.json --bundle var/migration/backup-01 --report var/migration/restore-01.json --confirm-target comicflow-target --writers-stopped
uv run python scripts/migrate_data.py verify --config var/migration/target.json --bundle var/migration/backup-01 --report var/migration/verify-01.json
```

`--confirm-target` 必须等于目标 JSON 的 label。`--writers-stopped` 是操作者声明，不会替你停止 API、Worker、Beat 或其他写入者；源和目标都要维持停写，直至恢复校验完成。盘点是只读但会读取整个桶计算摘要，不能用其通过替代停写窗口。

退出码：0 操作通过；2 盘点完成但存在阻塞项；1 配置、连接或保护条件失败。成功报告写入指定路径；异常时只在标准输出给出受限错误代码及异常类型，不输出外部客户端完整异常或密码。失败时可能没有报告文件，不视为成功。

盘点会阻止未完成/未知作业、未释放活动槽、未发布 outbox、旧活动会话、队列/锁/无法分类 Redis 状态、仅 URL/本地路径媒体、缺失引用对象、额外用户表/视图/序列以及不支持的 schema。不能靠清空队列、改任务状态或补调用模型解除阻塞。

## 3. 输出与失败处理

- `database.dump`：同一只读 PostgreSQL 快照的完整逻辑备份；包含加密的模型配置历史。
- `objects/`：整个桶的对象字节，以对象键的 SHA-256 作本地文件名，保留候选和历史文件。
- `manifest.json`：完整成功后才写入；记录表摘要、原对象键、内容哈希、元数据/标签及密钥指纹，不包含主密钥值。
- 独立 key 副本：与备份目录分开放置。POSIX 下新文件权限为 0600；Windows 还须由操作者设置目录/文件 ACL，不能把 mode 当作 Windows 权限隔离。

报告不主动写入连接凭据、正文或签名 URL，但会保留对象键、用户元数据和诊断位置；这些字段也可能包含用户信息。配置、报告、dump、媒体和 key 均按私有资料管理，通过受保护通道传输，不提交 Git。校验和用来发现损坏，不提供备份加密或来源认证；只恢复可信备份。

备份中断：不产生完整 manifest，不能恢复；保留源端，处理原因后用新目录重做。恢复中断：数据库事务失败会回滚，但对象上传阶段失败可能留下已恢复的库/部分对象；工具保留现场并拒绝再次覆盖，检查后改用新的空库/桶。它不自动删库、清桶或清理队列。恢复不执行 Alembic 升级，不启动消费者。

限制：暂不支持版本桶、未完成多段上传、单对象超过单次 PUT 上限（5 GB）、跨版本 schema 转换或第三方共享库。表内容逐表在内存中计算摘要，适用于当前项目规模。Redis 缓存数量变化也可能让备份前后校验停止，属于保守失败，应在稳定窗口重做。源目标地址指纹可发现相同配置，不能识别所有 DNS/隧道别名，仍需人工核对实际实例。对象 ACL、桶策略、生命周期、对象锁和服务端加密配置不由工具迁移，目标需另行配置；当前保留的是内容、Content-Type、用户元数据、标签及常用响应头。

## 4. 不扣费的合成数据演练

```powershell
uv run pytest tests/deployment/test_migration_tools.py -q
uv run python -X utf8 tests/integration/verify_migration_runtime.py
```

Docker Desktop 需运行，已缓存 PostgreSQL 16、Redis 7、Compose 指定 MinIO 版本及 `comicflow-api:latest` 镜像。使用镜像内 Python/FFmpeg，不运行其业务 API。脚本不下载镜像。

演练独占 `comicflow-migration-rehearsal` Compose 项目，请勿并行运行两次。数据库和 MinIO 使用 tmpfs；数据服务在内部网络，固定转发代理向宿主发布随机回环端口。宿主 Python 控制器只配置合成凭据，限制其客户端 DNS 到回环；CLI 子进程只接收合成配置，但不宣称整个宿主被网络沙箱隔离。代理只有三个固定测试目的地，不加载业务环境/卷，不挂 Docker socket。

合成一个项目、角色、两版加密配置、终结作业/outbox及9个媒体；真实 dump/restore 后验证新签名读取、历史资源与配置解密，最后只清理该 Compose 项目。运行证据留在 `var/verification/migration-时间/`。本测试不是浏览器验收，不是 API/Worker 进程重启测试，也不证明真实供应商画质或正式迁移停机时间。结果见[验收报告](migration-tooling-verification-2026-09-22.md)。
