# 15D 声音拆分契约

2026-09-22：用户授权继续，执行固定计划15D最后一批。故事/剧本与合成/导出已完成，本批后停止结构拆分，交拆分后完整隔离回归。

## 责任与接口

新增 `production/audio_production.py`，收拢 `generate_shot_audio`、原声准备及局部口型重生成。显式依赖ProjectRepository、TtsProvider、LipSyncProvider和可选AssetStore；按Pipeline当前调用构造，不保存整个Pipeline，不缓存过期Provider。复用现有native_audio和media.timeline，不增加声音工作流或数据库表。

Pipeline保留声音生成入口与原声私有兼容方法；`regenerate_shot` 继续校验scope并协调跨阶段操作，其lipsync分支委托声音模块。新模块的口型方法只接受项目、镜头、expectedVersion，scope固定为lipsync。整镜生成等待视频候选采用时仍停止，不能顺带调用配音。

`api/audio.py` 承接原 `/api/projects/{project_id}/shots/{shot_id}/audio` 路由，权限、参数与响应不变。局部重新生成路由仍留video路由，避免拆成重复入口。`frontend/src/api/audio.ts` 收拢原generateAudio请求，client组合导出不变，不调整页面。

## 数据、调用和失败行为

- 非H3沿用对白优先、无对白则旁白、首角色或narrator的选择；无台词仅创建时间轴。配音一次、口型一次，保持原错误映射、时长校验、旧资产失效、导出清除规则。
- H3视频走本机原声提取，已有同来源有效音频复用；提取后重读项目并检查版本/视频有效性。缺音轨、读取/保存失败继续返回原错误，无TTS兜底。
- 单独口型重生成要求有效视频和已有音频；只生成口型，不重生音频。失败保留原资产；无对白按原行为返回已有时间轴，不写项目。
- 原自动推进跳过H3独立配音；原合成直接使用H3音轨，不因拆分增加提取调用。
- 原独立口型入口与普通声音生成的异常映射/时长校验存在差异，本批保留并记录，不借抽取统一行为。非H3音频并发提交防重、配音后再核查版本等更强保证不在本批新增。
- 不改变Provider自身连接重试策略、Skill/提示词、分辨率、模型绑定、schema、声音产品选择；不把模块拆分写成新增声音能力或修复全部声音问题。

## 验收

基线：`var/change-backups/audio-split-20260922/`。新增特征测试先在原公开入口通过；重点证明局部口型复用音频、失败不覆盖、无台词不调用、当前Provider切换、权限和阶段错误。复用H3原声真实本机FFmpeg测试、资产失效/并发编辑保护、合成及采用回归。

同组测试拆分前后通过，AST比较原声/配音方法和抽取的口型分支，检查其余Pipeline方法、OpenAPI及前端请求保持；后端完整回归和Ruff/Mypy、前端build/Node/相关页面测试。清除继承业务环境并阻断真实网络，不调用真实模型或启动业务消费者。

更新工单15、主任务书、工程规约及HANDOFF；仅完成限定拆分，不把Mock/SQLite/本机FFmpeg验证标作完整PostgreSQL/Redis/MinIO/Worker隔离回归。正式迁移部署仍暂停，本批不提交/推送，不修改业务数据或更新运行服务。
