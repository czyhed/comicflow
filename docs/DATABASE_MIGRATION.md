# 数据库迁移指南

## 当前服务状态

✅ **项目已启动**
- API: http://127.0.0.1:18001/health
- 前端: http://127.0.0.1:5173
- MinIO 对象存储: http://127.0.0.1:19000
- MinIO 控制台: http://127.0.0.1:19001
- PostgreSQL: localhost:15432
- Redis: localhost:16379

## 数据库迁移方案

### 方案 1: PostgreSQL 导出导入（推荐）

适用于迁移完整的数据库到新服务器。

#### 1.1 导出当前数据库

```bash
# 导出整个数据库（包含结构和数据）
docker exec comicflow-postgres-1 pg_dump -U comicflow -d comicflow > comicflow_backup_$(date +%Y%m%d_%H%M%S).sql

# 或者只导出数据（假设新服务器已有结构）
docker exec comicflow-postgres-1 pg_dump -U comicflow -d comicflow --data-only > comicflow_data_only.sql
```

#### 1.2 复制备份文件到新服务器

```bash
# 使用 scp
scp comicflow_backup_*.sql user@new-server:/path/to/backup/

# 或使用 rsync
rsync -avz comicflow_backup_*.sql user@new-server:/path/to/backup/
```

#### 1.3 在新服务器上导入

```bash
# 如果新服务器使用 Docker
docker exec -i new-postgres-container psql -U comicflow -d comicflow < comicflow_backup_*.sql

# 如果新服务器是独立 PostgreSQL
psql -U comicflow -d comicflow -h new-server -f comicflow_backup_*.sql
```

### 方案 2: 使用 pg_dump 的自定义格式（更灵活）

```bash
# 导出为自定义格式（支持压缩和选择性恢复）
docker exec comicflow-postgres-1 pg_dump -U comicflow -d comicflow -F c -f /tmp/backup.dump
docker cp comicflow-postgres-1:/tmp/backup.dump ./comicflow_backup.dump

# 在新服务器恢复
docker cp comicflow_backup.dump new-postgres-container:/tmp/backup.dump
docker exec new-postgres-container pg_restore -U comicflow -d comicflow -c /tmp/backup.dump
```

### 方案 3: 在线复制（适合持续同步）

使用 PostgreSQL 的逻辑复制功能：

```sql
-- 在源数据库创建发布
CREATE PUBLICATION comicflow_pub FOR ALL TABLES;

-- 在目标数据库创建订阅
CREATE SUBSCRIPTION comicflow_sub 
CONNECTION 'host=source-server port=5432 dbname=comicflow user=comicflow password=xxx' 
PUBLICATION comicflow_pub;
```

### 方案 4: Docker Volume 迁移（适合同构环境）

如果新服务器也使用 Docker：

```bash
# 1. 停止当前容器
docker compose down

# 2. 备份 volume
docker run --rm -v comicflow-postgres:/source -v $(pwd):/backup alpine \
  tar czf /backup/postgres_volume_backup.tar.gz -C /source .

# 3. 传输到新服务器
scp postgres_volume_backup.tar.gz user@new-server:/path/

# 4. 在新服务器恢复
docker volume create comicflow-postgres
docker run --rm -v comicflow-postgres:/target -v /path:/backup alpine \
  tar xzf /backup/postgres_volume_backup.tar.gz -C /target
```

## 对象存储（MinIO/S3）迁移

### 导出 MinIO 数据

```bash
# 1. 使用 mc (MinIO Client) 镜像同步
docker run --rm -it --network comicflow_default \
  -v $(pwd)/minio-backup:/backup \
  minio/mc:latest \
  sh -c "mc alias set local http://object-store:9000 comicflow comicflow_dev_only && \
         mc mirror local/comicflow /backup/comicflow"

# 2. 同步到新服务器的 MinIO
docker run --rm -it \
  -v $(pwd)/minio-backup:/backup \
  minio/mc:latest \
  sh -c "mc alias set new http://new-server:9000 access_key secret_key && \
         mc mirror /backup/comicflow new/comicflow"
```

### 或直接复制 Volume

```bash
# 备份对象存储 volume
docker run --rm -v comicflow-objects:/source -v $(pwd):/backup alpine \
  tar czf /backup/minio_volume_backup.tar.gz -C /source .

# 在新服务器恢复
scp minio_volume_backup.tar.gz user@new-server:/path/
docker volume create comicflow-objects
docker run --rm -v comicflow-objects:/target -v /path:/backup alpine \
  tar xzf /backup/minio_volume_backup.tar.gz -C /target
```

## 完整迁移步骤

### 推荐流程

```bash
# === 在源服务器 ===

# 1. 停止应用（可选，取决于是否允许停机）
docker compose stop api worker beat

# 2. 备份数据库
docker exec comicflow-postgres-1 pg_dump -U comicflow -d comicflow -F c > comicflow_db_$(date +%Y%m%d).dump

# 3. 备份对象存储
docker run --rm -it --network comicflow_default \
  -v $(pwd)/backup:/backup \
  minio/mc:latest \
  sh -c "mc alias set local http://object-store:9000 comicflow comicflow_dev_only && \
         mc mirror local/comicflow /backup/comicflow"

# 4. 传输到新服务器
rsync -avz --progress comicflow_db_*.dump backup/comicflow/ user@new-server:/data/comicflow-migration/

# === 在目标服务器 ===

# 5. 部署 ComicFlow
git clone <repo> && cd comicflow
cp .env.example .env
# 编辑 .env 配置生产环境变量

# 6. 启动基础服务
docker compose up -d postgres redis object-store

# 7. 恢复数据库
docker cp /data/comicflow-migration/comicflow_db_*.dump comicflow-postgres-1:/tmp/restore.dump
docker exec comicflow-postgres-1 pg_restore -U comicflow -d comicflow -c /tmp/restore.dump

# 8. 恢复对象存储
docker run --rm -it --network comicflow_default \
  -v /data/comicflow-migration/comicflow:/backup \
  minio/mc:latest \
  sh -c "mc alias set local http://object-store:9000 comicflow comicflow_dev_only && \
         mc mirror /backup local/comicflow"

# 9. 运行数据库迁移（确保表结构最新）
docker compose run --rm migrate

# 10. 启动应用服务
docker compose up -d api worker beat

# 11. 验证
curl http://localhost:18001/health
```

## 验证迁移

```bash
# 检查数据库连接
docker exec comicflow-postgres-1 psql -U comicflow -d comicflow -c "\dt"

# 检查记录数
docker exec comicflow-postgres-1 psql -U comicflow -d comicflow -c "
SELECT 
  'projects' as table_name, COUNT(*) FROM projects
UNION ALL
SELECT 'shots', COUNT(*) FROM shots
UNION ALL
SELECT 'characters', COUNT(*) FROM characters;
"

# 检查对象存储
docker run --rm -it --network comicflow_default \
  minio/mc:latest \
  sh -c "mc alias set local http://object-store:9000 comicflow comicflow_dev_only && \
         mc ls local/comicflow --recursive"
```

## 回滚计划

如果迁移出现问题：

```bash
# 1. 保留源服务器数据（迁移前不要删除）
# 2. 如果新服务器有问题，切换 DNS/负载均衡回源服务器
# 3. 如果需要重新迁移，清空新服务器数据后重试

# 清空数据库
docker exec comicflow-postgres-1 psql -U comicflow -d comicflow -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

# 清空对象存储
docker run --rm -it --network comicflow_default \
  minio/mc:latest \
  sh -c "mc alias set local http://object-store:9000 comicflow comicflow_dev_only && \
         mc rm --recursive --force local/comicflow"
```

## 注意事项

1. **停机时间**：如果可以停机，建议停止应用再备份（保证数据一致性）
2. **增量迁移**：对于大数据库，可以先做一次全量备份，然后在正式迁移时只增量同步最新数据
3. **环境变量**：记得在新服务器的 `.env` 中配置正确的 API keys 和生产环境配置
4. **网络配置**：确保新服务器的防火墙允许必要的端口
5. **SSL/TLS**：生产环境建议配置 HTTPS 和数据库 SSL 连接
6. **备份保留**：迁移成功后保留源数据至少 7-30 天，确保稳定运行

## 快速迁移脚本

创建 `scripts/migrate-to-server.sh`：

```bash
#!/bin/bash
set -e

SOURCE_HOST="localhost"
SOURCE_PORT="15432"
TARGET_HOST="$1"
TARGET_USER="$2"

if [ -z "$TARGET_HOST" ] || [ -z "$TARGET_USER" ]; then
  echo "Usage: $0 <target-host> <target-user>"
  exit 1
fi

BACKUP_DIR="migration_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "=== 1/5 Backing up database..."
docker exec comicflow-postgres-1 pg_dump -U comicflow -d comicflow -F c > "$BACKUP_DIR/db.dump"

echo "=== 2/5 Backing up objects..."
docker run --rm --network comicflow_default \
  -v "$(pwd)/$BACKUP_DIR:/backup" \
  minio/mc:latest \
  sh -c "mc alias set local http://object-store:9000 comicflow comicflow_dev_only && \
         mc mirror local/comicflow /backup/objects"

echo "=== 3/5 Transferring to target server..."
rsync -avz --progress "$BACKUP_DIR/" "$TARGET_USER@$TARGET_HOST:/tmp/comicflow-migration/"

echo "=== 4/5 Running restore on target server..."
ssh "$TARGET_USER@$TARGET_HOST" << 'EOF'
cd /opt/comicflow
docker cp /tmp/comicflow-migration/db.dump comicflow-postgres-1:/tmp/restore.dump
docker exec comicflow-postgres-1 pg_restore -U comicflow -d comicflow -c /tmp/restore.dump
docker run --rm --network comicflow_default \
  -v /tmp/comicflow-migration/objects:/backup \
  minio/mc:latest \
  sh -c "mc alias set local http://object-store:9000 comicflow comicflow_dev_only && \
         mc mirror /backup local/comicflow"
docker compose restart api worker beat
EOF

echo "=== 5/5 Migration complete!"
echo "Backup saved in: $BACKUP_DIR"
echo "Verify at: http://$TARGET_HOST:18001/health"
```

使用方法：
```bash
chmod +x scripts/migrate-to-server.sh
./scripts/migrate-to-server.sh new-server.example.com ubuntu
```
