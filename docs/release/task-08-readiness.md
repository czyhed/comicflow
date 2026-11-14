# Task 08 发布验收清单

## 应用与数据

- [ ] API、Celery Worker、Celery Beat 使用同一版本 Git tag。
- [ ] `DATABASE_URL`、`REDIS_URL`、`S3_ENDPOINT` 和 `EXPORT_DOWNLOAD_SECRET` 通过服务器密钥注入，不写入仓库。
- [ ] 执行 `uv run alembic upgrade head` 并保存迁移日志。
- [ ] PostgreSQL 完成每日备份，并验证一次恢复到隔离数据库。
- [ ] Redis 仅作为队列，不保存项目或额度事实；PostgreSQL 是唯一业务状态来源。
- [ ] MinIO/S3 启用私有桶、服务账号最低权限和生命周期清理策略。

## 网络与权限

- [ ] API 仅通过 HTTPS 反向代理暴露，PostgreSQL、Redis、MinIO 管理端口不对公网开放。
- [ ] Drone 部署账号只允许更新 `/opt/comicflow`、执行迁移和重启 ComicFlow 服务。
- [ ] `deploy_key` 使用专用密钥并限制来源 IP；部署日志不得打印密钥或连接字符串。

## 运行与回滚

- [ ] `comicflow-api`、`comicflow-worker`、`comicflow-beat` 配置 `Restart=always` 和健康检查。
- [ ] 验证 API 重启、Worker 重启后项目、生成作业、额度账本和导出包仍可恢复。
- [ ] 验证失败、取消和重试不会重复结算 Credit 或发布不完整导出包。
- [ ] 保留上一稳定 tag；回滚时先停止 Worker，再恢复应用版本，最后按迁移兼容性执行数据库回滚。

## 观测与试点

- [ ] 记录 API 错误率、生成成功率、重试率、审核阻止率、导出失败率和单位导出成本。
- [ ] 为 PostgreSQL 连接池、Redis 队列积压、对象存储错误和磁盘空间配置告警。
- [ ] 为试点账号配置明确的 Credit 上限，Mock 环境不产生外部 Provider 成本。
- [ ] 完成一条中文故事从创建、剧本、镜头、声音到导出包下载的验收记录。

## 本地 UAT 证据

- Playwright：3 passed，覆盖逐步确认、全自动模式、镜头生成、音画时间轴、局部重生成、合成和导出下载。
- Playwright：4 passed，另覆盖邮箱魔法链接验证、匿名项目认领和 Credits 展示。
- Python：35 passed，1 skipped（Docker 基础设施烟雾测试需显式 `COMICFLOW_INFRA_SMOKE=1`）。
- Docker smoke：`COMICFLOW_INFRA_SMOKE=1` 下 `1 passed`；PostgreSQL、Redis、MinIO、Outbox、Celery Worker、导出包和签名下载通过。
- 重启证据：`docker compose restart api worker beat` 后三项服务恢复，API `/health` 返回 `{"status":"ok"}`。
- 最终本地门禁：Playwright `6 passed`；后端 `36 passed`；mypy、TypeScript、Vite build、`git diff --check` 通过。

## 本地收尾边界

本地自动化已验证身份认领、项目访问控制、Credit 预留/结算/释放/取消幂等、Mock 合成、稳定 `/metrics` 计数器和 Console/SMTP 邮件适配器。真实邮件投递、Prometheus/Grafana 接入、服务器备份恢复、HTTPS、最低权限和线上 UAT 必须在部署环境完成，不能用本地 Mock 结果替代。

真实模型候选和切换门禁记录在 `docs/adr/0006-model-provider-selection.md`；任务 08 不切换 `PROVIDER_MODE=mock`，模型评测属于任务 09。
