# 15D 合成作业与导出拆分契约

2026-09-22。用户批准按既定顺序开始第一批合成/导出拆分；故事/剧本已完成，声音留在下一批。沿用任务书v2.1第3节和工单15，不创建新的排期。

## 目标与范围

将Pipeline中的合成就绪检查、创建/执行/取消作业、导出清单读取收拢到 `production/composition_jobs.py`。模块显式接收ProjectRepository、CompositionProvider、可选AssetStore和当前模型配置revision；按当前Pipeline调用构造，不缓存旧配置，不反向依赖Pipeline。现有实现没有调用生成状态同步回调，本批不新增回调或Redis写入。

Pipeline保留原公开方法及 `_composition_readiness` 兼容入口；Worker继续通过 `pipeline.run_job(job_id)` 执行，原模型revision选择不变。原声/FFmpeg/视频资源模块直接复用。声音生成和局部口型重生成留待下一批，跨阶段自动推进继续归Pipeline。

三条HTTP路由（合成提交、导出清单、取消作业）归入 `api/composition.py`，保留权限顺序、状态码、请求/响应、作业归属检查；前端两个已有请求移入 `api/composition.ts`，保留client对象名称与调用方式，不增加取消按钮或页面功能。

## 保持的行为

- 输入仍为projectId、expectedVersion、idempotencyKey或jobId；现有版本校验先于幂等复用。H3已采用视频无需独立audioAsset即可排队，实际音轨由FFmpeg检查；缺音轨不调用TTS补救。
- 原作业状态、仓储claim、outbox事件、20内部额度预留/结算/失败取消释放保持。内部额度不是供应商价格。失败作业原有手动重执行能力保留；不新增自动重试策略。
- 产物必须包含video.mp4、cover.jpg、subtitles.srt；真实字节上传至原对象键，快照不保存字节。导出读取刷新签名且不写项目、不重新合成。
- 保持自动项目成功/失败时的阶段与generationSession更新。结构拆分不能宣称修复现有取消与正在执行FFmpeg的竞态、跨请求幂等原子性或导出历史覆盖问题；如发现阻断缺陷，单独记录和证明，不能借抽取修改状态机。
- 不修改schema、Provider协议、提示词、H3请求分辨率、音轨策略或真实配置，不更新业务运行服务，不调用付费模型，不提交推送。

## 验收与回溯

当前文件基线保存在 `var/change-backups/composition-split-20260922/`，保留此前未提交修改。原公开入口特征测试先在拆分前通过，再以同组测试验收拆分；覆盖配置/revision、合成门禁、原声音轨、额度、抢占、重复消费、取消权限、三种产物和签名读取。

比对移动方法的AST、完整OpenAPI和前端请求；运行后端相关聚焦及完整回归、Ruff/Mypy、前端build/Node和合成/原声/资源相关页面测试。测试清除继承的业务连接/密钥并禁止真实网络，媒体验证使用本机FFmpeg；完整真实隔离数据栈回归按固定计划在声音拆分后完成。本批不以旧849通过报告代替新验证。

完成后更新HANDOFF、工单15、主任务书及验收记录，仅标记合成/导出完成；下一项声音剩余职责，再完整不扣费隔离回归。实际迁移部署仍暂停。
