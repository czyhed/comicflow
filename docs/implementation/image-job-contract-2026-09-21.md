# 任务4本批：角色图片作业可靠性

状态：本批已本地完成并通过离线/隔离联调，见[验收报告](image-job-verification-2026-09-21.md)。沿用03B，不新增并行任务体系。

先交付角色主图与现有三视图的持久记录、防重和恢复，下一批再将三次视角生成改为一次整板与独立采用。提示词、Skill规则、风格文案均保持。本批不调用真实模型、不重启业务服务、不迁移业务库、不提交部署。

## 接口和职责

- `POST /api/projects/{id}/characters/{id}/image-jobs` 接收 expectedVersion、operationId、purpose（candidate/views）、force，202返回作业。
- `GET /api/projects/{id}/image-jobs` 和 `GET .../image-jobs/{id}` 返回持久进度；`POST .../{id}/recover` 只恢复安全阶段。
- 独立图片记录表保存冻结输入、角色revision、来源图版本、模型配置revision、各视角结果、供应商任务号及租约。创建与outbox同事务，Worker不自动重试提交。
- 角色职责保留在角色模块；图片执行与存储拆出明确模块，沿用现有Adapter和Celery，不建通用作业框架。旧同步入口也经同一作业门禁，返回兼容结果。

## 状态和失败

queued → preparing → submitting → polling（异步供应商）→ finalizing → succeeded。known task/已保存结果中断为recoverable，提交结果不明为unknown；明确拒绝为failed。unknown保留活动槽，禁止用新operationId绕过。

每个视角保存独立检查点；恢复不得重做已保存视角。来源变化时保留生成记录，不能覆盖当前角色素材。主图仍先候选再人工确认。切换控制台模型不改变在途作业；历史配置不可用则停止。

## 验收

先写失败测试：并发创建/执行、重启、响应丢失、已知任务查询失败、保存失败、来源变更、配置切换、视角部分成功。HTTP假供应商确认提交计数；SQLite持久测试不代替隔离PostgreSQL/Redis/Worker/MinIO联调。前端刷新能查进度、未知状态禁止重复点击，完整后端回归/前端构建及相关页面测试通过后记录准确结果。

运行环境尚未升级时不得声称页面已启用。三视图仍是三次图片调用，本批仅防止恢复时重复生成，下一批再减少为一次。
