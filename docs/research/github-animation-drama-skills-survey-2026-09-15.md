# GitHub 漫剧生图、生视频与角色一致性 Skill 调研

调研日期：2026-09-15  
调研范围：GitHub 公开仓库源码、SKILL.md、README、参考规则、示例和仓库元数据。  
执行约束：只读访问；没有下载仓库、修改现有功能或调用图片/视频模型。

## 结论

目前没有证据表明某个外部 Skill 单独使用就能解决 ComicFlow 的成片质量问题。Skill 主要提供提示词结构、资产台账、连续性规则和生产门禁，不能替模型保证人物脸部或动作一定稳定；`zenstory-ai/drama-skills` 自己的角色一致性文档也明确把价值定义为“让必须一致的事实在生成前可检查”，而不是承诺零漂移。

最适合 ComicFlow 的组合是：

1. 保留项目现有的 `h3-prompt-writing` 作为 MiniMax H3 的供应商契约。
2. 吸收 `zenstory-ai/drama-skills` 的三层连续性模型：身份与造型分离、真实参考图状态、每镜冻结起点与终点、参考图用途标注。
3. 吸收 `eternityspring/shuohao-skills` 的角色设定图方案：一张角色资产板同时包含面部基准、正面/侧面/背面全身视图和细节条，并在出图前后做结构校验。
4. 参考 `xiaoweihu339-afk/character-anchor-skill` 的“候选图 → 用户批准 → golden reference”生命周期，避免失败图或最近生成图自动成为新人物基准。
5. 参考 `suihe1/short-drama-production` 的 H3 预检、样片审批、任务状态回写和付费任务禁止自动重试流程。

因此建议“规则级吸收”，暂不整体替换现有 Skill。真正需要优先验证的是 ComicFlow 是否在每个 H3 请求中传入了正确的参考图用途、上一段实际视频与尾帧，以及是否把批准后的角色资产作为唯一身份来源。

## 候选总表

| 候选 | 重点 | 对 ComicFlow 的直接价值 | 主要限制 | 建议 |
| --- | --- | --- | --- | --- |
| [shuohao-skills](https://github.com/eternityspring/shuohao-skills) | 角色卡、角色设定图、分镜图、H3 提示词 | 最完整的角色资产板和确定性校验；支持一次角色一张综合设定图 | 图片默认依赖 Codex `$imagegen`；H3 部分是提示词规则，不是 H3 生成器；部分规则假设自己的目录和 JSON 结构 | 优先吸收角色设定图版式、角色卡 schema、校验流程 |
| [drama-skills](https://github.com/zenstory-ai/drama-skills) | 漫剧全流程、连续性、图片提示词、视频提示词、审查 | 最适合解决“图有了但每镜不是同一个人”和“参考图用途不清”；明确 H3 首帧/首尾帧/full-reference 的互斥关系 | 生产技能本身不生成媒体；需要把其文档契约映射到 ComicFlow 数据模型 | 优先吸收连续性和参考图语义 |
| [short-drama-production](https://github.com/suihe1/short-drama-production) | MiniMax H3/CompShare 生产总控 | 有 preflight、dry-run、submit、wait、下载、哈希、样片审批和禁止自动付费重试规则 | 更像人工/脚本生产工具包；默认 16:9，与 ComicFlow 默认竖屏方向不同；不能直接替换后端 Adapter | 作为 H3 任务安全和人工审批参考 |
| [character-anchor-skill](https://github.com/xiaoweihu339-afk/character-anchor-skill) | 角色锚点资产库和反馈闭环 | 把稳定身份、可变造型、候选图、批准图、失败图、反馈和质量评分分开；明确四类 golden reference | 默认面向 Codex 图片生成；没有 MiniMax H3 专用提示词方言 | 作为角色资产状态机和质量记录参考 |
| [ai-film-skills](https://github.com/nigo-studio/ai-film-skills) | 角色 Lock Block、Seedance 2.5 视频提示词 | Lock Block 简洁直接；强调参考图角色、服装、空间和摄影机职责分离 | 主要面向 Seedance 2.5；没有 ComicFlow 所需的完整 H3/数据库/任务恢复契约；角色板是三栏，不是完整多视角资产库 | 吸收 Lock Block 和参考图职责写法 |
| [anime-mv-ref2v](https://github.com/SeOgi-Tsu/anime-mv-ref2v) | MiniMax H3 动漫 MV/PV、分镜模式、音频能量 | 题材和 H3 目标贴近动漫视频 | 仓库很小、公开信号少，聚焦 MV/PV，不覆盖角色资产生命周期和漫剧对白生产 | 只作为动漫 H3 提示词补充参考 |

## 重点源码证据

### 1. shuohao-skills：角色设定图最适合借鉴

仓库元数据显示：Apache-2.0，默认分支为 `main`，截至调研日仓库为活跃状态，公开仓库约 3.3k stars、454 forks，未归档，开放 issue 为 0。仓库包含独立的 `novel-characters`、`novel-art`、`novel-storyboard` Skill、参考规则、示例 JSON 和零依赖 selftest。

主要证据：

- [novel-characters/SKILL.md](https://github.com/eternityspring/shuohao-skills/blob/main/skills/novel-characters/SKILL.md) 要求先从原文提取角色，再归并别名、生成角色卡、执行 `validate`，最后才选择性出图。它区分报告语言和图片/TTS 提示词语言，图片提示词固定使用英文，减少模型读中文设定时的歧义。
- [novel-characters/references/schema.md](https://github.com/eternityspring/shuohao-skills/blob/main/skills/novel-characters/references/schema.md) 将角色卡拆成身份、人格、证据、图片和声音字段。图片字段包括 `prompt`、`negativePrompt`、`tags` 和 `sheet`，并要求图像提示词不含角色姓名。
- 同一份 schema 将角色设定图定义为一张 16:9 横向综合图：左约 34% 为半身面部基准，右上为正面/侧面/背面全身视图，右下为 4–5 个细节特写。它特别强调三视图的脸必须跟左栏一致，不能为了塞细节压扁人物比例。
- [novel-characters/references/sheet.md](https://github.com/eternityspring/shuohao-skills/blob/main/skills/novel-characters/references/sheet.md) 明确“一角色一次调用”、先生成候选并由用户挑选，选中的图才作为后续资产基准；生成失败允许单角色重跑，不影响其他角色。
- [novel-storyboard/references/frame.md](https://github.com/eternityspring/shuohao-skills/blob/main/skills/novel-storyboard/references/frame.md) 要求每段分镜图放入独立文件夹，主分镜图固定到 0 秒，子分镜图固定到对应切点；参考图要写清楚用途，而不是让模型猜一张图是角色、场景还是道具。
- [novel-storyboard/references/h3-prompt.md](https://github.com/eternityspring/shuohao-skills/blob/main/skills/novel-storyboard/references/h3-prompt.md) 对 H3 提示词规定对齐指令和切点时间由分镜秒数推导，并将主分镜图作为段落世界观与开场状态锚点。

适合 ComicFlow 吸收的内容是“角色资产板的数据形状和出图门禁”，而不是把它的目录结构或 Codex 图片调用方式直接搬进后端。ComicFlow 当前需要额外保留自己的角色候选图、确认状态、对象存储键和 Provider 协议。

### 2. drama-skills：连续性和 H3 参考模式最完整

仓库元数据显示：MIT，默认分支为 `main`，截至调研日约 1.9k stars、446 forks，未归档，包含 CI、评估样例和多份 JSONL 生产结果。

主要证据：

- [character-consistency-across-shots.md](https://github.com/zenstory-ai/drama-skills/blob/main/docs/character-consistency-across-shots.md) 明确指出三视图只解决“这个人长什么样”，不能单独解决服装、道具、湿度、伤势、空间位置和门窗状态。因此它把一致性分成视觉设定与连续性锁、参考图状态、冻结关键帧和视觉依据三层。
- [short-drama-image-prompts/SKILL.md](https://github.com/zenstory-ai/drama-skills/blob/main/skills/short-drama-image-prompts/SKILL.md) 要求先确定这张图要固定的身份、状态、空间或比较变量，再按“身份锚点 → 当前变体 → 构图/视角 → 光色/材质 → 背景边界 → 禁止项”生成图片提示词，并强调提示词不能把互斥状态平均成一个角色。
- [character-and-look.md](https://github.com/zenstory-ai/drama-skills/blob/main/skills/short-drama-image-prompts/references/character-and-look.md) 将 Character 身份锚点和 Look 可变状态分开；视图数量被定义为按用途选择的选项，不强制所有场景都使用同一套三视图。
- [short-drama-video-prompts/SKILL.md](https://github.com/zenstory-ai/drama-skills/blob/main/skills/short-drama-video-prompts/SKILL.md) 将 `IMG-*`、`PLAN-*`、`REF-*` 区分开：图片提示词或计划图不是实际文件，只有项目中已核对的 `REF-*` 才能进入正式视频参考槽。每张参考图还必须说明顺序、用途、控制范围和不得控制范围。
- [references/minimax-h3.md](https://github.com/zenstory-ai/drama-skills/blob/main/skills/short-drama-video-prompts/references/minimax-h3.md) 给出 H3 模式矩阵：只有起始帧时使用 `first_frame`，起始帧加结束帧时使用 `first_last_frame`，人物/场景图或它们与起始图组合时使用 `reference`。文档还明确 H3 首尾帧输入与 reference 输入互斥，连续段应使用上一段实际视频和从该视频取得的实际尾帧，并把它们作为 full-reference 的不同职责输入。
- 同一 H3 参考文档规定最多 1 张首帧、1 张尾帧、9 张 reference image，时长为 4–15 秒整数。这个限制与 ComicFlow 目前的“首镜最多九张参考图”设计方向一致，但仍必须以当前实际 Provider 契约为准。
- [comic-drama-workflow.md](https://github.com/zenstory-ai/drama-skills/blob/main/docs/comic-drama-workflow.md) 明确实际生产前要经过生产技能预览，并且连续段从第二段起同时绑定上一段实际视频和实际尾帧；没有真实产物时，后续段应标为不可提交，不能拿计划尾帧或文字描述冒充接力输入。

这部分最能解释 ComicFlow 目前“看似传了人物图，实际人物仍漂移”的风险：问题可能不是缺少三视图，而是参考图的职责、当前 Look、镜头起点和上一段视频没有被作为结构化输入一起保存和核对。

### 3. short-drama-production：最适合参考 H3 付费任务安全

仓库元数据显示：Apache-2.0，默认分支为 `main`，截至调研日约 154 stars、21 forks，未归档，开放 issue 为 0。它的重点不是单一图片提示词，而是“生产总控 + H3/CompShare 执行”。

主要证据：

- [references/h3-execution.md](https://github.com/suihe1/short-drama-production/blob/main/references/h3-execution.md) 将 H3 生产分为预检、dry-run、提交、等待和结果回写，明确提交会产生外部状态与费用。
- [references/pipeline.md](https://github.com/suihe1/short-drama-production/blob/main/references/pipeline.md) 要求先生成第一段样片并评审角色、声音、动作、运镜和叙事可读性，再批量生产；已成功创建任务后不因结果不理想自动付费重试，返工前先归因。
- 同一 pipeline 明确要区分官方 MiniMax 与 CompShare 提供方，即使目标模型同名为 MiniMax-H3，也不能混用密钥或任务查询端点。
- 它把 storyboard、frames、video 和 edit 作为版本化产物管理，资产或导演方案变化会使下游产物过期。

这些规则对 ComicFlow 的直接价值主要在任务持久化、恢复查询和生成前预览；不能直接替换 ComicFlow 的 H3 Adapter，因为它的脚本和 `production.json` 是另一套运行时契约，并且默认项目画幅为 16:9。

### 4. character-anchor-skill：角色资产生命周期值得吸收

主要证据：

- [SKILL.md](https://github.com/xiaoweihu339-afk/character-anchor-skill/blob/main/SKILL.md) 把角色一致性定义成长期资产库，而不是一次生成。稳定身份锚点包括脸型、眼型、眉形、鼻梁、嘴型、下颌线、发际线、年龄呈现、身高比例和永久标记；服装、光线、机位、姿势和表情属于可变属性。
- 它要求至少准备并由用户批准四类 golden reference：正面近景、左侧近景、右侧近景和露脸全身图；资产不完整时可以生成，但必须标记为降级并进入候选目录。
- 它把 `raw`、`golden`、`rejected`、`approved`、`candidates`、`failed` 分开，并记录 prompt 版本、参考图类型、质量评分和用户反馈。
- 它特别禁止“最近生成的图”自动成为默认参考图，只有用户明确批准的 golden reference 才能升级为长期身份依据。

它不是 H3 专用 Skill，但这套状态语义非常适合补进 ComicFlow 的角色参考图流程，尤其适合解决用户已反馈的“角色图片生成质量差、后续三视图进一步漂移”的问题。

### 5. ai-film-skills：Lock Block 和参考图职责清晰

主要证据：

- [character-consistency/SKILL.md](https://github.com/nigo-studio/ai-film-skills/blob/main/.claude/skills/character-consistency/SKILL.md) 要求先锁定近景，再用该近景生成一张 16:9 三栏角色板；后续视频提示词重复同一身份块，服装和临时状态作为变体处理。
- [video-prompt-director/SKILL.md](https://github.com/nigo-studio/ai-film-skills/blob/main/.claude/skills/video-prompt-director/SKILL.md) 给每张参考图分配明确角色，并区分身份参考、环境参考、首帧和尾帧；它还要求在 `[Maintain Consistency]` 中写出身份、服装、道具数量、空间方向和摄影机侧别等不可漂移项。

它的 Lock Block 思路适合映射为 ComicFlow 的结构化角色锁，但仓库主要针对 Seedance 2.5，缺少 H3 的参考模式矩阵、任务恢复和数据库状态，因此不适合整体替换。

### 6. anime-mv-ref2v：题材贴近，但证据不足以当主流程

主要证据：

- [仓库 README](https://github.com/SeOgi-Tsu/anime-mv-ref2v) 和 [SKILL.md](https://github.com/SeOgi-Tsu/anime-mv-ref2v/blob/main/SKILL.md) 将目标定位为 MiniMax H3 动漫 MV/PV 的 reference-to-video 提示词工程，包含分镜模式和音频能量分析。
- [references/h3_prompt_patterns.md](https://github.com/SeOgi-Tsu/anime-mv-ref2v/blob/main/references/h3_prompt_patterns.md) 提供动漫 MV/PV 的 H3 提示词模式。

它适合补充动漫化镜头节奏、音乐能量和视觉换挡，但公开仓库规模小、没有角色资产状态机或完整漫剧对白生产证据，不能作为 ComicFlow 角色一致性主方案。

## 与当前 ComicFlow 的对应关系

| ComicFlow 现有能力/风险 | 最有用的外部规则 | 需要注意的兼容点 |
| --- | --- | --- |
| 角色主参考图与三视图 | shuohao 的综合角色设定图；character-anchor 的 golden reference 审批 | ComicFlow 当前三视图是独立视角对象；若改成一张综合图，需保留图片内部视角说明和对象键，不可只替换前端展示 |
| 人物身份在跨镜头漂移 | drama-skills 的身份/Look 分层和连续性锁；ai-film 的 Lock Block | 不能只把角色名和一段自由文本传给 H3；必须把稳定锚点、当前 Look、镜头起点和参考图用途结构化保存 |
| 同场景后续镜头割裂 | drama-skills 的上一段实际视频 + 实际尾帧续接规则 | 需要与 ComicFlow 已有 `CASCADE_FRAME_MISSING` 和后续镜头移除人物/场景参考图的决策保持一致，不能把两种输入模式混用 |
| H3 参考图数量和职责混乱 | drama-skills 的 `reference` 模式与 9 张上限说明 | 必须以当前实际 H3/优云网关契约为最终准据，外部文档不能覆盖项目已验证的 Provider 观察 |
| 生成失败后重复扣费 | short-drama-production 的 preflight/sample/禁止自动重试；character-anchor 的候选与批准状态 | 与 ComicFlow 的任务号立即持久化、恢复查询和幂等回写一起实现；Skill 本身不能代替任务状态存储 |
| 图片效果差但没有可比较记录 | character-anchor 的质量评分和反馈规则；shuohao 的候选选择与 validate | 需把图片候选、批准、拒绝原因、提示词版本和参考图版本写入 PostgreSQL/对象存储元数据 |

## 筛选结论和推荐顺序

### 第一优先级：吸收 drama-skills 的连续性契约

这是对当前质量问题最直接的规则来源。先确认每个镜头是否有：

- 本镜真正可见的角色、场景和道具清单；
- 每张参考图的用途、控制范围和不得控制范围；
- 当前角色的稳定身份锚点与可变 Look；
- 可验证的起点、唯一动作和终点；
- 连续镜头的上一段实际视频与实际尾帧；
- 与 H3 模式互斥关系一致的请求载荷。

### 第二优先级：吸收 shuohao 的角色资产板与离线校验

ComicFlow 应优先把角色第一次出图改进为“一个候选角色资产板”，而不是先让一张普通头像成为永久参考，再无条件派生多个视角。资产板应有面部基准、视角、全身比例、服装和细节区域，并由用户批准后才进入正式角色参考资产。

是否在一张图中放三视图，取决于图片模型对版面控制和后续视频模型对多视角信息的利用情况。外部 Skill 只能证明这是一种常用工作流，不能证明当前 image-2.5 或 MiniMax H3 一定能正确解析；实际接入仍需用不付费的请求构造、对象键和 manifest 校验先验证。

### 第三优先级：吸收 character-anchor 的资产状态和反馈闭环

这会降低后续生成的无效调用：未批准的候选图不能被后续镜头引用；生成失败的视角不能覆盖已经批准的视角；用户说“眼睛、发型或身材不对”时，反馈要变成下一次提示词的修正规则。

### 第四优先级：吸收 short-drama-production 的 H3 生产门禁

它适合补强当前已经暴露的 504/任务号丢失问题：提交前展示精确请求，提交后立即记录任务号，超时进入待恢复状态，恢复只查询和下载，不能自动再次提交。

## 不建议直接采用的方案

- 不建议把任意一个仓库的完整目录或 SKILL.md 原样替换 ComicFlow。各仓库的语言、画幅、模型、文件结构和生产工具不同。
- 不建议只增加“更详细的英文提示词”。外部规则普遍强调身份、服装、道具、空间和起止状态的结构化绑定；提示词变长不能替代正确参考图和连续帧。
- 不建议把三视图数量当作一致性的唯一指标。三视图解决空间身份信息，Look、状态、参考图用途、连续镜头尾帧和用户批准状态同样决定结果。
- 不建议在没有真实媒体和供应商任务记录时宣称效果已验证。本次调研没有调用任何图片或视频模型，也没有对仓库示例执行付费生成评测。

## 可供后续实现的最小规则集合

若后续决定继续完善 ComicFlow，建议只从以下规则开始，避免一次引入整套外部生产系统：

1. 角色资产：`candidate`、`approved`、`rejected` 三态；approved 才能作为 H3 reference。
2. 角色锁：稳定身份字段和当前 Look 字段分离，生成提示词时由编译器合并。
3. 图片 manifest：每张图保存顺序、用途、控制范围、不得控制范围和对象键。
4. 综合角色板：支持一张 16:9 角色资产板，面部基准与正/侧/背全身视图同图；仍保留单视角对象字段以兼容已有数据。
5. H3 镜头：生成前离线检查模式、参考图数量、镜头时长、起点/终点和连续镜头输入；检查失败不调用 Provider。
6. H3 任务：提交成功立即持久化任务号；轮询超时返回 `pending_recovery`；恢复操作不重新提交。
7. 质量反馈：记录用户对脸型、发型、体态、服装、画风和参考对齐的评分，下一次编译提示词时只应用已批准的修正规则。

这些规则与 ComicFlow 当前工程规约中的“Mock 优先、Provider 契约校验、PostgreSQL 保存正式状态、禁止重复付费生成”一致，不要求引入新的模型或新的编排平台。

