# 03A 视频持久作业与 04A 恢复界面验收

日期：2026-09-19。本轮本地实施，不提交、推送、部署，不修改真实数据库或启动 Worker/Beat；真实文本、图片、视频调用均为 0。

## 交付范围

画面页提交改为保存作业并快速返回 202。页面从服务器读取阶段、供应商任务号、错误和已开始的文本/视频调用次数；刷新不会重新生成。任务记录读取失败时禁用生成。恢复已有任务由用户显式点击；批量按本次冻结清单逐镜头处理，失败、候选结果、停止或离开页面即停止后续提交，已发出的供应商任务不等于取消或退款。

H3 和百炼 Wan 共享持久检查点。输入、准备指纹、规则摘要、模型配置版本、扩写结果、任务号和下载后的资产均可追踪。默认 H3 768P 和两条提示词路径保持原契约。已有任务查询/下载不调用第二次视频生成；已保存的扩写结果可以复用。

本批是 03 的视频阶段与 04 的最小恢复阶段。图片/三视图长任务、完整候选采用、版本对比、实测媒体参数和全站 UI 改版尚未完成。当前输入仍匹配则沿用自动采用行为；输入变化或镜头被删除则保留候选，旧有效视频不变。候选可从资源页查看，旧自动生产入口遇候选会停止，不当作已采用继续生成。

## 接口与状态

| 接口 | 行为 |
| --- | --- |
| `POST /api/projects/{pid}/shots/{sid}/video-jobs` | `expectedVersion`、`operationId`、可选 `preflightFingerprint`；服务器强制即时预检，保存作业与 outbox 后返回 202，不等待模型 |
| `GET /api/projects/{pid}/video-jobs` | 读取当前项目作业，按创建时间倒序；无模型调用 |
| `GET /api/projects/{pid}/video-jobs/{id}` | 读取单条安全详情，隐藏内部输入、密钥和下载链接 |
| `POST /api/projects/{pid}/video-jobs/{id}/recover` | 无 taskId 时恢复已有作业；未知视频提交可显式填写已核查的 taskId，关联后仅查询/下载 |

状态：queued → preparing → expanding（仅 local-skill）→ prepared → submitting → polling → downloading → finalizing → succeeded；Mock 使用 rendering。中断另分 recoverable、unknown、failed/cancelled。没有百分比估算。`callsStarted` 记录跨过调用检查点的次数，不是账单或扣费确认。

沿用 `ownerUserId` / `X-User-Id` 的现有项目权限。读记录与恢复排队不依赖当前用途绑定能否构造 Provider；执行时按原模型库 revision 恢复。环境配置只保存身份摘要，变化后明确停止，不将旧任务送至新模型。模型库主密钥和旧配置版本必须随数据库保留。

## 防重与保存边界

- 新表 `video_generation_jobs`：逻辑操作唯一键、每镜头唯一 active slot、revision CAS 和带 token 的有限租约。PostgreSQL 为事实来源，Redis 只派发。
- 新建作业与 `production.video.queued` outbox 同事务保存；重复请求和多执行器不能同时持有同一作业的有效租约。新视频 Celery task 不配置生成自动重试。
- 供应商 taskId 必须先提交到数据库，再开始轮询。进程停在 submitting/expanding 且无确定结果时，租约到期后显示 unknown，不能用普通重试绕过。
- 模型调用失败、HTTP 超时、数据库保存失败不自动发第二次生成。恢复可能再次查询和下载同一结果；供应商的查询/存储费用仍以其规则为准。
- 有对象键的输入不持久化短期签名 URL，执行前重签；拒绝内联图片 Base64 入作业。作业不复制模型 API Key。
- 作业结束和项目资产安装同事务保存；资产与当前输入比较，不匹配保留候选。项目后续保存若携带的旧快照缺少已经落库的作业资产，返回 VERSION_CONFLICT，避免抹掉已付费结果。
- 旧同步 `/visual` 仍兼容错误体与结果格式，但真实 H3/Wan 必须经过相同作业门禁。其逻辑操作键取项目/镜头/版本/模型版本，同版本重复调用返回原操作；显式新一轮生成用新的 video-jobs 接口与 operationId。旧同步入口仍可能是长 HTTP 请求。

## 实现入口

后端：`infrastructure/video_jobs.py`、`production/video_jobs.py`、`providers/video_checkpoints.py`、H3/Wan Adapter、Pipeline、API schema/routes、Worker/outbox 派发及 `database.py`。

前端：`features/visuals/VideoJobPanel.tsx`、`VisualWorkspace.tsx`、`video-jobs.ts`、`api/client.ts`、`use-batch-generation.ts`、types/styles。

迁移：`backend/migrations/versions/0003_video_jobs.py`，基于 `0002_model_registry`。本轮只在临时 SQLite 中运行升级并核对唯一约束，真实数据库未执行。

## 验证

先前已确认缺少作业方法的 RED；本轮另外用失败测试复现旧项目快照覆盖新视频，再实现冲突保护。所有供应商行为使用 MockTransport；全量后端通过隔离启动器移除业务环境并阻止真实 socket 连接（仅允许 Windows asyncio 本地 socketpair）。浏览器业务 API 拦截，Vite 代理指向不可用的本机端口 9。

新增后端用例覆盖：快速排队零模型请求、并发创建/抢租约、stale token、同操作重放、outbox 原子回滚、任务号保存前后崩溃、提交响应丢失、手动关联已有任务、文本扩写复用/未知文本不重试、下载与最终保存恢复、H3/Wan 查询恢复、供应商明确失败、原模型库 revision、排队后规则变化、输入修改/删除保留候选、旧入口防重/候选阻断、权限和数据库安全报错、迁移约束、迟到的项目保存冲突。

浏览器新增 4 项：刷新找回供应商任务且无自动恢复、未知提交锁定并显式关联任务号、一次点击一次提交且列表错误禁止绕过、离开批量页面停止后续调用。原准备单与生产流程用例同步适配 202 接口；检查桌面与 390px 窄屏。

最终命令与结果以 `var/verification/durable-video-20260919/` 的 backend-final.txt、frontend-build.txt、frontend-node.txt、frontend-e2e.txt、ruff.txt、mypy.txt 为准；最终结果：后端725通过/3跳过，Ruff/Mypy75源文件通过；前端build、Node27、Playwright66通过。最终按钮样式另通过4项聚焦浏览器检查。3项跳过为两份未指定的本地项目样本和一项真实基础设施smoke；Alembic/Starlette弃用警告不影响结果。新增后端26项、浏览器4项。

## 正式启用前与限制

1. 本次没有重启本机业务服务或更改服务器。后续在明确目标环境后备份数据库，应用 `0003_video_jobs`，再核对 API/Worker/Beat 的 PostgreSQL、Redis namespace、MinIO、模型库主密钥一致；不得直接把旧 Redis 队列复制并启动。
2. Worker 与 outbox 派发未运行时，202 只表示排队成功，页面会显示等待执行器。显式 memory 模式仅用于测试，作业不跨重启、也不通过独立进程执行；不能用于正式生成。
3. 尚未启动真实 PostgreSQL/Redis/Celery 联调；临时 SQLite 多连接测试不等于已完成服务器进程宕机演练。本轮离线通过也不等于真实模型可用或画质通过。
4. 未承诺跨供应商恰好一次。未知提交且查不到任务号、或文本扩写结果未知时，保持锁定并人工核查；本批没有“确认未创建并解锁”的运营入口，也不自动取消供应商任务。未来增加该入口须保留审计与费用确认。
5. Redis/outbox 派发沿用既有机制；派发器卡在 processing 或消息未送达时不盲目重放付费请求，用户可对尚未执行的已保存作业明确安排恢复。完成结果仍以数据库为准。
6. 页面最小详情展示选中镜头的最新作业，完整历史作业选择和候选采用后置。当前 asset-store 抽帧契约沿用，不能把提示词/素材契约通过当作真实首尾帧视觉连贯性通过。

下一步：05 连续性与动作完成策略，先明确严格首帧/多图参考选择和换角色、换场行为；随后 06 角色整板与 14B 旧项目换风格。03 图片阶段与 04B 候选采用分别保留未完成状态。

回溯：`var/change-backups/durable-video-20260919/manifest.json` 为本批开始前 224 个相关源文件、测试与文档副本。保留工作区此前修改，不以 Git reset/clean 回退。

补充回溯文档2份见同目录supplemental-manifest.json，分别是启动说明和08迁移任务。
