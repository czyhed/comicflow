# 15A视频模块拆分与09A隔离联调验收

日期：2026-09-19。15A完成，09A隔离联调通过；09C首次真实生成待用户操作。05/06质量策略、15B/C/D、09B完整30秒模拟未开始。本轮真实模型调用0，未提交、推送或部署。

## 责任与兼容接口

- `production/video_preparation.py`：`VideoPreparation.character_inputs/prepare/preview`负责角色与场景引用、已有尾帧策略、视频输入和共享预检。显式接收项目/角色存储、Provider、资产存储、配置版本和签名函数；不提交模型请求，不保存项目。
- `production/video_jobs.py`：显式接收作业存储、准备模块、项目存储、视频/文本Provider、资产存储及配置版本，取消`pipeline: Any`和对Pipeline私有成员的访问。保留冻结快照、任务号先保存、租约、CAS及未知提交不重发行为。
- `production/video_frames.py`：抽出`extract_cascade_frames`，保留原FFmpeg、存储和错误行为。Pipeline的旧私有入口保留兼容委托，供已有Mock路径及测试使用。
- `production/interfaces.py`：增加可预览视频能力协议。Pipeline保留原公开入口和必要编排，不引入第二套状态机。

抽取前冻结11种合成输入的准备结果、请求描述与指纹，包含H3首镜、多图连续性、严格级联、显式帧、缺尾帧、Skill缺文本模型门禁及Wan/Mock路径。成功Skill扩写沿用既有回归。规范化标识符和局部导入后，抽出方法与6个查找/版本帮助方法的AST和修改前副本一致；本批未修改提示词、模型选择、参考顺序或分辨率策略。Pipeline从3253行降至2863行，行数仅作范围记录，不作为验收依据。

## 实际运行的检查

日志目录：`var/verification/video-module-split-20260919/`。

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 抽取前/后及最终聚焦回归 | 各52通过 | `baseline.txt`、`after-extraction.txt`、`final-focused.txt` |
| 后端全量 | 736通过、3条件跳过 | `backend.txt` |
| Ruff | 通过 | `ruff.txt` |
| Mypy | 78个源文件通过 | `mypy.txt` |
| 前端生产构建 | 通过 | `frontend-build.txt` |
| 视频任务、准备单、生产入口Playwright | 9通过 | `frontend-focused.txt` |
| 真实隔离数据栈/API/Worker恢复 | 通过 | `runtime-report.json`、`runtime-first.txt` |
| 本机已有项目只读页面与参考图 | 通过 | `local-runtime/browser-readonly.json`、`local-preflight-desktop.png`、`preflight-safe.json` |

后端离线运行入口为本轮留存的`run_offline.py`，清理供应商环境并禁止socket连接；3项跳过是2项可选业务样本回放和1项旧的opt-in基础设施检查。不能将跳过写成通过；本轮另用下述独立真实基础设施联调补充证据。全量之后仅做接口类型收敛，再跑52项聚焦、Ruff、Mypy通过。

前端本轮没有产品代码变更。9项聚焦使用模拟API；另对本机真实API做只读浏览器检查，拦截除预检外的变更请求和所有外部请求，未出现被拦请求或页面异常；项目、任务列表、生成会话、模型配置、风格及准备单返回200。随后实际播放已有首镜视频，浏览器readyState=4、播放时间前进，读取到768×1344、5.175秒，记录在`local-runtime/existing-video-playback.json`。这是旧视频的播放结果，不是本轮新生成结果，也不能证明下次供应商一定输出同样规格。

## 09A真实基础设施范围

入口：`tests/integration/video-runtime.compose.yml`和`verify_video_runtime.py`；[复现步骤](../../tests/integration/README.md)。独立Compose项目`comicflow-video-verify-20260919`，无发布端口、无业务.env，数据库/MinIO使用tmpfs，Docker网络`internal: true`阻断外网。当前源码只读挂载，缓存镜像只提供Python依赖和FFmpeg。

实际验证了：真实PostgreSQL迁移0003、API创建视频作业和outbox、Redis发布、独立Celery Worker执行；假H3只提交1次，任务号先保存后终止Worker并重启API；显式恢复查询，不重新提交。模拟下载503后再次恢复，仅取回原任务结果。视频、首尾帧实际进入MinIO，签名下载字节与本地视频一致。

报告计数：假提交1、查询3、下载2；作业记录文本0/视频1；真实模型调用0。测试主动推进的是临时测试数据库中的租约时间，不代表等待真实900秒；outbox通过真实Dispatcher/Celery显式派发，未在此测试中启动Beat定时器。请求分辨率为768P，测试媒体是本地FFmpeg制作的360×640、5秒蓝色视频，不能据此声明供应商输出768P或画质合格。测试容器和网络已按专用Compose项目清理。

## 本机试用环境与备份

用户选择复用本机已有项目。修改前代码/测试/文档219份副本及SHA256清单：`var/change-backups/video-module-split-20260919-174930/`。此前未提交改动全部保留。

业务库升级前备份位于忽略目录`var/verification/video-module-split-20260919/local-runtime/`：

- `database-before-0003.dump`，已用pg_restore列表验证；`database-backup-list.txt`保存清单。
- `model-config-before-0003.tar.gz`保存原配置解密密钥卷；`backup-sha256.json`保存校验值。

这些备份含私有数据/密钥，不应上传仓库。MinIO对象未迁移、未修改；回溯时须保留现有数据，不能在用户新生成后直接覆盖数据库。仅结构抽取可恢复对应源码副本，不使用全仓库reset。

本机PostgreSQL由0002升级至`0003_video_jobs`，153项目、26角色保持不变。模型库revision29可读取，原API/Worker/Beat停止；原PostgreSQL/Redis/MinIO运行。新版API使用当前源码、相同模型密钥卷和独立Redis命名空间`comicflow-local-validation-20260919`，地址`http://127.0.0.1:18002`；前端`http://127.0.0.1:5173`代理该API。部署服务器未改动。

启用前只读盘点为0个视频作业、0个未发布outbox，新命名空间为空。**用户明确回复“启用验证专用Worker/Beat”后，两个进程已启动并检查就绪**：Worker只监听新命名空间，模型库revision29、H3/768P/5秒与API一致；Beat每2秒派发，实际空outbox处理返回0，仍0个业务视频作业。未恢复旧队列，未向业务库创建测试作业。

操作记录：此前包含消费者启动的合并操作被自动审批拒绝，仅返回`blocked by policy`，该组操作未执行。之后先完成独立只读核查及前端启动，再取得用户明确启用消费者的授权；单独启动通过。此阻塞已解决，不代表曾绕过拒绝。

## 首次真实验证交接

消费者启用和就绪核查已完成，现在交用户点击。入口和启停步骤见[本地启动说明](local-test-startup.md)。本次选定《深夜便利店诡事》`prj_8386abe590d7`的`sh1`“推门进入便利店”，现有项目version11。

1. 打开本机页面并选择该项目，进入「画面」第1镜。已有视频时按钮显示「重新生成」，不是“生成全部”。
2. 刷新准备单，确认MiniMax-H3、配置版本29、768P、5秒、9:16、`ref2va`、参考图1张、预计文本0/视频1。如配置已由用户改变，以页面重新检查为准。
3. 当前是本地中文编译加优云Context-IR优化，**没有调用文本模型执行英文H3 Skill**；本批保持既有路径。参考图从MinIO按对象键取字节、校验后嵌入请求，首镜实际字节检查已通过，无须把本机127.0.0.1图片地址开放给供应商。
4. 用户只点一次该镜生成，观察作业阶段、供应商任务号及结果。刷新应仍能读到同一任务；已知任务中断使用「继续查询 / 保存已有任务」，未知提交先核查供应商，不能重复新建。
5. 完成后确认新视频可播放、供应商记录的参数/用量符合预期，保存任务号与画质反馈。该次调用可能计费；准备检查不能验证余额或保证模型质量。

现有逻辑在输入匹配时自动采用新视频，历史资产保留；“所有新视频先预览再人工采用”属于04B，尚未实现。首镜验证不证明相邻镜头连续性合格：当前sh2预检是两个人物主图加上一尾帧，共3张普通参考，尾帧不是严格首帧。05再完善入场、动作终点和模式策略，06再实现一次图生图整板。

首次反馈后进入05/04B，再15B/06/03B最小图片记录；09B完整30秒模拟及用户质量验收随后进行。完整样本按既有6—12镜头契约使用6×5秒，不在15A调整剧本校验。
