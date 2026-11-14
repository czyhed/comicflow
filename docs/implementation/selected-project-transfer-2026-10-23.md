# 指定项目上传：黄龙山巅韩立大战天哭上人

## 授权与状态

2026-10-23用户指定仅上传项目 `prj_57cd8e0c84af`。本次为既有数据库中的新增合并，不是整库恢复或正式数据环境切换。

已完成：用户启动原本机PostgreSQL/MinIO后，只读导出并合并到既有宝塔服务器；服务器项目数3→4，原有记录逐行摘要核对未变。通过服务器API确认项目列表、剧本、角色整板及3个已采用镜头视频可读，全部16个对象SHA-256一致；视频分段请求返回206。未发布代码、升级schema、调用模型、触发合成或重放作业。

## 数据范围

- 原项目状态、故事、剧本、版本历史、已保存的素材与采用状态。
- 剧本/作业引用及属于该项目的角色卡。
- 该项目已终结的图片、视频作业日志。
- 所有上述记录中对象键指向的媒体；原对象键、字节与元数据保留。
- 模型库、API Key、解密密钥、Redis、outbox均不迁移；不发布代码、不改schema、不调用模型。

旧整库工具要求空库/空桶，不能用于本次。新增工具 `scripts/transfer_project.py` 支持 export / check / import / verify；配置由显式私有dotenv或runtime compose JSON读取，不输出凭据。工作包与报告保存 `var/project-transfers/`，该目录已由Git忽略。

## 执行与失败行为

1. 源库readonly repeatable-read快照读取限定项目，拒绝运行中会话、未结束作业、活动租约、缺关联或凭据字段。暂停/等待重试会话原样保留，不排队；sourceUrl仅在同一素材已有objectKey时视为供应商来源记录，不作为额外待下载文件。逐对象读取，导出后复查源行与媒体摘要。
2. 完整包含rows.json与manifest.json，校验内容SHA-256及引用集合；路径不能越出包。失败包没有complete清单，不能导入。
3. 目标预检schema、项目/角色/作业ID及operation_key；相同数据复用，任何同ID不同内容停止。导入前保存现有public业务表一致性逻辑行快照。该文件包含敏感业务配置，留在私有var目录；它不是pg_dump、角色权限、DDL或整机备份。
4. 仅对缺失对象使用If-None-Match条件新增，不覆盖；逐个复读字节校验。素材复制完成后，serializable事务只INSERT所选业务行。
5. 不导入outbox，未结束作业拒绝进入包，历史作业不会自动排队。异常不自动重试、不删除已上传的无引用对象。
6. 验证数据库行一致、全部对象可读，API读取项目/角色/视频并重新签名；比较原服务器项目及模型配置摘要。

## 本次实际结果

- 项目ID `prj_57cd8e0c84af`，version 11；9镜头、4角色及4张整板，3个已采用视频。
- 新增project_states 1行、characters 4行、image_generation_jobs 4行、video_generation_jobs 3行；两条旧legacy作业随项目payload保留，其中一次合成失败记录保留。
- 16对象、32,903,373字节（约32.9 MB）：4 PNG、7 JPG、4 MP4及1个其他扩展对象。MP4对象数含历史作业输入引用，不代表4个已采用镜头。
- stage `awaiting-confirmation`，generationSession.status `waiting-retry`，历史 `COMPOSITION_MEDIA_UNREADABLE` 原样保存；没有更改为已完成或重试。剩余6个镜头没有生成，完整成片仍缺素材。
- 服务器表计数：project_states 4、characters 10、image_generation_jobs 5、video_generation_jobs 4；model_registry_versions仍17、outbox_events仍2、schema仍0004。原3项目/6角色/旧作业/模型库/outbox逐行摘要均一致。
- 4整板媒体请求成功，3视频均返回HTTP206及4096字节样本；这是接口和媒体分段读取验收，未做浏览器主观画质/音质验收。
- 聚焦测试31 passed、1 skipped（Windows符号链接权限）；Ruff通过。本机TEMP表实际验证serializable事务中途失败回滚、完全相同数据重复导入不新增，原public项目表摘要未变。

## 私有备份和证据

位置：`var/project-transfers/20261023-182212-huanglongshan/`（Git忽略，不提交）。

- rows.json / manifest.json / objects：源端一致性导出及逐文件SHA-256。
- server-before-import.json：222,058字节，导入前服务器public业务表逻辑行快照，含敏感配置记录，仅私有留存；不是完整pg_dump。
- export-report.json / target-check.json / import-report.json / transaction-test.json / server-verification.json：操作及验收证据，不含明文凭据或签名URL。

本机项目数据完整保留。数据库/MinIO整库迁移、原解密密钥迁移和Redis切换继续作为独立待办，不因本次单项目完成而关闭。
