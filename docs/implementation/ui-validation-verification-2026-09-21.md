# 7A主流程UI验收与本机真实验证指南

日期：2026-09-21。主流程UI整理及本机运行更新完成，现在交用户小额真实验证。未调用真实文本、图片或视频模型，未测试供应商连通性，未提交、推送或部署服务器。模拟证明工程流程，不保证供应商可用性和实际画质。

## 本批修改

- AppShell仅对实际全自动项目显示生产会话控制，避免导入项目读取缓存后误显示；阶段/状态中文化，根据实际快照显示合成中或成片就绪。
- 分镜页增加“到剧本编辑当前镜头”，定位对应场景和镜头；支持键盘选择，删除“编辑将在未来版本开放”的错误提示。
- 角色主图候选在设定未保存时禁止确认；说明重新生成可能计费，删除重复生成入口。三视图仍独立确认。
- 创建页删除只改本地文字、不改变真实调用模型的下拉框，明确模型按用途在顶部“模型 API”中配置。
- 调整参考图宽度、顶部换行和分镜编辑入口布局；只处理现有主流程，不重建UI或扩大提示词任务。

业务文件：frontend/src/components/AppShell.tsx、features/storyboard/StoryboardWorkspace.tsx、features/characters/CharacterReferences.tsx、features/create/CreateWorkspace.tsx与styles.css。后端业务代码本批未修改。相关角色、导入会话及分镜缺陷先失败测试后修复。

## 已执行检查

| 检查 | 结果 |
| --- | --- |
| 前端构建/类型检查 | `pnpm build`通过 |
| Node回归 | 27通过 |
| Playwright全量 | 77通过，含390px导航/角色页无横向溢出与未保存确认保护 |
| 独立真实基础设施浏览器集成 | 1通过，约57秒；假供应商、真实PostgreSQL/Redis/Celery/MinIO/FFmpeg |
| 实际合成媒体 | 30.022秒、1080×1920/30fps、H.264/AAC，六段运动与原声顺序通过 |
| 本机业务只读检查 | API健康、前端入口、项目/角色、图片字节、作业读取、准备单通过 |

完整隔离集成在本批最后的创建页静态模型说明及状态文字调整之前执行；之后全量77项和build通过。后端沿用上一批817通过/3条件跳过基线，不冒充本批重复执行。普通Mock浏览器测试的18001只读代理拒绝日志与4184真实隔离贯穿结果分开记录。

贯穿内容和复跑命令见[09B报告](full-flow-verification-2026-09-21.md)。本批证据：var/verification/ui-validation-20260921/integration-report.json、media-report.json；临时comicflow-verify-flow栈已关闭。H3请求为768P，1080尺寸是本地合成输出，不是H3计费档位。

## 本机运行更新

先核对旧任务、备份并验证，再从0003升到0004_image_jobs。153项目、26角色保留，升级前后project_states与characters校验值一致。旧嵌入式记录中2 queued/6 running仅保留历史，没有重新派发或伪造完成；升级前无未发布outbox、无活动持久视频作业，新命名空间为空。

数据库和解密密钥备份在var/verification/ui-validation-20260921/local-runtime/：database-before-0004.dump、model-config-before-0004.tar.gz、database-backup-list.txt及backup-sha256.json。代码回溯副本在var/change-backups/ui-validation-20260921-162101/。这些均保存在Git忽略的var目录；含密钥的运行配置和备份不能上传。

本次验证使用旧本地PostgreSQL/Redis/MinIO数据卷及comicflow_comicflow-model-config密钥卷，未搬往服务器。API、Worker/Beat共享当前源码和同一持久模型库；COMICFLOW_COMPOSITION_PROVIDER明确为ffmpeg，队列命名空间为comicflow-local-validation-20260921。旧comicflow-api/worker/beat容器仍停止；其他项目容器未改动。

- 页面：http://127.0.0.1:5173/；API：http://127.0.0.1:18002/。
- 前端代理已指向18002。验证Worker收到ping并回复pong，Beat派发检查返回0。
- 收尾核查：schema0004、持久视频作业1条（原成功记录）、图片作业0、活动槽0、未发布outbox0。启动和只读核查未产生新生成作业。
- 主图gpt-image-2.5（chat-image），参考图编辑wan2.6-image（wan26-image）；二者是独立用途绑定。
- 用户明确批准将编辑尺寸720*1280改为1536*1024。仅更新该模型的size，其余配置保留；模型库revision29→30，保存后读取验证通过，未生成图片。
- H3仍为MiniMax-H3、768P、中文context-ir；便利店首镜准备单显示5秒、9:16、ref2va、文本调用0/视频调用1。这是预计调用，不是已经发出。

机器记录：local-runtime/readiness.json、size-update.json、final-audit.txt及data-before.txt/data-after.txt。未向供应商查询账户余额或实际模型状态。

## 用户现在怎样验证

1. 打开5173；当前停在《深夜便利店诡事》的角色页。其他浏览器可通过“打开已有项目”选择该项目（prj_8386abe590d7）。
2. 先复用“主角”的已确认主图，不必重做故事、拆分或人物提示词。点击“基于确认图片生成整张三视图（一次图片请求，可能计费）”，只点一次；等待候选，检查正/侧/背身份、服装和比例，满意再确认。此步由用户发起真实图片调用。
3. 到“画面”选第1镜“推门进入便利店”。先检查准备单的实际图片、动作/终态、台词和5秒768P；确认板应作为一个人物参考项。缺素材或校验失败先处理，不点击批量生成。
4. 仅生成这一个镜头；观看人物是否一致、是否完成进入店内、声音是否符合剧本。满意才“采用”。出现未知/超时先查看作业和供应商已有记录；有任务号时优先继续查询/保存，不新建重复任务。
5. 首镜满意后再验相邻第2镜：出现夜班店员应携带该角色有效参考图，同时检查上一已采用镜头尾帧与场景。ref2va中的尾帧是连续性参考，不保证硬性首帧。采用上游新版本会使依赖结果需要重做，历史文件仍保留。
6. 两镜效果合格后再补齐其余镜头并合成约30秒。先给出此次板与首镜的反馈，不为凑满30秒连续付费重试。

《暴雨末班车》首镜现被VIDEO_SPEECH_OVER_BUDGET拦截，原因是已有5秒镜头旁白过长；本次没有擅改剧本或增加时长，不建议直接拿它重试。两项目共六张已有角色主图的实际字节读取均HTTP200。便利店准备单通过仅说明输入和配置符合当前契约，不代表空间描述、画质或动作已人工验收。

本批没有重写旧人物提示词、Skill或风格库。保存的旧内容继续用于主图；整板使用已确认主图及现有整板规则，中文H3沿用context-ir，不额外调用文本模型润色。

## 停止与再次启动

当前服务已经运行，不需要再次启动。此次不要运行旧scripts/start-local.ps1，它会启用旧消费者并使用不同代理端口。下列命令只适用于本次已核查、没有新增未知任务的验证环境；若已有未知/进行中作业，先核对记录。

```powershell
# 仓库根目录；先运行Docker Desktop
docker start comicflow-postgres-1 comicflow-redis-1 comicflow-object-store-1
docker compose --env-file var/verification/ui-validation-20260921/local-runtime/empty.env -p comicflow-local-validation -f var/verification/ui-validation-20260921/local-runtime/compose.json up -d api worker beat
# 另一个终端
cd frontend
pnpm exec vite --host 127.0.0.1 --port 5173 --strictPort
```

停止验证消费者和API可使用相同compose参数执行`stop beat worker api`，不删除数据卷。停止前先查看是否有进行中任务。后续先收真实反馈；05B扩展/其他模块拆分按实际问题推进，迁移演练及服务器发布仍后置。
