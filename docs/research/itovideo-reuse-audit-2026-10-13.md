# iToVideo 源码拆解与 ComicFlow 复用评估

日期：2026-10-13。对象：用户提供的本地 iToVideo 源码，对照当前 ComicFlow 工作目录，包括未提交的实现。

## 结论

**有可以直接借用的代码，而且最有价值的部分集中在尾帧提取、剪辑时间轴、混音、字幕和素材交互。** 建议抽取这些能力接入 ComicFlow 已有生产流水线。整套画布、作业调度、模型管理和商品广告生成流程都需要另外评估，不能靠复制目录接通。

iToVideo 的创作工具覆盖更广，编辑交互更细；ComicFlow 已有的角色卡、候选采用、生成准备单、持久作业、未知提交恢复和版本失效机制仍应保留。两者使用相近技术栈，不代表业务数据结构或失败语义一致。

发现一项已离线复现的具体差距：**ComicFlow 当前的“尾帧”提取实际取到视频结束前约一秒位置的帧；iToVideo 有解码到文件结尾的正确实现。** 这是比增加提示词数量更直接的接续质量改进候选。

## 研究范围与证据边界

- iToVideo 服务仓 HEAD：`b582c3e`；前端仓 HEAD：`e5126f1`；两仓 tracked 文件均无未提交改动。结论依据本地源码，不等同于线上版本。
- 读取了路由、执行器注册表、实际调用路径、持久化代码、相关测试和 ComicFlow 对应实现；外部项目的文档与注释仅作为核查线索。
- 本轮只新增研究报告与本地合成视频验证产物。没有修改业务源码、配置或真实项目，也没有调用模型、启动服务、安装依赖或发布。
- 运行了 iToVideo 前端时间轴/轮询的 13 项离线测试，全部通过。更广的检查遇到当前 `node_modules` 缺少 Rolldown 本机原生绑定，不能据此认定功能代码失败，也不能宣称全项目构建通过。
- 没有真实模型画质、生产负载、线上部署或完整数据库恢复验收。“代码接通”与“生成效果更好”分别判断。

补充细节见[前端专项核查](C:/Users/lmk/Documents/ChatGPT/comicflow/docs/research/itovideo-frontend-audit-2026-10-13.md)和[提示词及媒体专项核查](C:/Users/lmk/Documents/ChatGPT/comicflow/docs/research/itovideo-prompts-media-audit-2026-10-13.md)。

## 1. 它实际是什么项目

### 技术与存储

| 层面 | iToVideo 当前实现 | ComicFlow 当前实现 | 对复用的影响 |
| --- | --- | --- | --- |
| 前端 | React + TypeScript + Vite，画布用 `@xyflow/react` | React + TypeScript + Vite，按生产阶段组织工作区 | 独立组件、纯函数较容易移植；整套画布引入新的交互与数据模型 |
| 后端 | FastAPI + Pydantic，psycopg 直接访问 PostgreSQL | FastAPI + Pydantic，SQLAlchemy + Alembic | 执行器算法可提取；仓储代码不能直接替换 |
| 长任务 | API 进程创建 asyncio 任务，阻塞执行器在线程执行 | 独立 Celery Worker + Redis + PostgreSQL outbox | 不采用它的调度器替换现有作业机制 |
| 项目事实 | 画布 `nodes/edges/viewport`；一键工作台另有 JSONB state/version | Project、Script、Scene、Shot、角色卡、资产、生成作业及导出快照 | 需要领域字段映射，不能只换页面 |
| 媒体 | MinIO/S3 对象键 + 资产表 + FFmpeg | MinIO/S3 对象键 + 资产元数据 + FFmpeg | 最适合复用算法和局部编辑能力 |

前端真实路由包括首页、项目库、模型管理、风格库、画布和工作台，见 [App.tsx](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_web/src/app/App.tsx:38)。后端路由注册见 [main.py](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/main.py:102)。

### 两条生产入口

**自由画布：** 图片/文本输入 → 可编辑分镜 → 套图或镜头生成 → 视频片段 → 拼接 → 音频/字幕加工。节点可以自由连线，前后端各维护一份端口与连线规则。实际执行器包含文本、套图、镜头、音频、合成、视频加工、抽帧等，见 [registry.py](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/registry.py:24)。

**一键工作台：** 商品主图及可选补充图 → 商品识别 → 创作准备 → 人工编辑 → 单段或连续视频制作 → 拼接 → 音频/字幕 → 交付。当前商品模板按 **8 + 6 + 10 = 24 秒**组织三段，首尾段由固定模板填充，文本模型主要负责中间的卖点演绎。它不是 ComicFlow 的通用中文故事拆分。依据：[reference_film.py](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/reference_film.py:134)、[creative_authoring.py](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/creative_authoring.py:45)。

文件名 `reference_film.py` 不足以证明支持“上传参考影片并自动拉片”；这里核实的是商品图片和尾帧接续路径。

## 2. 最值得拿过来的能力

这里的“可直接借用”指可以提取主体算法或组件，仍需对接项目类型、样式、权限及原接口；没有宣称复制后无需验收。

| 能力 | 技术复用等级 | 能给 ComicFlow 带来的实际变化 | 推荐顺序 |
| --- | --- | --- | --- |
| 真正的尾帧提取 | 很小范围移植 FFmpeg 参数 | 相邻镜头使用实际末帧，避免接续到先前动作状态 | 第一 |
| 多轨时间轴组件 | 组件主体可移植，接 props/事件/样式 | 在成片上拖动音轨和字幕、缩放、定位播放头 | 第一 |
| 音轨裁剪与播放时长计算 | 纯函数可提取 | 统一裁剪起止、音轨位置与预览时长 | 第一 |
| 转场接缝计算和 FFmpeg 拼接 | 算法可提取，合成接口需适配 | 显式设置转场，并准确扣除重叠时长 | 第二 |
| 多音轨混音与背景音乐压低 | 滤镜构造可借用，数据与执行需适配 | 配音时压低 BGM，支持音量、淡入淡出与音效 | 第二 |
| 字幕自由定位、样式、ASS 动效 | 算法/编辑交互可提取，字幕来源需独立处理 | 可预览并调整字幕位置、字号和进入效果 | 第二 |
| 素材分组和来源展示 | 展示函数容易移植，资产契约需适配 | 图片/视频/音频分类、套图版本、来源与历史更清晰 | 第一或第二 |
| 风格库卡片与预设管理交互 | UI 可借鉴，内容和快照适配 | 从紧凑风格下拉扩展为可浏览的风格库 | 后续 |
| 请求返回路径解析器 | 标准库纯函数可提取 | 支持更复杂的供应商响应取值路径 | 有真实协议需求时 |
| 自由节点画布 | 只能做较大功能移植 | 用户自主组织输入、生成与后期生产 | 最后，单独决定产品方向 |

### A. 尾帧提取：有实测证据的优先项

ComicFlow [frame_extractor.py](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/utils/frame_extractor.py:35) 使用 `-sseof -1 -frames:v 1`。前者从距结尾一秒的位置开始解码，后者立刻只取一帧，因此不能保证取到视频实际最后一帧。

iToVideo [ffmpeg.py](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:843) 尾帧模式使用 `-sseof -1 -update 1 -fps_mode passthrough`，解码到 EOF，不断覆盖同一输出图；[video_check.py](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/video_check.py:74) 另有末秒 `reverse` 后取一帧的实现。

本轮生成了一个 2 秒视频，前 1.7 秒红色，最后 0.3 秒蓝色：

| 方法 | 实际提取颜色 | RGB | 判断 |
| --- | --- | --- | --- |
| 直接执行 ComicFlow 当前 `FrameExtractor._extract_last_frame` | 红 | `[254, 0, 0]` | 不是最后画面 |
| 使用 iToVideo 的 EOF 覆盖参数 | 蓝 | `[0, 0, 254]` | 与实际结尾一致 |

证据：[结果 JSON](C:/Users/lmk/Documents/ChatGPT/comicflow/output/research/itovideo-tailframe-2026-10-13/result.json)、[合成测试视频](C:/Users/lmk/Documents/ChatGPT/comicflow/output/research/itovideo-tailframe-2026-10-13/red-then-blue.mp4)、[当前方法提取图](C:/Users/lmk/Documents/ChatGPT/comicflow/output/research/itovideo-tailframe-2026-10-13/comicflow-current-tail.jpg)、[EOF 方法提取图](C:/Users/lmk/Documents/ChatGPT/comicflow/output/research/itovideo-tailframe-2026-10-13/itovideo-eof-tail.png)。

它确实用于 ComicFlow 视频资产尾帧保存：[video_frames.py](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/production/video_frames.py:55)，后续准备读取 `lastFrameObjectKey`。因此这是生产路径上的真实差距，不只是闲置工具。

推荐只在原 `FrameExtractor` 接口内移植参数与必要校验，保留异步线程调用、对象键隔离和现有依赖失效机制。新增单镜视频、短于一秒视频及不同帧率的聚焦验证。已有视频和尾帧不会因为研究报告自动更新；本轮没有修复，也没有据此断言某个历史作品的问题都由此造成。

### B. 时间轴与音频后期：最明显的工具差距

iToVideo 的 [Timeline.tsx](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_web/src/pages/one-click/components/Timeline.tsx:19) 以 props 和事件回调为接口，未把整个工作台状态仓储作为依赖；这是适合移植的组件形状。[audio-timing.ts](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_web/src/pages/one-click/audio-timing.ts:1) 是音轨起止、裁剪和播放时长计算的独立函数。

ComicFlow 已有逐镜头声音时间轴和原声试听：[AudioWorkspace.tsx](C:/Users/lmk/Documents/ChatGPT/comicflow/frontend/src/features/audio/AudioWorkspace.tsx:44)，也已有合成时镜头裁剪：[composition_jobs.py](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/production/composition_jobs.py:83)。所以应增强当前声音/导出工作区，把可编辑的多轨能力补上，无需重新建立全部合成作业。

适配必须明确：秒与毫秒换算、裁剪后成片坐标、轨道稳定 ID、保存版本、候选/当前资产关系。它的自动变速和截断逻辑不能默认用于 ComicFlow 原声，避免为了“塞进时长”悄悄改变已生成对白。

### C. 转场与混音：提取计算，不复制执行器

iToVideo [ffmpeg.py](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:221) 的 `clamp_transition_seconds`、`build_seams`、`plan_join` 和 `seam_seconds` 计算重叠上限与拼接分组。相邻片段转场会改变全片时长，字幕与音轨必须使用同一套接缝结果。

[audio_mix_filters](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:651) 包括 BGM 侧链压低与音轨处理；可复用其滤镜构造思路，输出仍由 ComicFlow 原合成 Provider 保存，作业状态仍由 `CompositionJobs` 管理。

不要复制其整份媒体文件的分辨率表：那份表中 `2K` 对应高度 1080，标签语义不应直接进入 ComicFlow；生成模型分辨率和最终编码尺寸也不能混为一谈。

### D. 字幕：可以借编辑和渲染，不能凭空得到真实时间戳

前端的定位/预览纯函数与后端 [write_ass_positioned](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:966)、`subtitle_anchor`、`subtitle_effect_tags` 可组成一套预览与烧录一致的字幕能力。

但 `subtitle-timing.ts` 中的词级排版需要已有词级时间数据。它不是 H3 原声的识别器，不能把原剧本文字按比例分段后冒充真实识别字幕。ComicFlow 当前保留镜头级字幕草稿的契约仍有效；可先支持人工时间和位置编辑，真实 ASR 对齐单独决定。

### E. 素材库：抄交互，保留“采用”的领域含义

iToVideo 资产记录有 `batchId`、`parentAssetId`、`sortOrder`、`selected`，见 [assets.py](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/repositories/assets.py:23)。这些可用于套图分组、来源展示和素材挑选。

ComicFlow 已有当前项目视频资源库，区分 current/candidate/historical/stale，并按资产 ID 做权限与访问签名：[video_resources.py](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/production/video_resources.py:42)。因此“资源库”不是从零补建；更实际的增量是扩展图片/音频分组和更好的候选浏览。

套图勾选 `selected` 不等于 ComicFlow 资产采用 `valid`。挑选图片、采用角色参考图、采用镜头视频必须分别对接原操作。

另有三项适合小范围提取的交互：

- [asset-label.ts](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_web/src/canvas/asset-label.ts:69) 的通用资产分组函数，改用 ComicFlow 领域标签后即可用于资源卡片。
- [FilmStep.tsx](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_web/src/pages/one-click/steps/FilmStep.tsx:20) 的提示词参考图链接展示，可抽成小组件接入现有准备单；引用编码仍由 ComicFlow Adapter 生成。
- [shot-candidates.ts](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_web/src/canvas/shot-candidates.ts:31) 的历史参数快照投影规则：历史产物只显示生成时的参数，缺失不能拿当前草稿补齐。复用此展示原则，不复制浏览器里的候选账本。

目标 Timeline 的画面轨目前只展示镜头段，没有视频段拖动排序或画面头尾拖动手柄；现有拖动主要针对音轨和字幕。因此它适合做后期编辑的基础组件，不能当作完整剪辑器直接交付。

### F. 供应商返回路径：独立实用，但没有需求时不必迁移

iToVideo [template.py](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/providers/template.py:56) 的 `parse_path/get_path/text_at/list_at` 支持数组下标、按字段筛选及 `[*]`，例如 `output[type=message].content[type=output_text].text`。这部分只依赖 Python 标准库，适合需要时提取。

ComicFlow 已有 [model_protocols.py](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/providers/model_protocols.py:126) 的模板能力，但响应路径目前更受限。若新增供应商确实需要复杂返回形状，可扩展取值算法，仍需补保存时语法验证和 Provider 消息契约。路径解析能力本身不意味着已经完整支持 Responses 等新协议。

**不整体复制它的 `render` 行为**：目标实现会省略缺失变量、铺平列表；ComicFlow 当前对未知变量明确拒绝。照搬会改变请求的失败行为，并可能静默遗漏必需输入。

## 3. 这些地方不建议照搬

### 后台调度与超时恢复

iToVideo 确实有数据库作业记录、事务级指纹防重和终态保护，不是纯前端伪状态。证据：[tasks.py](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/repositories/tasks.py:104)、[tasks.py](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/repositories/tasks.py:162)。

不过执行句柄在 API 进程内：[runner.py](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/runner.py:89)。重启时把在途作业标失败，工作台保留 checkpoint 再继续；其他视频路径超时还会尝试取消供应商作业并删除本地任务，见 [runner.py](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/runner.py:172)。不能把这些机制等同于独立 Worker 的可靠投递与未知提交恢复。

ComicFlow 已有同事务 outbox、作业领取租约、operationKey/active slot、unknown/recoverable 和候选采用接口，见 [video_jobs.py](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/infrastructure/video_jobs.py:258)、[VideoJobs](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/production/video_jobs.py:148)。保留这些，借用目标项目“当前进度继续”和逐段制作的交互即可。

### 模型配置与启动迁移

iToVideo 仓储直接保存并查询 `api_key`，API 的 ModelConfig 响应也包含 `apiKey`：[models.py](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/repositories/models.py:38)、[模型响应 schema](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/schemas/models.py:57)。ComicFlow 现有加密保存并在公共读取时移除密文：[model_registry.py](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/providers/model_registry.py:130)。复制它的模型管理后端会退化现有能力。

iToVideo 启动会建附加表、改部分模型默认配置、清理在途状态：[main.py](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/main.py:76)。ComicFlow 的 Alembic 显式迁移及发布规则应保持，不借此引入启动时隐式升级。

### 整套商品模板与自由画布

当前一键商品模板的固定三段、商品颜色环境映射、广告结尾及 negative prompt 都服务于商品宣传。直接搬到中文漫剧会限制人物、叙事与镜头规模，并与现有 6–12 镜头/30–90 秒剧本契约冲突。

自由画布适合作为独立创作入口研究，但涉及节点、端口、边、保存、图校验、依赖失效和生产对象转换。它不是给现有页面添加一个图表组件；若决定开发，需要先明确如何与 Script/Shot 和持久作业共用事实，避免出现两套剧本。

## 4. 文档与目录容易造成的误判

1. **画布的“autosave”并非后端自动保存。** 当前画布是手动保存，配合 localStorage 暂存；工作台另有自动保存。不能按文件名认定刷新恢复机制一致。
2. **旧生产目录不是当前主链路。** `pages/one-click/production/pipeline.ts` 明确旧逻辑停用；不能把所有旧 assess/frame/check 流程都计入当前能力。
3. **Skill 在目录里不一定被调用。** 画布文本路径白名单加载了部分候选 Skill；另一份 cinematic Skill 未加载；工作台当前商品模板路径没有同样的 Skill 调用。
4. **风格快照保存不等于当前写作使用。** 画布文本路径会把风格上下文加入提示词；当前商品工作台虽保存 `recipeSnapshot`，`author_creative → writing_brief` 的显式输入没有该快照，输出全局风格取固定模板。默认简介可受风格选择影响，但不能据此称完整风格规则已经注入该写作入口。
5. **逐镜检查不等于语义质量评审。** 解码、时长、尺寸及实际尾帧校验能发现技术问题，不能证明人物一致、表演正确或故事有吸引力。

以上调用链及行号在两份专项报告中展开。

## 5. 推荐采纳顺序

**第一批建议：实际尾帧 + 现有素材浏览优化。** 前者已证明有确定收益；后者可用已有资产，无需增加模型调用。尾帧行为变更按项目规约先补失败测试，再在原接口内修复，并明确历史帧如何处理。

素材浏览优化可以具体限定为：资产分组标签、准备单参考图点击预览、历史参数详细卡。三项都接现有读取接口，避免为了 UI 迁移新增第二份状态来源。

**第二批建议：多轨后期编辑。** 以现有导出/声音页为入口，借用 Timeline、audio-timing、字幕预览与 FFmpeg 算法；先交付可保存的时间/音量/位置编辑，再支持转场、淡入淡出和 BGM 压低。所有坐标最终使用同一份合成计划。

**第三批建议：风格库浏览和必要的协议扩展。** 风格内容经过漫剧适配，用现有快照机制；供应商路径解析只在具体接入需要时扩展。

**自由画布单独评估。** 如果目的仍是尽快完成连续漫剧，不把它设为上述功能的前置条件。

这些是研究建议，不是已采纳的项目方向，也不是新的实施授权；本轮不改 ADR、规格或工程规约，不重排现有迁移与发布工作。

## 6. 直接复制的来源条件

技术复用可行性已按模块区分。所提供目录里没有找到覆盖主项目的 LICENSE；个别外部 Skill 有各自许可证，不能推导整个项目的授权。若主项目由你拥有或已获得复用许可，可以据此提取源码；否则先核实主项目与对应第三方内容的授权，保留来源和适用许可证。

## 7. 本轮验证

命令在 iToVideo_web 中执行：

```powershell
node --experimental-strip-types --test tests/timeline.test.ts tests/task-polling.test.ts
```

结果：13 passed，0 failed。覆盖字幕锚点、画幅预览、时间刻度、音轨裁剪/变速后的时长、字幕效果状态、轮询不重叠与停止后不再调度。这里只证明所覆盖逻辑在当前主机通过，不证明 JSX 组件交互、后端合成或真实模型效果全部通过。

另一次包含 `adaptive-style.test.ts`、`video-model-capabilities.test.ts` 的检查在加载 Vite/Rolldown 时遇到本机原生依赖缺失。未修复或重装提供的依赖目录。

尾帧验证使用本机 FFmpeg 合成双色视频，调用 ComicFlow 当前方法，与目标项目 EOF 参数对照；结果和媒体文件保存在 `output/research/itovideo-tailframe-2026-10-13/`，不涉及真实项目资产。
