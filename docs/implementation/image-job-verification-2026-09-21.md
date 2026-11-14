# 任务4：角色图片作业可靠性验收

日期：2026-09-21。状态：主图候选与现有三视图的可靠作业已本地完成；一次整板及独立采用仍是下一批。

## 实际行为

角色页提交快速返回202和jobId。图片记录先进入PostgreSQL，与outbox同事务提交，已有Celery负责执行；唯一操作键、角色活动槽与带token的租约防止重复提交及旧Worker回写。刷新从服务端读取状态，活动/未知作业阻止新生成。

万相异步接口取得任务号立即落库，再轮询/下载；进程中断或下载失败沿用任务号恢复。同步chat-image响应丢失标记unknown，不能通过普通恢复或新operationId重发。明确拒绝或供应商终止才释放活动槽。本地unknown不会替用户取消上游任务。

冻结图片输入、Skill执行元数据、角色revision/来源主图、风格和模型库revision；Worker按历史配置执行。角色已改变时，未提交步骤停止；已付费完成的图片留在作业结果中，可获取图片链接，不能覆盖当前素材。角色编辑/主图确认增加乐观保存检查，防止旧快照抹掉新候选。

三视图仍为正面、四分之三、侧面三次生成，已有成功视角逐项记录；恢复跳过已保存视角。本地四格板合成失败只重试合成，不再次生图。主图候选仍需用户确认。提示词/Skill规则/风格文字/图片布局均未调整。

## 模块与接口

- 新增 `production/image_jobs.py`：输入快照、执行、进度、恢复及公开输出。
- 新增 `infrastructure/image_jobs.py` 与 `0004_image_jobs.py`：独立 `image_generation_jobs` 表、CAS/租约、事务安装和outbox；沿用现有栈，不把视频表改成通用框架。
- `character_assets.py` 保留角色编辑/确认、请求组装与本地拼板，移除旧同步长生成循环。Pipeline只作委托；旧同步HTTP入口也通过同一作业防重门禁。
- 图片Adapter增加可选检查点，API增加提交/列表/详情/恢复；Worker无自动付费重试。模型选择增加只解析图片历史绑定的入口。
- 角色页新增进度、任务号、已保存数量、恢复与未知提示；前端图片API单独维护。

提交：`POST /api/projects/{pid}/characters/{cid}/image-jobs`，字段expectedVersion、operationId、purpose（candidate/views）、force。查询：`GET /api/projects/{pid}/image-jobs`及`/{jobId}`。恢复：`POST /api/projects/{pid}/image-jobs/{jobId}/recover`。

## 验证证据

先补失败测试，确认5项因缺少request_image_job失败，再实现。最终新增19项覆盖并发、重启、任务号落库失败、未知响应、同步超时、来源变化、配置变化、部分视角恢复、最终保存失败、拼板失败、坏图片下载、权限和迁移约束。

| 检查 | 结果 |
| --- | --- |
| `uv run pytest backend/tests -q --tb=short` | 802通过/3条件跳过 |
| `uv run pytest backend/tests/test_durable_image_jobs.py -q --tb=short` | 19通过 |
| `uv run ruff check backend/src backend/tests` / `uv run mypy backend/src` | 通过；84个源文件 |
| 前端 `pnpm build` / `node --test tests/*.test.mjs` | 构建通过，27通过 |
| 前端 `pnpm exec playwright test` | 75通过 |
| 隔离PostgreSQL/Redis/Celery/MinIO | 通过；真实模型调用0，假图片提交1、查询3、下载2 |
| 0004下原视频隔离恢复回归 | 通过；假H3提交1、查询4、下载2，候选采用/MinIO/FFmpeg首尾帧及播放通过 |

后端3项条件跳过：2项缺少外部脱敏夹具，1项默认未启用基础设施冒烟。本批另行执行的隔离图片联调已通过，不能将这些跳过说成全都执行过。Playwright部分旧测试未拦截辅助请求，日志有127.0.0.1:18001连接拒绝；75项测试通过不代表业务服务在线。

隔离联调使用 `tests/integration/image-runtime.compose.yml`：不发布端口，Docker internal网络禁止外网，数据库/对象数据为临时tmpfs，假供应商在容器回环地址。通过真实HTTP提交后强制终止Worker、重启API、停用当前模型绑定；原job仍按历史revision恢复，下载先故意503，再恢复并验证MinIO字节与候选图。没有启动业务Worker/Beat，没有访问业务数据库/付费队列。临时Compose已关闭。另将原视频联调脚本的schema期望更新为0004，并按已实现的候选采用契约补显式采用；在独立项目重跑通过，结果保存在 `var/verification/image-jobs-video-20260921/runtime-report.json`，未覆盖9月19日历史报告。

证据目录：`var/verification/image-jobs-20260921/`，包括backend-tests.txt、playwright.txt、image-runtime-report.json。回溯副本：`var/change-backups/image-jobs-20260921-114109/`。没有提交/推送。

## 运行限制及下一步

- 0004仅在临时测试库应用；业务库未升级，API/Worker运行版本未更新。不要把源码验收当成页面已可用。实际启用须先备份、核对在途和队列，再一致升级schema/API/Worker；不自动重放旧付费队列。
- 本批仅角色主图和现有视角，不宣称场景生图也已异步化；同步供应商没有查询能力时，未知结果仍需人工核对，无自动重发/找回承诺。
- 下一批：确认主图 → 一次图生图生成正/侧/背整板候选 → 独立确认 → H3使用一张已确认板。复用本批记录及恢复，不再重建作业系统；不增加文本润色调用或复杂布局编辑器。
- 本批不要求用户付费验证；一次整板完成并模拟通过后，再复用满意主图由用户生成一张板检查效果。数据库、媒体、模型密钥迁移仍在任务7，本批不执行迁移。
