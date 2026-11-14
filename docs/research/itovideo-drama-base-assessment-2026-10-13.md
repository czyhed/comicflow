# iToVideo 漫剧版底座评估

日期：2026-10-13。状态：评估建议，供用户审阅及 6.1sol 后续开发使用；不代表已替换项目或已授权发布。

## 1. 结论与前提

**建议以 iToVideo 完整前后端建立独立的漫剧版，保留其页面、画布及配套接口，再定向迁入 ComicFlow 的漫剧能力。**

用户最新目标是保留 iToVideo 几乎所有可见部分，不是必须保留 ComicFlow 的全部内部实现。在这个目标下，先拆出所有前端再接 ComicFlow，会同时适配画布、素材、配方、任务、一键工作台和后期编辑。保留 donor 成套链路更可能减少改动面。这是调用关系支持的工程判断，尚无实际移植工时证明，不是“iToVideo 后端整体更好”的断言。

若首版必须无缝读写全部 ComicFlow 旧项目、完全保留额度/权限/版本规则并直接替换线上系统，应重新比较兼容成本。本次没有替用户决定丢弃旧项目。建议两套环境并存，旧数据留在原系统，迁移单独验收。

## 2. 证据范围

路径缩写：

- I-W：`C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_web`
- I-S：`C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service`
- C：`C:/Users/lmk/Documents/ChatGPT/comicflow`

本轮核对版本：I-W `e5126f1f984249cf6036fc5e69f364c892d9aefd`；I-S `b582c3ea8b16387c04fd23538210710c54e3461d`。两 donor Git 工作区 `status --porcelain` 均无输出。ComicFlow 有大量既有未提交变更，不能只取 HEAD，也不能整体搬走全部未提交内容。

读取实际路由、前端调用、执行器、归一化、仓储和测试源码；运行两项不导入应用的归一化探针。未启动服务、连接业务数据库、读取真实配置/密钥、安装依赖、调用模型、执行迁移或修改业务代码。本轮只新增本报告和交接文档。

用户演示观感作为产品偏好输入；本轮未亲自重新操作整套 UI，不能证明所有展示功能可用、画质更高或生产性能更好。已复核工程规约、CONTEXT、ADR 0001–0006 和既有实施计划，沿用 codebase-design 的接口/实现分离方法。

## 3. 能保留什么，必须改变什么

下表执行器路径均相对 I-S `app/services/executors/`，前端路径相对 I-W `src/`。

| 模块 | 源码事实 | 漫剧版处理 |
| --- | --- | --- |
| 首页/项目/模型/配方/画布/Studio | `app/App.tsx:38` 注册真实页面 | 保留页面结构、交互和导航；品牌与必要内容调整 |
| 自由画布 | `canvas/CanvasStage.tsx:154`；`canvas/hooks/useNodeRun.ts:227` 按连线构造请求 | 连线确实影响输入，成套保留；不退化成点击跳旧页面的镜头图 |
| 画布写作 | `text.py:197` 写作指令明确限定商品宣传片 | 新增漫剧分支，核对每一层提示词注入，避免只换 UI 文案 |
| 分镜解析 | `prompts.py:200` 只返回固定字段 | 对白、角色和场景贯穿解析/编辑/保存/提交，否则模型返回也会丢失 |
| 一键工作台 | `assisted/creative_authoring.py:51` 与 `product_template.py:18` 固定商品 8+6+10 秒模板 | 保留准备/编辑/逐镜制作/拼接/后期 UI，替换为漫剧计划 |
| 角色 | 已有图片/套图、多参考和素材绑定；未核实到与 C 对等的项目角色卡模块 | 在原素材和节点框架增加稳定角色身份、参考版本、镜头绑定 |
| 视频/H3 | I-S `app/services/providers/xiangong_h3/` 已接 multipart 与 `/api/v1/jobs` | 复用适配器，核对实际参数、对白和引用；不重写 SDK |
| 后期 | `pages/one-click/requests.ts:36`、`:63` 已把原声/裁剪/音轨/字幕提交给 compose/enhance | 保留前后端和 FFmpeg 链路，验证漫剧音频/字幕来源 |
| 风格库 | `pages/workspace/recipes/types.ts:32` 含镜头、故事、动作、接续与画风 | 保留配方 CRUD/收藏/应用；C 画风只能迁入其中的风格部分 |

### 归一化问题的实际探针

从原 `prompts.py` AST 提取原样 `shot_items` 与 `normalize_shots`，未执行模块 import。输入一个 12 秒镜头，携带 `id/sceneId/characterIds/dialogue/narration/prompt`。

| 参数 | 输出时长 | 丢失字段 |
| --- | --- | --- |
| `preserve_durations=False` | 10.0 | id、sceneId、characterIds、dialogue |
| `preserve_durations=True` | 12.0 | id、sceneId、characterIds、dialogue |

两项断言通过。这证明此函数不保留这些输入字段，不代表整套画布没有稳定 ID：前端已有稳定分镜行 ID。当前 TextExecutor 在 `text.py:237` 使用 `preserve_durations=True`，不能声称这一入口必然把 12 秒变成 10 秒；前端 `canvas/sync.ts:36` 仍有 5–10 秒 clamp，需要编辑保存往返测试。

## 4. 接口差异的实际影响

| 操作 | iToVideo | ComicFlow | 采用 donor 底座后的处理 |
| --- | --- | --- | --- |
| 项目 | 元信息/分页，另读 graph 或 Studio | 包含 Script、资产、作业的项目快照 | 保留原项目接口，避免翻译全部快照 |
| 画布保存 | GET/PUT `/api/projects/{id}/canvas` | 尚无对应自由图接口 | 保留并修冲突行为 |
| Studio 保存 | GET/PUT `.../studio`，独立 JSON state/version | 按故事/剧本/生产阶段分别修改 | 保留，增加漫剧 schema/workflow 版本 |
| 提交 | POST `.../canvas/generate`，nodeType/taskType/params/inputs | POST `.../shots/{shotId}/video-jobs`，版本/准备指纹/operationId | 保留 donor 外部接口，内部补必要作业保护 |
| 恢复/采用 | 任务表、remote ID、部分 checkpoint、前端选择 | 专用 recover/adopt 与版本校验 | 按故障场景补齐，不机械翻译全部状态 |
| 角色 | 素材和节点引用 | 角色卡、主图/整板候选、确认、版本 | 抽取规则，适配 donor 存储 |
| 风格 | 配方 CRUD/收藏/快照 | visual-styles 目录与项目风格快照 | 保留 donor 配方框架，补漫剧内容与应用链路 |

两边都用 HTTP/JSON 不意味着可以只改 base URL。但保留 donor 的前后端，就可以避免大部分上述接口翻译。

## 5. 后端不作整体排名

### iToVideo 已有的能力

- PostgreSQL 保存 graph、Studio、任务和素材，不是只在浏览器里演示。
- `app/repositories/tasks.py:104` 以事务级指纹锁防并发重复提交，复用 PENDING/RUNNING/SUCCEEDED。
- Studio 保存 `app/repositories/studio.py` 使用行锁与版本检查。
- `tests/test_video_resume.py` 覆盖已知远程任务只查询、不重复 POST 的 mock 场景；本轮读了源码，未执行这组测试。
- `app/services/studio_resume.py` 和 `assisted/reference_film.py` 已保留部分产物/checkpoint，不能说“没有恢复能力”。
- 多参考、指定视频版本尾帧、合成及音频字幕已有完整模块。

### 已核实的差距

| 项目 | 证据/含义 | 处理原则 |
| --- | --- | --- |
| 画布覆盖冲突 | I-W `src/canvas/hooks/useCanvasSave.ts:158` 收到 409 后采用新版本号重存本地整图；I-S `app/repositories/projects.py:119` 先读版本后无版本条件 UPDATE，未见行锁 | 前后端一起修；拒绝静默覆盖；真实 PG 双会话测试。并发丢失为源码推断，尚未运行复现 |
| 执行与重启 | `runner.py:89` 在 API 进程创建任务；`repositories/tasks.py:219` 重启将部分任务标 FAILED | 先补提交未知/已知任务恢复/持久结果。独立执行器按故障测试和部署需求决定，不以“换 Celery”代替验收 |
| 超时不一致 | `runner.py:172` 附近保留 Studio film 远程任务，但普通视频尝试取消及删除本地记录、留回执 | 漫剧付费路径保留 ID 和历史，查询超时不当作远程失败，恢复不重新付费提交 |
| 采用 | I-W `pages/one-click/film.ts:176` 完成或 verification 可自动 accepted | 漫剧默认区分技术完成和用户选用，保留历史；使用原版本 UI |
| 首帧 | `executors/shot.py:95` 可将冲突锚定帧改成参考图 | 严格首帧模式冲突要提前提示，不能改变用户已选择的含义 |
| H3 参数 | `providers/xiangong_h3/request.py:62` 固定 1.0P | UI 档位、实际像素、compile_prompt 和引用清单一致；复核实例能力，不隐式提高规格 |
| 模型密钥 | `repositories/models.py:38`、`schemas/models.py:64` 公共响应包含 apiKey | 保留模型页；密钥只写入，回读配置状态/掩码，保护服务端存储 |
| 登录 | `app/api/auth.py` 源码固定账号口令 | 实际使用前配置化；它已有会话鉴权，不应误写成“没有鉴权”。多租户另计 |

这是有限架构评估，不是全量安全审计。也不能由 C 的框架更复杂推导质量更好。本报告对执行与恢复的判断依据是上列源码；两套实现的可靠性仍需通过进程中断、重复提交和结果持久化等故障测试验证，不能仅凭框架名称下结论。

## 6. ComicFlow 的迁入优先级

| C 路径 | 迁入价值 | 方式 |
| --- | --- | --- |
| `backend/src/comicflow/providers/message_contract.py`、`production/story_scripts.py` | 场景/镜头/角色引用、对白/旁白校验 | 抽取适用校验和 fixture，不搬整个流水线 |
| `production/character_assets.py`、`character_boards.py`、`reference_images.py`、`providers/character_prompt.py` | 角色身份、参考图用途、文字整板、确认 | 优先规则与提示词；适配 donor 仓储，不复制旧角色页面 |
| `providers/h3_context_ir.py`、`h3_inputs.py`、`xiangongyun_h3.py` | 中文对白、引用、预览与请求一致 | 对照 donor 适配器，确定唯一编译路径，避免双重编译 |
| `production/video_jobs.py`、`infrastructure/video_jobs.py`、`production/image_jobs.py` | 提交未知、恢复、采用、结果来源 | 迁行为契约/故障测试，再适配；不把整套 outbox/SQLAlchemy 当独立函数粘贴 |
| `production/visual_styles.py`、漫剧写作提示词 | 画风、角色和中文叙事规则 | 映射到 donor 配方，确保画布与 Studio 真正使用 |

上表首个路径已相对 C 写全；其余 Python 路径以 `C/backend/src/comicflow/` 为前缀。同一单元格中省略目录的文件与前一个文件同目录。

首批不整体迁入：旧 AppShell/工作区外观、所有数据库、额度体系、全部模型配置仓储和部署链。不为保持技术名词一致而重写 donor SQL。

不要迁入已知退步项：C `utils/frame_extractor.py` 的尾帧问题已在前轮复现，本方案保留 donor EOF 尾帧方法。

## 7. 完整范围、难度和推荐排序

完整目标包含首页/项目/素材/模型/配方页面、自由画布、Studio、一键制作、后期和导出。先做画布闭环只是验证顺序，不是把用户范围缩成一张画布。

- 较低难度：保留页面/交互框架，调整品牌内容和漫剧配方。
- 中等难度：故事分镜数据往返、角色参考、对白/旁白、H3 参数、画布生成闭环。
- 中等至较高难度：固定商品 Studio 改成多场景漫剧计划，同时保持逐镜恢复和后期。
- 不确定性较高：极端故障恢复、旧数据无缝迁移、多进程生产部署、多租户。后几项不默认全部列入首版。

排序：① iToVideo 独立 fork + 定向漫剧改造；② 完整前端接 C 后端（旧业务兼容成为硬要求时再比较）；③ 从零重做所有可见部分。

不提供没有依据的复用百分比、token 预算或固定周数。基线构建及第一条闭环通过后再估计；界面已经存在不等于漫剧验收完成。

## 8. 验证边界与交接

- 本轮两项原归一化函数探针通过；不是端到端测试。
- 前轮 timeline/task-polling 共 13 项通过；本轮没有重复运行。
- 前轮 Vite 测试遇 Rolldown 本机绑定缺失。本轮 donor 无可直接用的 `.venv/Scripts/python.exe`，C 与当前 Python 环境未安装 psycopg。没有安装依赖、修改锁文件或伪造依赖跑通测试。
- 未完成全构建、数据库并发、UI 全流程、真实角色一致性或对白质量验收。
- 源码未必与用户演示版本一致，开工先逐页核对差距。
- 未发现覆盖主项目的 LICENSE。记录用户提供来源，不把外部 Skill 的许可推导为主项目许可；本技术报告不判断权属。

后续任务见 `C:/Users/lmk/Documents/ChatGPT/comicflow/docs/implementation/itovideo-drama-sol-handoff-2026-10-13.md`。

本报告按最新目标调整方案排序，前轮调用链/尾帧等事实仍有效。本轮不修改工程规约或接受 ADR。采用 donor 后端与 C ADR 0005 存在技术基线差异；后续实施应在新开发目标记录 fork 决策，若宣告替换 C 则同步更新其工程规约和 ADR，不能静默冲突。
