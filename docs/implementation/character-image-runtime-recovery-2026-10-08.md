# 本地角色图片执行恢复

日期：2026-10-08。范围：恢复用户本次已点击的角色图片作业，修复本地执行器停止后的启动设置。用户明确回复“恢复这次，并且我想解决这个问题”，授权此次真实图片调用。没有发布服务器、迁移数据或删除记录。

## 根因与操作

API运行，但local-runtime-worker-1、local-runtime-beat-1已停止约两周。指定图片作业停在preparing，attempts/callsStarted均0，taskId为空，租约未占用；创建与恢复共留下2条pending事件。输入与冻结模型配置签名匹配，供应商尚未收到调用。

当前本地Compose三个业务服务restart=no，电脑重启后不会随Docker恢复执行器。处理采用现有Celery/outbox/图片作业入口，不修改供应商协议、提示词或模型配置。

1. 确认专用Redis队列及unacked为空后启动原Worker；Beat暂时保持停止。
2. 用户批准后，在事务内复核6个未完成图片作业都没有实际调用、任务号或租约，并保存10条outbox变更前元数据。
3. 保留5个历史作业的8条事件及本次1条重复事件，将其outbox status设为held。没有修改历史图片作业payload或删除任何事件。
4. 通过现有claim_outbox → publish_to_celery → mark_outbox_published派发本次一个事件，复用原jobId及revision44，不新建作业。
5. 恢复Beat；将当前API/Worker/Beat容器restart policy和本地Compose同步为unless-stopped。使用docker update应用策略，没有重建或中断正在生成的Worker。migrate仍restart=no。

## 作业与验证

| 项目 | 结果 |
| --- | --- |
| 项目ID | prj_9045ea3f39c4 |
| 角色ID | chr_e3f4cdbd202ab9a2dfd7fe64 |
| 图片作业ID | ijob_e490a61cd6ef412589c01a7b507fa353 |
| 用途 | text-board |
| 派发事件 | evt_bde575a8d0eb4557b8f5eaf64fe6cb1b |
| 终态 | succeeded |
| attempts / callsStarted | 1 / 1 |
| 保存结果 | 1张候选图，1536×1024，2,652,109字节 |
| 对象存储检查 | 通过现有AssetStore读取内容，Pillow图片校验通过 |
| 页面API检查 | GET作业返回succeeded、applied=true及1个资产 |
| API | health返回ok |
| Worker | inspect ping返回1节点pong |
| Beat | 周期派发日志正常，Worker执行dispatch_outbox返回0 |
| 历史保护 | 5个旧作业callsStarted全部0，非published事件仅9条held |

applied=true表示候选结果已安装到角色记录，最终采用仍服从角色页现有确认流程。这里只验证生成、保存和查询，不替用户确认图片质量。

当前入口：前端http://127.0.0.1:5173，API http://127.0.0.1:18002。运行Compose：`var/verification/ui-validation-20260921/local-runtime/compose.json`，项目名local-runtime，Redis命名空间comicflow-local-validation-20260921。

变更前outbox元数据已从API容器复制到本机忽略目录`var/verification/character-image-recovery-20261008/outbox-before.json`。只含事件ID、topic、jobId、status和时间，没有凭据或提示词；容器重建后本机记录仍保留。

## 后续恢复约束

held只是此次运维保留标记，pending_outbox只会读取pending；未新增业务作业状态、表或队列体系。历史作业需要用户明确选择恢复，现有recover入口会创建新的pending事件，原held记录继续保留。不要批量释放旧事件，也不要为恢复创建新operationId绕过作业门禁。

unless-stopped只随Docker恢复未手动停止的容器；Docker Desktop仍需启动。本次未通过重启电脑验证，只核实容器实际策略、Compose策略与运行状态一致。今后用户点击生成后留下的待执行任务可能在执行器恢复时继续执行，恢复前应先核对作业状态。Worker为solo/concurrency1，长任务期间control ping可能暂时无应答，不据此重复提交供应商请求。

数据库、MinIO、模型解密密钥迁移和Redis正式切换任务继续保留；本地修复不等于服务器部署完成。
