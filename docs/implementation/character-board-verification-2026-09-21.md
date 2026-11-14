# 06B 一次整板与独立确认验收

日期：2026-09-21。结论：本地实现、离线测试及隔离基础设施联调通过。真实模型调用0，真实人物相似度、细节和角度质量尚未验收。

## 改动

确认主图 → 一次图片编辑生成正面/严格侧面/背面整板 → 查看候选 → 独立确认 → H3参考模式使用一张板。

新增purpose=board，复用ImageJobs与0004，不加表/Worker类型或额外文本调用。冻结主图、风格、模型配置和编译规则；候选存referenceBoardCandidate，确认前不覆盖referenceBoard。新接口`POST /api/projects/{pid}/characters/{cid}/reference-board/approve`接受candidateId和expectedVersion，SQL事务内检查来源及项目版本，重复确认无副作用。当前模型配置不可用也不阻止确认。

专用整板规则来自`skills/xiaoluo-visual-assets/references/character-board.md`，本地编译并记录Skill文件/hash；不代表额外启动一个Skill代理或文本模型。主图的单人正面/9:16构图不再进入整板提示词；未改变主图润色和六种风格预设内容。

使用用户配置的图片编辑模型和尺寸，不自动加分辨率或换模型。当前可用编辑协议为wan26-image；chat-image仍只支持文生图，不能因模型名称含image就假定能编辑。要求正方形/横版宽高比1—2.5，单边256—5760；供应商自身更严格的尺寸要求仍应按其文档配置。结果实际字节按H3格式、尺寸和30MiB限制检查，不合格不安装候选。

旧三图入口、旧素材、已排队任务和恢复保留兼容；新页面只提供整板生成。候选、正式板、失效板分别展示，历史分图可展开查看。生成之后是否合格由用户确认，没有自动重生或视觉打分。

## 证据

- RED：新增11项行为测试全部因缺少board用途失败；实现后通过，随后补下游选图/风格/HTTP确认测试，共14项通过。
- `uv run pytest backend/tests -q --tb=short`：816 passed，3 skipped。跳过的是两个外部脱敏夹具和一个需显式开启的基础设施冒烟；本批另跑真实隔离基础设施，不能把跳过当作通过。
- `uv run ruff check backend/src backend/tests`通过；`uv run mypy backend/src`：85个源码文件通过。
- 前端`pnpm build`、Node测试27项、Playwright全量75项通过。之后仅调整整板卡片间距/预览宽度及修正测试fixture的completedSteps，重新构建和角色页3项通过。已查看候选板截图，使用纯色假图，仅验布局与交互，不是画质证据。
- `docker compose -p comicflow-verify-board -f tests/integration/image-runtime.compose.yml up --abort-on-container-exit --exit-code-from verify`：退出码0。独立PostgreSQL/Redis/Celery/MinIO、Docker internal无外网；主图1次+整板1次假提交，5次查询、3次下载。两阶段均测试Worker强制中断/API重启、当前绑定清空后按原配置恢复；租约到期在测试库显式模拟。
- 整板POST校验`n=1`、配置size不变、主图base64解码后与确认主图字节一致。候选保存在MinIO且可读取；确认后经生产VideoPreparation和H3 reference_plan得到1张对应人物板。未真实提交H3。
- 验证后已关闭并移除本次`comicflow-verify-board`容器/网络；未操作业务API/Worker/Beat、业务库或供应商。

机器报告与日志：[隔离报告](../../var/verification/character-board-20260921/image-runtime-report.json)、[后端回归](../../var/verification/character-board-20260921/backend-tests.txt)。改动前副本位于`var/change-backups/character-board-20260921-135219/`。

## 边界与下一步

本地通过不代表当前运行页面已更新。图片作业依赖0004；本批只在临时数据库应用迁移。真实试用前需安排业务数据备份、schema/运行镜像核对和API/Worker同版升级，不能直接把新页面接旧服务，也不能重放旧付费队列。

用户可在环境就绪后复用一张满意主图，只验证一张整板；先检查三视图是同一人物、角度齐全、服装稳定、脸部清楚，再点击确认。模拟只能证明请求/记录/恢复和选图，不能保证模型美术质量。

下一开发任务为任务5：相邻两镜参考选择与动作衔接，特别是前镜尾帧、下一镜人物/场景参考以及模式冲突的明确呈现。本批H3单板选择证据针对ref2va；没有声称首尾帧模式会同时传入人物板。后续任务6完整30秒流程，任务7UI整理及数据库、MinIO、密钥迁移部署。
