# iToVideo 前端逆向与 ComicFlow 复用审计

日期：2026-10-13。范围：本地源码静态核查；未启动服务、未调用模型、未读取密钥或 `.env`，未修改两项目业务代码。结论中的“已实现”表示有路由、调用者与 API 请求实现，不表示本次已完成真实浏览器或供应商验收。专项静态核查未执行测试；主调查已运行 timeline/task-polling 共 13 项，全通过；Vite 相关检查被 Rolldown native binding 缺失阻断，其他用例未跑。

## 结论

**最值得拿的是时间轴、字幕编辑和资产展示的局部模块，以及编辑草稿与生产事实分离的设计。不要整套复制自由画布或一键成片控制器。** 两项目都用 React + TypeScript + Vite，局部视图和纯函数有较好的复用基础；但领域模型不同：ComicFlow 是故事 → 场景/镜头 → 已确认角色资产 → 持久生成作业 → 明确采用 → 合成，iToVideo 当前 Studio 主路径明显偏商品图驱动的商业短片。外观接近不等于生产契约相同。

ComicFlow 已有持久视频作业、候选采用、历史视频、版本门禁、严格上一镜尾帧与局部试片，不能当作空白重建。真正明显缺少的是多轨可视编辑与字幕后期编辑；资源浏览和准备单更适合做展示升级。

先读的约束：`docs/PROJECT_ENGINEERING_RULES.md`、`CONTEXT.md`、ADR 0002/0003/0005、`docs/implementation/quality-and-modularity-taskbook-2026-09-19.md`、`ui-validation-contract-2026-09-21.md`、`selected-shot-composition-2026-10-09.md` 与 `shot-continuity-editing-2026-10-09.md`。本文只提出候选，不改变目前执行计划。后续采用仍需定义实际输入、输出、失败行为及离线验收，不引入新的通用编排平台。

## 如何确认不是目录里的空壳

下列来源路径以两个源码根为基准，所有 `:行号` 都是本次读取的实际行号：

- **I** = `C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_web/src/`
- **C** = `C:/Users/lmk/Documents/ChatGPT/comicflow/frontend/src/`

| 入口 | 实际调用链 | 当前判断 |
| --- | --- | --- |
| `/projects/:projectId/canvas` | `I/app/App.tsx:53` → `CanvasPage.tsx:71` 的 `useProjectLoader` → `hooks/useProjectLoader.ts:83` 读取资产；`canvas/api/projects.ts:36` 读取 `/api/projects/{id}/canvas` | 自由画布有实际页面和持久化接口；舞台是 `CanvasStage.tsx:154` 的 ReactFlow |
| 画布保存 | `CanvasPage.tsx:98` → `useCanvasSave` → `api/projects.ts:43` 的 `saveGraph` PUT `/api/projects/{id}/canvas` | 手动保存，内容变化写浏览器缓存；文件名 autosave 不代表服务端自动保存 |
| 画布资产库 | `CanvasPage.tsx:225` → `AssetsDrawer.tsx:26` 过滤 role → `asset-label.ts:69` 分组；资产来源为 `api/assets.ts:29` 的 GET `/api/projects/{id}/assets` | 已有图片/视频网格；不是所有资产种类的完整管理平台 |
| “历史”抽屉 | `CanvasPage.tsx:233` → `HistoryDrawer.tsx:27` 的项目 Link → `projectRoute`；列表接口 `api/projects.ts:26` | **项目切换历史**，不是成片版本历史、撤销栈或审计记录 |
| `/studio`、`/projects/:projectId/studio` | `app/App.tsx:54` → `StudioPage.tsx:23` 的 useStudio → `controller.ts:99` → `api.ts:12` GET `/studio`；`api.ts:19` PUT 保存 | 独立 Studio 状态，不读画布 store；与自由画布不是同一运行态 |
| 当前 Studio 准备与生产 | `StudioPage.tsx:38` 有 preparation/film 时切换到 FilmStep → `FilmStep.tsx:89` → `actions.ts:108` 的 renderFilm → `film.ts:82` 组装 render 请求 → `tasks.ts:129` 的 runJob → `api.ts:26` POST `/studio/generate` | 实际连接的当前路径；含任务查询、断点、逐镜或自动渲染 |
| 时间轴/字幕后期 | `StudioPage.tsx:41` → `steps/ArrangeStep.tsx:88` ArrangementPreview 与 `:97` Timeline → `requests.ts:63` finalRequest → `taskType=video_enhance` → `/studio/generate` | 有编辑到请求序列化链路，不是单纯截图；导出侧还依赖服务器实现 |
| `/recipes` | `app/App.tsx:47` → RecipeLibraryPage → `recipes/api.ts:5` 列表/创建/修改/收藏；`RecipeUseDialog.tsx:27` 建快照并用路由 state 传给 Studio/Canvas | 有持久 API 与应用流程；不是纯静态配方展示 |

**容易被误判的旧代码：** `pages/one-click/production/pipeline.ts:3` 明确写 “Retired checkpoints”，`:6` 直接返回“旧版制作流程已停用”。旁边 `production/state.ts` 的 assess/frame0/check0/frame1/check1/compile/verify 不能据文件存在认定当前产品提供完整自动视觉打分和两轮修图。`StudioPage.tsx:38-39` 仍保留旧路径兼容渲染，但当前 preparation/film 路径转到 FilmStep。`FilmStep.tsx:111` 的“重新生成分镜提示词”只有 DEV 构建显示。

## 9 个具体候选

### 1. 可视时间轴：最强的组件复用候选

来源：`I/pages/one-click/components/Timeline.tsx:19` 定义 TimelineShot，`:21` 定义 props，`:49` 实现。全部输入和事件由 props 提供，没有 useStudioContext、画布 store 或 API 依赖。

已实现：ResizeObserver 自适应宽度（`:55`）、0.5–24 倍缩放（`:16`）、随播放头滚动（`:98`）、requestAnimationFrame 合并拖动事件（`:114`）、声音出现位置拖动（`:245`）、头尾裁剪（`:264/:281`）、字幕整体移动和头尾调整（`:310/:332/:350`）。依赖 React、lucide-react、`shared/frame-size.ts` 的刻度函数、`audio-timing.ts` 与 AudioTrack/SubtitleLine 类型，以及 `pages/one-click/styles/timeline.css`。

**复用方式：** 复制 Timeline 的视图与刻度/拖动逻辑，定义 ComicFlow 的小型 Timeline view model，通过适配函数将已采用镜头和现有裁剪草稿转成 props。最初可以只展示画面段、播放头、镜头裁剪，后续再启用音轨和字幕。

**边界：** 当前画面轨道只展示镜头段（`:217`），没有视频段拖动排序、拼接磁吸、波形、缩略帧或视频头尾拖动；不要把它叫完整非线性剪辑器。ComicFlow 现有 `C/features/export/ExportWorkspace.tsx:45` 保存页面内裁剪草稿，`:157` 播放原视频，`:161` 输入入点/出点，`:71` 用既有 composition 请求提交。这个接口是最低迁移成本的落点，但 Timeline 原组件本身需要新增画面裁剪手柄。

优先级 **P1**；前端展示迁移成本低，持久可编辑音轨成本另算。参考测试：`iToVideo_web/tests/timeline.test.ts:130` 刻度缩放与 `:155` 音轨裁剪；不代表浏览器拖动已经本次验证。

### 2. 音轨时长与裁剪计算：可以按函数迁移

来源：`I/pages/one-click/audio-timing.ts:8` 的 AudioTiming 只有 startAt/in/out/duration/fitSeconds；`:17/:23/:31/:38` 分别计算源长度、速度、播放长度、结束位置；`:48/:60` 是头尾裁剪纯函数，无第三方依赖。

优势：时间轴和试听预览复用相同计算，避免“条形长度正确、实际试听错位”。`ArrangementPreview.tsx:66` 计算 speed，`:73` 设置 playbackRate，`:74` 淡入淡出，`:87` 修正播放位置；这是有实现的同步逻辑。

**复用方式：** 函数可直接移植，经 AudioTiming 输入适配即可；ArrangementPreview 需先将 `:42` 的 useStudioContext 改为显式 props，不直接拖整个 Studio 类型进 ComicFlow。

**边界：** fitSeconds 允许最多 1.35 倍加速，仍太长则裁到目标长度（audio-timing.ts:25/:34）。此策略可能截断对白，与 ComicFlow“不为凑时长无提示截断台词”的现有契约不能等同；首批仅启用明确的裁剪/位置计算，加速和截断应由用户明确选择并由 FFmpeg 契约复核。ComicFlow `C/features/audio/AudioWorkspace.tsx:25` 目前读单镜时间轴和音频，缺少此类多轨编排；不应借前端迁移隐式生成 TTS。

优先级 **P1/P2**：基础计算 P1，新增上传音乐/音效、混音、淡入淡出和持久编辑 P2。

### 3. 字幕坐标、动画与词级分句：函数质量高，但导出必须一起接

来源：`I/shared/frame-size.ts:42` subtitleAnchor、`:56` subtitlePosition、`:73` containRect；`I/shared/subtitle-effect.ts:78` subtitleAnimationWindow 与 `:99` subtitleEffectState；`I/canvas/subtitle-timing.ts:4` fitWordsToTrack 与 `:24` buildKaraokePhrases。

已实现：按实际 contain 后的视频矩形定位字幕，x/y 使用 0–1 归一化坐标；支持 none/fade/rise/zoom/blur/slide；暂停时让字幕清晰可定位，点击预演才播放入口动画；词级时间戳按 >0.35 秒间隙、>10 字或 >2.4 秒拆句。`ArrangeStep.tsx:46` 修改字幕，`:57` 添加字幕；`requests.ts:106` 将字幕 segments 和 style 提交给 video_enhance。

**可直接取用的部分：** containRect、坐标回退、动画窗口与状态计算、分句逻辑，不依赖 store/API。**必须改造的部分：** `frameSize:26` 的 720P/1080P/4K 语义不能代替 ComicFlow H3 0.5P/544×960 及最终 1080×1920 输出；应该从实际输出规格读取宽高。

**边界：** 原函数明确要求与后端 ffmpeg.py 的 dimensions/subtitle_anchor/subtitle_effect_tags 同步（frame-size.ts:7；subtitle-effect.ts:5）。不能只搬前端 CSS 宣称所见即所得。词级对齐依赖 TTS result.segments[].words（arrangement.ts:45），ComicFlow 当前 H3 原声没有这份时间戳；没有数据时只能编辑人工字幕，不可把镜头级字幕标成逐句同步。ComicFlow `C/features/export/ExportWorkspace.tsx:119/:129` 已明确展示“字幕来自剧本与镜头时长，尚未语音时间对齐”，应保留诚实表述。

优先级 **P2**。一旦做字幕编辑，必须同时定义持久草稿、版本冲突、导出 ASS/SRT 与 FFmpeg 的效果契约。

### 4. 资产分组标签与缩略图：短平快，可先用

来源：`I/canvas/asset-label.ts:21` 标签回退、`:63` role 排序、`:69` 泛型分组；`I/canvas/api/assets.ts:105` createThumbnail 在浏览器生成最长边 160px、JPEG 质量 0.6 的缩略图，成功/失败都释放 object URL（`:119/:122`）。

**复用方式：** 分组纯函数与缩略图可以迁移；ComicFlow 需把角色主图/角色整板/场景参考图/候选视频/已采用视频/试片/成片映射成自身领域标签。AssetsDrawer 的 props 形式也方便改造（AssetsDrawer.tsx:17），但图片库网格样式不等于采用入口。

**边界：** Drawer `:14` 只允许六种 image/video role，音频和字幕被过滤；没有分页、搜索、删除、采用、过期签名恢复入口。`formatAssetAge:26` 默认无时区的北京时间字面值，用 new Date 按浏览器本地解析；ComicFlow 若返回带 UTC/offset 时间，应保留该事实并规范化，不能照搬时区假设。

ComicFlow `C/features/resources/VideoResourcesWorkspace.tsx:59` 已有后端分页筛选，`:25` 获取单资源临时播放链接，`:30` 隐藏重签过程中的旧 URL，`:42` 区分播放错误；这些能力应保留。优先搬标签/缩略卡而不是替换资源服务。

优先级 **P0**，收益来自“看清这张图是什么”，不需要新的生产状态。

### 5. 历史视频的不可变参数快照：值得学，现有能力先补展示

来源：`I/canvas/shot-candidates.ts:8` 从已成功任务取候选；`:31` clipGenerationSnapshot 存 prompt、负向、模型/协议、尺寸/时长、声音、seed；`:50` appendCandidate 按任务或 assetId 去重；`:73` 从旧 clip 节点恢复历史。

最有价值的规则是 `:30`：**历史产物从生成时任务快照取参数，不拿今天正在编辑的镜头补齐历史。** 同任务重复回包或签名 URL 更新不会新增版本（`:49`）。测试明确覆盖缺历史参数不能拿当前草稿补齐（`tests/shot-candidates.test.ts:136`），失败重生保留旧候选（`:151`），预览不改变输出（`:287`）。

**复用方式：** 规则与小型快照投影函数可迁移，ApiTask/ShotVideoCandidate/图连线恢复函数强耦合目标 store，需重写输入适配。ComicFlow 已有 `C/api/video.ts:52` adoptVideo、`C/features/visuals/VisualWorkspace.tsx:61` 候选展示、`VideoResourcesWorkspace.tsx:14` current/historical/candidate/stale；这是候选和历史能力的展示强化，不是新建第二份浏览器候选账本。

**边界：** 原 sameVideo 在无 assetId 时用 URL 去重（shot-candidates.ts:44），签名 URL 会变化，不适合作持久身份；优先保留 ComicFlow 对象键/资产 ID/作业 ID。跨资产“曾经用什么模型/提示词”应读取服务端原作业事实，缺失显示未知。

优先级 **P0/P1**；先补历史详细卡与可点击参考来源，再考虑版本并排对比。

### 6. 串行保存、脏状态与草稿恢复：复用局部策略，不拷贝保存政策

来源：`I/canvas/autosave.ts:36` serializeSave；`:82` buildSnapshot 将内容/运行态/视口分开比较；`:154` shouldRestoreCache 只在 baseVersion 等于服务端版本时恢复。`I/pages/one-click/persistence.ts:4` sameStoredValue 按对象键排序做 JSON 比较，`:14` sameJobCheckpoint 忽略 progress，`:18` nextPollDelay 未变化从 2.4 秒逐步到 10 秒。

Studio `controller.ts:64` 用 1.2 秒 debounce 自动保存，`:149` 保存时单个 Promise 串行、revision/savedRevision 处理保存中继续编辑，`:179` 冲突后 blocked。`tasks.ts:35` 只为恢复检查点变化持久化，不因每次 progress 更新写整份状态。其思想可降低写库/状态闪烁，不能据此声称已测出性能节约百分比。

ComicFlow `C/features/script/ScriptWorkspace.tsx:52` 的草稿在组件内，`:125` 显式 updateScript 保存，`:142` 确认前保存；`C/app/App.tsx:26` 活跃作业每秒拉 snapshot。迁移可从“剧本本地未保存草稿，带项目 ID + 基础版本 + schemaVersion”开始，刷新时提示恢复，业务事实继续来自 PostgreSQL。

**不能搬的政策：**

- 画布保存实际上是纯手动 + localStorage（autosave.ts:3；useCanvasSave.ts:86），不能替代 ComicFlow 服务端生成作业事实。
- `useCanvasSave.ts:158` 碰到 409 后拿新 version 用本地内容再存一次，`:181` 宣称“已用当前画布覆盖保存”；这可能覆盖另一窗口编辑，与 ComicFlow 现有乐观锁门禁冲突。取 Studio 冲突 blocked 的做法，不取这个自动覆盖。
- serializeSave 的锁为模块级全局 Promise（autosave.ts:34），多个项目会串在一条队列；若移植，应明确保存聚合边界。
- Studio 顶栏 `StudioPage.tsx:79` 在 projectId 存在且保存未超过 400ms 时显示“已保存”，没有按 dirty 显示待保存；不要把它当绝对可靠的保存事实标签。

优先级 **P1**，先做草稿恢复与保存队列；是否自动保存完整剧本需要单独产品决策，避免每次击键触发历史版本/下游失效。

### 7. 配方快照、输入清单与时长方案：产品结构值得搬，商品内容不适配漫剧

来源：`I/pages/workspace/recipes/RecipeUseDialog.tsx:27` 建 RecipeHandoff，包含 recipe 快照、planId、brief、mode；`:33` 传给 `/studio` 或 `/canvas`，不在此处发生成请求。`:52` 展示 inputChecklist。`recipe-prompt.ts:65` snapshotRecipe 存 ID/name/version/content/production；`:16` 内置配方只带公开摘要，服务器按 ID 解析详细来源。`recipe-timing.ts:21` planRecipe 选择预制或自定节奏，`:139` 累计时间轴；`recipe-beats.ts:8` 根据权重分配片内阶段时间。

**复用方式：** 保留 ComicFlow 已有 VisualStyleProfile 快照，增加少量实际需要的“剧情目的、适用输入、镜头节奏建议、避免项、验收清单”字段或预设说明，呈现成配方卡。先复用 `C/features/styles/StylePresetPicker.tsx:10` 现有目录，不立刻迁移整套用户配方 CRUD 平台。

**边界：** iToVideo `film.ts:49` 默认商品商业宣传片，`:50` 走 productStoryRequest，`:62` 强制 PRODUCT_STORY_MODE；配方中的产品保真和 sellingPoint 不直接替换漫剧人物/场景/对白约束。`shared/shot-timing.ts:2` 固定 5–10 秒、1–24 镜，与 ComicFlow 当前结构契约和供应商能力不完全一致；时间权重算法可借用，硬编码范围必须取项目/模型契约。内置源内容被删减，单搬前端配方快照不能得到后端私有详细模板。

优先级 **P2**。先做有限预设，不为本次分析恢复此前后置的复杂风格平台。

### 8. 提示词中的参考图可点击：小组件、高收益

来源：`I/pages/one-click/steps/FilmStep.tsx:20` PromptText 接收 text/references/onOpen，`:26` 只索引真正有 url 和 mention 的参考图，`:29` 分割 `@xxx` 并匹配，未知引用保持文本；`:43` secondLabel 对实际/计划时长偏差 ≥0.5 秒才显示两项。

**复用方式：** 把 PromptText 独立抽成小组件，给 ComicFlow VisualPreparation 的实际参考清单提供 ID → 图片卡关联；点击查看已传图片，不发起模型请求。只迁移参考展示，不把目标 `@char-1` 引用格式自动写进 H3 请求；引用编码仍由自身 Adapter 决定。实际时长说明也可以基于已有 asset.durationMs 显示。

现有 `C/features/visuals/VisualWorkspace.tsx:45` 准备单 query 与 `:52` 提交使用同一 continuityMode，`:171` 已展示媒体时长，具有正确接入位置。改造依赖 React 与既有弹窗，几乎不依赖目标后端。

优先级 **P0**。此项提升核对输入效率，但不承诺提升模型画质。

### 9. 分镜表格的编辑体验：学输入处理，不另造第二份镜头模型

来源：`I/canvas/panels/StoryboardTable.tsx:31` 为时长输入保留原文，失焦再转数值，避免清空后立刻钳到最小时长、第二个数字被错误拼接；`:99` 表格各字段可编辑；`:65` 删除先读取下游影响并确认。

**复用方式：** 时长输入控件的临时字符串机制可单独搬，改用稳定 shot.id 保存临时值；整批列表布局可以作为 ComicFlow 剧本编辑器的可选表格视图。当前 `C/features/storyboard/StoryboardWorkspace.tsx:11` 是只读卡片并显式跳转剧本编辑，不必为了“跟它一样”把分镜、剧本变成两个会写同一事实的编辑器。

**边界：** 目标直接连到 useCanvasStore，删除依赖 graph 的成员关系/传播；ComicFlow 的 sceneId/scene.shotIds 双向一致、稳定 ID 和服务端下游失效都不可用它的 shot.index + 节点删除代替。它在失焦时 clamp 5–10 秒（`:117`），ComicFlow 应按当前真实模型/剧本约束报错，避免静默改用户时长。

优先级 **P1**，先复用局部输入体验；是否新增全表编辑按实际需求决定。

## 不建议直接照搬的四个区域

1. **自由画布整体。** `CanvasStage.tsx:12` 引入 @xyflow/react，CanvasPage 以 ReactFlowProvider 包裹，节点、连线、端口、同步、脏传播、API 图结构均互相依赖。ComicFlow 持久主状态是领域对象和生成作业；整搬需要新的 graph 模型/接口/迁移，相当于产品方向改变。
2. **StudioController + tasks + film 整套生产控制。** 不是完全可独立模块，耦合 StudioState、ApiTask、自定义 operationId/nodeId、prepare/render/checkpoint、商品识别和配方服务。`tasks.ts:153` 保存 operation identity 后再提交值得学；但它仍是在前端控制器里恢复/投影结果，不能替换 ComicFlow 后端 Celery/outbox 与持久作业。`runJob:162` 在未找到已有任务后提交，需要审计目标后端幂等，不宜据前端一段代码宣称未知结果绝不重复付费。
3. **“accepted”语义。** `film.ts:176` 以成功视频和 job.status/verification 自动算 accepted，`:182` 当前链路强制 voiceEnabled=false。ComicFlow 新视频先候选、用户明确采用，其 H3 原声及独立配音契约也不同。这段数据投影不能搬成 ComicFlow 的采用逻辑。
4. **通用分辨率/时长/切换场景策略。** `frame-size.ts:26` 分辨率层、`shot-timing.ts:2` 范围和 `FilmStep.tsx:53` 每段接上一段尾帧均服务目标产品。ComicFlow 区分同场/换场、角色身份资产和严格上一镜尾帧选项；不能为表面一致抹掉已存在的条件门禁。

## 拿文件时的最小清单

| 可迁移文件/函数 | ComicFlow 映射 | 必须处理的依赖 |
| --- | --- | --- |
| `I/pages/one-click/components/Timeline.tsx` | `shots = selectedShots.map(s => ({id:s.id, name:s.title, duration:trim ? trim.outSec-trim.inSec : s.durationSec}))`；videoSeconds 为实际试片时长；time/onSeek 接 HTMLVideoElement；disabled 接合成是否在途 | 同目录外的 audio-timing、frame-size 刻度函数与 timeline.css；AudioTrack/SubtitleLine 换成本项目局部类型；未支持音轨编辑时传空 tracks，未支持字幕编辑时关闭字幕轨 |
| `I/pages/one-click/audio-timing.ts` | 明确将毫秒资产 durationMs 除以 1000，裁剪入出点是源文件位置；单纯显示长度不需要 fitSeconds | 无外部库；移植裁剪函数前复核有变速时 screen delta 与 source delta 的映射，原实现只用 delta 直接加源入出点 |
| `I/shared/frame-size.ts` 中 containRect/字幕坐标/刻度函数 | 实际输出 width/height → containRect；x/y 存归一化值 | 不复制 frameSize 的硬编码档位；边界值在服务端也验证 |
| `I/shared/subtitle-effect.ts` | 输出 effect state → 浏览器字幕样式 | ASS/FFmpeg 镜像规则必须同步；无导出实现先只标预览功能 |
| `I/canvas/subtitle-timing.ts` | 仅有真实 TimedWord 数据时组字幕 | 不从镜头时长捏造词级时间；H3原声没有 words 时走人工编辑 |
| `I/canvas/asset-label.ts` 的 groupAssetsByRole、`api/assets.ts` 的 createThumbnail | 本项目资产类型 → UI role；上传 File → 临时缩略图 | 替换标签目录与时间解析；缩略图只是预览，不取代原文件和对象键 |
| `I/canvas/autosave.ts` 的 shouldRestoreCache/serializeSave 思路、`one-click/persistence.ts` 的 JSON 比较 | userId + projectId + scriptDraft + baseVersion + schemaVersion | 重新定义缓存数据形状；不复制画布节点、运行态缓存、409覆盖和模块级跨项目锁 |
| `I/pages/one-click/steps/FilmStep.tsx` 的 PromptText | 已提交/准备单 prompt + 真实 reference manifest → 点击查看对应图片 | 抽成独立文件；引用名仅做展示，不改变实际 Provider 请求协议 |

上表是技术接缝，不是要求新增全量复制目录。最直接的组件仍是 Timeline；其余优先摘取单个纯函数和展示组件。迁移任何后期编辑都要让“服务端已有事实”和“未提交的编辑草稿”可区分。

## 建议迁移顺序与验收缝

| 批次 | 最小范围 | 保持的事实来源 | 应验收的内容 |
| --- | --- | --- | --- |
| A：展示完善 | 参考图可点击、资产角色标签/缩略卡、历史参数详细展示 | 现有准备单、作业、资源 API | 查看/筛选/播放不生成；历史参数不拿当前草稿补齐；过期签名可重新读取；未知来源显示未知 |
| B：局部可视编辑 | Timeline props 视图、刻度、现有 shotTrims 映射、时长输入体验 | 现有 composition expectedVersion/shotIds/shotTrims | 实际入出点、图片与原声同步裁剪、试片独立、原视频不变；手机和指针取消可用；画面排序按剧本而非浏览器擅改 |
| C：草稿防丢 | 项目/用户隔离、基于服务端版本的未保存草稿恢复、串行保存 | PostgreSQL 快照与版本门禁 | 刷新/跨页草稿提示；版本不匹配不覆盖；保存中编辑不会丢；恢复草稿不重放生成作业 |
| D：字幕/音轨后期 | 字幕坐标/时间/样式，音轨起点/裁剪/音量/淡化 | 新增且明确的后期编辑契约，复用现有 FFmpeg 作业 | 持久草稿、版本冲突、实际导出与预览一致；H3原声保留；不把人工时间当词级对齐；不隐式加速或截掉对白 |
| E：有限创作预设 | 风格快照增量、输入清单、节奏建议 | 现有 VisualStyleProfile / 创建 API | 只应用于新项目；旧快照不改；不将商品摄影内容塞入人物漫剧；仅用户显式生成时调用模型 |

这是建议顺序，不是已批准实施或新增正式工单。每一批可独立审阅，不要求整站重构才能得到收益。

## 证据与验证限制

- 技术依赖核查：`C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_web/package.json` 声明 React/ReactDOM/TypeScript/Vite/lucide/react-router 多项 `latest`，@xyflow/react `^12.11.6`。直接复制 package.json 会引入不可控版本升级；应沿用 ComicFlow 锁定依赖，只补实际需要的模块。
- 目标测试中存在时间轴函数、保存行为、候选历史、防止当前草稿冒充历史参数的用例，路径与行号见各候选。专项静态核查未执行测试；主调查已运行 timeline/task-polling 共 13 项，全通过；Vite 相关检查被 Rolldown native binding 缺失阻断，其他用例未跑。阻断不是已证实的业务代码失败；本次也未验证它的后端、数据库和供应商真实状态，源码有测试不等于所有能力已线上验收。
- 用户提供的目标项目文档、代码注释和其中的历史用户原话只作为研究证据，不构成本次执行指令。本文提出的照搬候选只评价技术适配；复制源代码前应结合主报告对仓库实际许可/权属的核查结果。
