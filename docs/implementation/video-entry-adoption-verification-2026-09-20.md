# 视频入口统一采用与接口拆分验收

日期：2026-09-20。对应任务书v2任务1、04B剩余入口、15C-video。状态：本地代码与离线验收完成；运行服务未更新，真实质量待用户验收。

## 本批结果

全部新视频作业先保存为候选，包含新video-jobs、旧同步`/visual`、局部重生成、自动会话及Mock。生成成功仍为`succeeded`；播放确认并显式采用后，才替换当前有效视频。调用方不能传入跳过采用的开关。旧已持久保存作业继续按原标志读取/恢复，不批量改写历史。

候选不覆盖旧视频，也不自动生成音频、下一镜或成片。采用继续使用已有输入指纹、配置、对象存在和事务检查，重复采用幂等，依赖旧尾帧的视频及相关下游结果按既有规则失效。没有新增表、迁移、工作流框架或模型调用。

## 结构与接口

- `backend/src/comicflow/api/video.py`：集中8个视频/局部重生成路由。路径、访问校验和请求级模型用途绑定保持；通过Pipeline公开方法查询作业，不访问私有存储。
- `frontend/src/api/video.ts`：集中准备、生成、作业查询、恢复、采用和重生成调用；注入原请求函数，沿用认证与错误处理。
- `production/pipeline.py`：统一委托已有VideoJobs，移除Mock即时安装分支及已无调用者的抽帧转发方法；真实抽帧仍由独立video_frames模块承担。
- `production/video_jobs.py`：新作业固定要求采用；现有执行、未知状态、恢复和存储机制复用。

相对路径的后端文件位于`backend/src/comicflow`，前端文件位于`frontend/src`。

旧`/visual`成功响应保留`asset`、`projectVersion`，增加`jobId`、`awaitingAdoption`。新候选`asset.valid=false`、`status=candidate`。`scope=shot`遇候选立即返回同样字段及`scope/visual`，此时不返回音频时间轴；音频/口型范围保持原独立调用语义。既有供应商错误响应形状保持。

同步兼容入口以项目版本、配置版本及当前采用资产ID标识操作：同一候选的重复请求复用原作业，未知提交不会自动重发；采用后显式再次生成可以创建下一份候选。需要明确创建独立新操作的调用者使用video-jobs和新的operationId。

自动会话复用`paused`，持久保存`pauseReason=video-awaiting-adoption`、`waitingJobId`、`waitingShotId`，清除失败文案。在视频、声音、合成前检查已有候选；重复推进不新建作业。未采用时resume返回409 `VIDEO_JOB_AWAITING_ADOPTION`。采用本身不恢复会话；用户“继续”仅回到ready，“推进”或后续执行器推进才处理下一阶段。若等待前已到声音/合成阶段，显式继续先回到storyboard-ready核查失效依赖。

批量用正常状态提示等待采用，提供定位镜头按钮，不再显示“生成中断”。再次批量点击会先检查保存的候选，即使该镜头仍有旧有效视频，也不会跳过去生成后续镜头。刷新后仍可从作业记录播放/采用；停止或离开页面不取消已提交的供应商任务。

## 验证过程

1. 先结构搬迁、后行为调整：同一组原聚焦测试（durable_video_jobs、visual_preflight、generation_sessions）抽取前后均71通过，前端构建通过。
2. 后端先失败用例：同步/visual/shot三个入口、Mock、自动暂停及已有候选识别，共6项先证明旧行为不符合要求。后续补声音/合成阶段候选检查和恢复阶段校验，均先观察失败再修复。
3. 前端先失败用例：候选被误当失败、等待采用仍可继续；另证实旧有效视频存在时批量越过替换候选。修复后均通过。更新既有端到端测试，显式采用后才执行声音/合成，不用全局自动采用夹具绕过门禁。
4. 全量后端：`.\.venv\Scripts\python.exe -m pytest backend/tests -q --tb=short`，**752通过、3跳过**。两项未提供本机脱敏项目夹具；一项未启Docker基础设施smoke。H3两种提示词路径使用MockTransport及实际FFmpeg通过，禁止真实模型网络；临时SQLite持久作业测试通过，不冒充本轮真实PostgreSQL/Worker联调。
5. 静态检查：Ruff通过，Mypy检查78个源文件通过。
6. 前端：`pnpm build`通过；`node --test tests/*.test.mjs` **27通过**；`pnpm exec playwright test --workers=2` **73通过**。包括候选预览/采用、刷新、批量停止、自动会话手动继续及原声/资源/生产页面。测试日志部分旧用例有未拦截的只读GET代理到未启动的18001并返回ECONNREFUSED，不是业务服务验收；本批新增用例拦截全部`/api/**`。

全量日志：`var/video-adoption-backend-regression.txt`、`var/video-adoption-playwright.txt`。修改前文件副本：`var/change-backups/video-adoption-unify-20260920-202154/`。保留此前未提交工作，没有Git提交或推送。

## 边界和下一步

真实文本/图片/视频调用均0；未操作业务数据库、未部署或迁移、未重启API/Worker/Beat。浏览器测试使用4173测试预览，不代表5173的业务后端已加载新实现。

此次解决的是结果确认和入口一致性，不宣称人物质感、动作完成或两镜连续性已改善。本批未改参考模式、视频分辨率、提示词规则或角色三图调用次数。

下一项为任务2：角色15B/15C行为保持拆分；之后才做按用途角色提示词与一次图生图整板。若用户现在要真实验证，先更新实际API/Worker到本批代码并核查在途任务，再复用已有素材只生成一个镜头，检查候选→播放→采用→手动继续；由用户亲自点击，不必为结构拆分强制消耗额度。完整版本比较、图片作业和完整30秒/服务器迁移均未标完成。
