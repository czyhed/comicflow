# iToVideo 逆向：提示词、风格、分镜与媒体合成

日期：2026-10-13。结论基于本地源码静态核查，未启动服务、未调用模型、未读取业务环境或密钥。这里的“可直接搬”指实现依赖少、可在保留 ComicFlow 契约的前提下提取；不等于已完成集成或许可核验。

已读取 ComicFlow 的工程规约、CONTEXT、ADR 0002/0003/0004/0006、提示词收尾记录、质量与模块任务书、原声合成规格、2026-10-09 接续裁剪与选中镜头合成契约。原工程规则、Provider Adapter、持久作业、人工采用及准确对白约束仍作为对照基线。

## 结论先行

iToVideo 最值得搬的并不是“更多 Skill 文件”，而是若干完整、确定性的媒体处理办法：**真实尾帧提取、接缝重叠计算、逐行字幕位置与 ASS 特效、语音压低 BGM 的 filtergraph**。其中尾帧提取发现了 ComicFlow 自身一个值得单独验证的明确实现差异：当前代码取倒数一秒处的首个帧，iToVideo 则继续解码到 EOF，或反转末秒取真正最后一帧。

ComicFlow 已经有按用途加载 Skill、来源 SHA-256、项目风格快照、H3 首尾帧互斥、原声保留、同步裁剪和局部试片。不能把 iToVideo 相同能力当成 ComicFlow 全部欠缺。iToVideo 在广告创作和画布媒介加工上的范围更广，但当前一键成片是 **24 秒商品广告固定三段模板**，不是通用长漫剧或上传参考影片分析。需要分别看真实入口，不能凭目录或页面标题推断。

## 1. 实际运行的提示词与 Skill

### 1.1 候选目录里既有已接入的，也有只存着的

画布的 `see_and_write` 结构化文本入口实际执行：观察图片 → 保存分析 checkpoint → 按用户选择/分析推荐路由 Skill → 把已摘录规则放进 writer system → 一次写作 → 本地解析结果。

- 四个候选 Skill **确实运行时加载**：`seedance-tvc-director`、`ai-ad-prompt-guide`、`seedance-video-prompt`、`ai-video-storyboard`。白名单与目录映射见 [prompt_skills.py:14](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/prompt_skills.py:14)、[prompt_skills.py:146](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/prompt_skills.py:146)，真正调用点见 [text.py:191](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/text.py:191)。
- 项目内 `product-ad-storyboard` 是另一项可选项。[prompt_skills.py:148](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/prompt_skills.py:148)
- `cinematic-video-prompt-engineer` 不在白名单。现有测试明确要求直接读取它时报错，自动路由推荐它时改走允许项。[test_prompt_skills.py:87](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/tests/test_prompt_skills.py:87)
- 路由遵循“手动优先 → 白名单内模型推荐 → 简报关键词”，不是所有 Skill 同时塞进模型，也没有独立 Skill 执行服务。[prompt_skills.py:120](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/prompt_skills.py:120)
- 文档按明确标题摘录，保留围栏代码里的标题为数据，缺失章节直接拒绝；引用按用户简报选择。[prompt_skills.py:92](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/prompt_skills.py:92)、[prompt_skills.py:170](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/prompt_skills.py:170)
- writer 明确覆盖外部 Skill 的交互流程和输出格式，不执行其中评分、修稿、联网、工具调用；去除 Seedance 特定语法，并按本项目 JSON 交付。[text.py:197](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/text.py:197)

**可借鉴的增量**：把完整规则按用途挑选至明确章节，显示所选来源路径/章节；在现有 ComicFlow loader 上扩展，避免重新建立 Skill 平台。

**ComicFlow 已有的部分**：`load_stage_skill()` 已只读一个用途引用文件，并写执行文件和哈希；H3 同样按请求读取指南并记录哈希。[drama_skills.py:37](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/providers/drama_skills.py:37)、[h3_skill.py:244](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/providers/h3_skill.py:244)、[h3_skill.py:337](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/providers/h3_skill.py:337)

**不宜整包复制**：iToVideo writer 定位商品广告，自动关键词路由把缺省落到广告方法；漫剧需要多角色对白、原故事事实和现有 JSON 校验。整包规则中的广告钩子、packshot、落版、品牌口播会污染剧本；可以提炼动作受力链、完成态、情绪留白、运镜词汇，但不能新增固定广告节奏或覆盖用户台词。[prompt_skills.py:135](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/prompt_skills.py:135)、[prompt_skills.py:61](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/prompt_skills.py:61)

### 1.2 两段式观察/写作比再加一轮“AI 导演审核”更实际

画布可把商品多模态观察结果在 writer 前持久保存，writer 失败后复用观察，降低重复调用；普通写作不自动追加修复模型请求。解析失败则返回原文和空分镜，页面由结果告知不是可展示 JSON。[text.py:171](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/text.py:171)、[text.py:182](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/text.py:182)、[text.py:237](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/text.py:237)

这是可以借鉴的阶段输入复用设计，但 ComicFlow 若新增“观察参考角色/场景图”，需另定义观察资产版本和人工采用方式，不能把识别推测写回角色卡。当前 comicflow 已禁止为了解析失败额外修复请求，故“一次写作”不是缺口。

### 1.3 适合直接抽取的小工具

`fill_prompt()` 单次替换命名占位符，用户值里的花括号不会被二次当成模板指令，代码只有标准库依赖。[prompts/__init__.py:18](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/prompts/__init__.py:18)

`_select_sections()` 适合外部大型规则库的白名单摘录，不过这里只选择标题所在叶子区块，不能直接当通用“连同所有子章节” Markdown 解析器；复制时保持标题校验、围栏处理和明确文档版本。ComicFlow 已有用途拆分，只有确实引入大参考文件时才需要这个工具。[prompt_skills.py:92](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/prompt_skills.py:92)

不建议直接替换 ComicFlow 的 JSON 解析器：iToVideo 的 `extract_json()` 会尝试补外层括号、扫描多个对象并挑“最像完整稿”的对象；失败消息带原文前 200 字。这种宽松修补和原文错误输出必须按 ComicFlow 的拒绝/脱敏约束重新评估。[prompts.py:105](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/prompts.py:105)、[prompts.py:134](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/prompts.py:134)

## 2. 创作配方与风格：有价值的数据结构，但入口不能混淆

iToVideo 配方不仅描述画风，还记录镜头用途、视频方向、衔接、适用条件、替代方式，以及声音、后期和人工验收项目。比如武侠 `bamboo` 明确“手和兵器实际可见才做动作，遮挡时用肩部动作替代”，这是比“电影感、高清、8K”更可执行的输入条件。[bamboo.json:17](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/data/recipes/bamboo.json:17)、[bamboo.json:70](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/data/recipes/bamboo.json:70)

内置目录对 JSON → Pydantic → 镜头索引做启动期一致性校验，只允许固定的五个内置 ID。风格 Schema 可存品类适配、参考范例、模型/provider、声音开关、Context-IR 开关和 `user_validated/draft` 状态。[creative_recipes.py:13](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/data/creative_recipes.py:13)、[recipe_style.py:12](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/schemas/recipe_style.py:12)、[recipe_style.py:41](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/schemas/recipe_style.py:41)

这对 ComicFlow 的实际增量是：在已有风格快照上补“适用于什么画面”“画面能否支持动作”“真实示例与草稿分开”。ComicFlow 本身已做到项目快照冻结、按角色/场景/视频用途编译、保留原故事和人物事实，无需推倒重建。[visual_styles.py:110](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/production/visual_styles.py:110)、[visual_styles.py:119](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/production/visual_styles.py:119)、[visual_styles.py:156](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/production/visual_styles.py:156)

### 真实入口的两种情况

1. **画布看图写剧本：风格已接入写作**。`text.py` 将 `recipeId` 解析成 context，再用 `canvas_recipe_prompt()` 替换 writer system。`generation_recipe()` 若有完整 `sourcePrompt`，只传这一底稿和必要字段，避免新旧规则叠加。[text.py:65](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/text.py:65)、[foundation.py:14](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/foundation.py:14)
2. **当前 Studio 默认固定模板：所选 recipe 写作输入未接通**。`reference_film.py` 将 `recipeSnapshot` 保存并置于 `plan_params`，但 `author_creative()` 构造模型 request 时只取商品事实、creative、settings、timing；`writing_brief()` 也没有 recipe 字段。视频 globalStyle 则来自固定 `template.global`，通过 `_prompt()` 与每段正文拼接。因此这一入口确实有模板风格，但不能证明用户所选配方被应用到写作或视频模板。[reference_film.py:128](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/reference_film.py:128)、[reference_film.py:265](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/reference_film.py:265)、[creative_authoring.py:62](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/creative_authoring.py:62)、[creative_model.py:29](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/creative_model.py:29)、[product_template.py:153](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/product_template.py:153)、[product_template.py:232](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/product_template.py:232)、[reference_film.py:79](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/reference_film.py:79)

这是对当前源码调用链的结论，不能外推成“项目所有风格都无效”。旧已准备剧本、用户编辑正文、上游把风格文字直接放进 brief 等路径也可能自带风格。

另一个不能搬的细节：`public_snapshot()` 对内置配方 ID 回读时使用当前内置公开文案替换 snapshot 的 content/production；ComicFlow 的历史冻结风格必须保持当时版本，不能沿用此展示替换逻辑。[recipe_catalog.py:92](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/data/recipe_catalog.py:92)

`bamboo` 仍使用固定 20/60/20 微动作比例，且 `validation` 明确为 `unverified`，不应当成真实质量已验收。ComicFlow 2026-09-22 收尾已主动移除固定比例覆盖原稿的做法，搬规则时要保留目前决定。[bamboo.json:23](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/data/recipes/bamboo.json:23)、[bamboo.json:72](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/data/recipes/bamboo.json:72)、[prompt-closeout-2026-09-22.md](C:/Users/lmk/Documents/ChatGPT/comicflow/docs/implementation/prompt-closeout-2026-09-22.md)

## 3. “参考影片分析”与一键成片的真实能力

当前注册的 `StudioFilmExecutor` 来自 `assisted/reference_film.py`，名字不能作为功能证据。源码实际接收一张商品主图和最多四张补充参考**图片**；stage_models 只选择图片观察 vision 和文字 writer，二者必须独立配置。它没有读取上传参考影片并解析其镜头节奏的分析步骤。[registry.py:19](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/registry.py:19)、[reference_film.py:194](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/reference_film.py:194)、[reference_model.py:11](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/reference_model.py:11)

准备阶段做一次商品识别，一次中段写作；三段骨架为外观 8 秒、卖点 6 秒、完整亮相 10 秒，前后段原文来自固定模板，结尾固定“未来，触手可及”。恢复优先使用已存观察与草稿；render 只消费已经准备的稿，不重写。[creative_model.py:1](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/creative_model.py:1)、[creative_authoring.py:51](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/creative_authoring.py:51)、[product_template.py:18](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/product_template.py:18)、[product_template.py:41](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/product_template.py:41)、[reference_film.py:266](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/reference_film.py:266)

适合借鉴的是**把可查看稿的准备与付费视频渲染分开、只改尚未付费段落、实际提交 Prompt 保留**；不适合搬的是固定商品短片结构。ComicFlow 需要完整中文剧本、多人关系、准确对白与独立镜头采用，不该改成电子产品广告模板。[reference_film.py:289](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/reference_film.py:289)

视频 Provider 支持 `reference_video` 作为参考视频输入，属于供应商生成输入能力，不能等同于应用做了参考影片镜头解析。[video.py:25](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/providers/video.py:25)

## 4. 首尾帧连续性：最应优先拿来验证的具体差异

### 4.1 ComicFlow 当前“最后一帧”实现并非真正 EOF 尾帧

ComicFlow `_extract_last_frame()` 运行 `ffmpeg -sseof -1 -i video -frames:v 1`。它定位结尾前一秒，再只输出此后的第一帧；对正常多帧视频，这与实际最后帧不同。[frame_extractor.py:30](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/utils/frame_extractor.py:30)

iToVideo 的画布 `extract_frame(at=None)` 使用 `-sseof -1` 后继续处理全部剩余帧，以 `-update 1 -fps_mode passthrough` 覆盖同一输出文件，最终保留 EOF 前最后解码帧。[ffmpeg.py:829](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:829)

Studio 的检查用 `-sseof -1 -vf reverse -frames:v 1`，反转最后一秒后取第一帧，也能拿到最后解码帧。模块注释有旧“画布采样末尾前 0.2 秒”的说法，但当前画布代码已经解到 EOF，应以实际代码为准。[video_check.py:71](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/video_check.py:71)

**建议最小移植**：保留 ComicFlow async/临时文件/JPEG 和源对象键隔离，只改变尾帧选择命令。在离线人工合成视频里把倒数一秒与真正末帧设为不同颜色，验证当前失败、移植后成功；再检查小于一秒、变帧率与损坏视频。不要自动重新生成现有镜头，也不要回写已有历史尾帧。

这是明确源码差异，尚未通过实际媒体复现；**不能据此断言用户现有作品停顿或跳变就是它导致**。严格首帧是静态姿态，仍不能保证速度和动作状态完全连续。

### 4.2 连续性策略本身不应整搬

iToVideo Studio 第一个视频使用用户商品原图，后续所有视频用上一段实际尾帧，换环境也保持这条链。适合产品稳定身份，但不能照搬到多人、多场景漫剧。[reference_film.py:30](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/reference_film.py:30)

ComicFlow 已支持 `previous-tail` 严格模式、场景/角色参考模式和互斥检查；源视频哈希隔离帧键也已存在。[video_preparation.py:146](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/production/video_preparation.py:146)、[video_preparation.py:266](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/production/video_preparation.py:266)、[video_frames.py:50](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/production/video_frames.py:50)

尤其不要搬 `harmonize_roles()`：它遇首尾锚定帧与参考图混用，会自动把锚定帧降级成普通 reference。这是改变用户首帧语义的行为，ComicFlow 严格模式应继续拒绝冲突。[shot.py:95](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/shot.py:95)

### 4.3 技术质量检查有独立价值

Studio 不仅 ffprobe，还完整解码视频检查损坏；对基础设施缺失/资源超时和确定视频不合格使用不同错误，前者只重跑检查，后者保留拒绝视频。当前仅验证可读流、实际画幅、尾帧，并不识别人物一致性/动作完成/台词准确，也不要求实际分辨率等于请求档位。[video_check.py:35](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/video_check.py:35)、[video_check.py:65](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/video_check.py:65)、[video_check.py:119](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/assisted/video_check.py:119)

可以将“ffprobe 元数据 + 完整解码 + 明确技术验证状态”引入 ComicFlow 候选视频验收；保留人工采用，不引入 AI 打分或自动付费重生成。

## 5. 多图生成：功能更广，不能直接搬默认调度

iToVideo 套图允许 1–12 张候选和最多 12 参考图，区分输入九宫格与输出九宫格；协议决定取参考图 bytes 或 URL，产物按真实 magic bytes 识别 PNG/JPEG/WebP/GIF。[image_set.py:16](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/image_set.py:16)、[image_set.py:28](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/image_set.py:28)、[image_set.py:56](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/image_set.py:56)、[image_set.py:196](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/image_set.py:196)

`generate_images()` 先按候选数请求，少了就默认并发追加单图请求，上限 6；默认会对 429/5xx 重试。`safe_submission` 关闭 5xx 重试及补图，但 429 仍退避重试。并发结果部分失败会被跳过，回调只记录最初 probe 请求。[image.py:306](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/providers/image.py:306)、[image.py:368](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/providers/image.py:368)、[image.py:385](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/providers/image.py:385)

**不可直接搬整个函数**：这会把“要 9 张”隐式扩大成多次付费调用，未知提交/部分结果也缺少 ComicFlow 的每次生成作业与额度记录。移植需用户明确数目、按 Provider 能力规划调用数、每张结果及时独立持久保存、每次请求有可追踪状态，失败不能把已完成图丢掉。

套图参考 IDs 用切片 `[:MAX_REFS]`，超过上限的输入会被静默忽略；第一张候选自动 selected。这也不符合 ComicFlow 明确候选采用和超限拒绝的约束。[image_set.py:63](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/image_set.py:63)、[image_set.py:162](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/image_set.py:162)

## 6. FFmpeg：最大的可复用模块，但要挑函数与修入口

ComicFlow 当前真实视频合成以每镜同步 trim、规格归一和硬切拼接为主；原声优先、无对白的无声镜头允许静音，输出 MP4/封面/SRT。[video_composition.py:21](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/providers/video_composition.py:21)、[video_composition.py:109](C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/providers/video_composition.py:109)

### 6.1 接缝计算和混合转场：可以提取，保留显式输入

iToVideo 明确 N 段只有 N−1 个接缝，`transition` 表示该段后面的接缝；重叠时长受相邻短片段一半及全局 2 秒约束，记录 requested/applied/clamped；总时长为片长之和减 overlap。[ffmpeg.py:221](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:221)、[ffmpeg.py:242](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:242)、[ffmpeg.py:290](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:290)

`plan_join()` 把连续硬切组分开，组内 concat，组间 xfade，降低大混合滤镜复杂度；合成槽位和字幕都扣掉前面接缝重叠，原声按同一区间裁剪、定位和淡化。[ffmpeg.py:271](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:271)、[ffmpeg.py:350](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:350)、[compose.py:109](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/compose.py:109)、[compose.py:260](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/compose.py:260)

可以直接复用 `plan_join`、`seam_seconds` 的算法，adapt `build_seams`/`clamp_transition_seconds` 的 typed 输入/有限数检查。**不能照搬缺省 unknown→dissolve**：源码把空缺/未知转场默认叠化，应改为显式选择或拒绝未知值，并默认保持 ComicFlow 原硬切。[ffmpeg.py:204](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:204)

### 6.2 字幕位置、预览一致性与特效：独立移植价值高

可复用 `subtitle_anchor()` 的归一化文字块中心坐标；`subtitle_effect_tags()` 生成 libass 标签，含淡入、上浮、滑入、缩放、虚焦；`write_ass_positioned()` 生成逐行位置 ASS，明确 PlayRes 等于实际输出分辨率，避免 preview 与渲染缩放不同。[ffmpeg.py:898](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:898)、[ffmpeg.py:933](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:933)、[ffmpeg.py:966](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:966)

适配需前端同样定义中心锚点、毫秒特效常量、实际画幅；服务端严格验证坐标/时间/字体。原台词逐字保留，ASS 文本转义要单独验证花括号和反斜线。输出可选烧录或软字幕，软字幕用 mov_text；产物时长显式按画面 `-t`，避免短字幕/短语音截断视频。[ffmpeg.py:574](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:574)

这些改变字幕可读性和可编辑性，**不会自动使字幕逐字对齐语音**。Compose 当前依然按镜头槽位选 subtitle/narration，并非语音识别对齐；若片段重排或局部选择，直接按 shots[index] 关联还需改成稳定 shot ID。[compose.py:293](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/compose.py:293)

### 6.3 混音与 BGM 自动压低：算法好，但当前 Compose 接口有缺口

`audio_mix_filters()` 将 voice/BGM 分组，voice `asplit` 一路混音一路作为 sidechaincompress 触发，触发路用 apad 防止配音结束后背景音乐提前中止；最后混音也 apad，渲染由视频时长封顶。[ffmpeg.py:651](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:651)

可借用此 filtergraph 原理，但不能宣称一键成片/Compose 已完整享有自动 ducking：Compose 读取附加音轨 role 后只把 `(path, weight)` 传给 render，`_audio_track_spec()` 把所有 tuple 默认当 voice，所以此入口丢掉 BGM/SFX role。原视频 track 使用 `role=original`，也不属于 voice sidechain trigger。[compose.py:135](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/compose.py:135)、[compose.py:148](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/compose.py:148)、[ffmpeg.py:724](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:724)、[ffmpeg.py:669](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:669)

ComicFlow 使用 H3 混合原声时不能凭空分离对白和环境音；如选整段原声作为压低触发，会连环境声一起触发，需要用户理解选项。独立配音可明确 role。还应检查多轨峰值，因为 iToVideo `amix normalize=0` 没有 limiter；不能承诺响度合规。

不要搬 `_audio_track_spec()` 的裁空→当作没裁，也不要搬超长配音自动 1.35x 加速/截断的默认策略。这会改变用户语音内容和裁剪意图，ComicFlow 当前明确超界拒绝，应继续按原行为。[ffmpeg.py:744](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:744)、[ffmpeg.py:749](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:749)

Compose 接口接受 output.bitrate，但 render 没有 bitrate 参数、最终固定 CRF23；它只保存 bitrate 字符串到元数据，不能把该控件视为已真正作用于输出。[compose.py:169](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/compose.py:169)、[compose.py:216](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/executors/compose.py:216)、[ffmpeg.py:641](C:/Users/lmk/Documents/ChatGPT/iToVideo/iToVideo/iToVideo_service/app/services/media/ffmpeg.py:641)

## 7. 建议搬运顺序与最小验收

| 顺序 | 模块/办法 | 搬运程度 | ComicFlow 必要适配 | 最小离线验收 |
| --- | --- | --- | --- | --- |
| 1 | 真正尾帧提取 | 可搬命令选择方式 | 保留 JPEG、async、源键隔离及历史不回写 | 最后 1 秒异色视频、短片、损坏片；输出与实际 EOF 比较 |
| 2 | ASS 字幕坐标与特效 | 大部分纯函数可复用 | 新的可选输出参数、前端中心锚点、字体/转义验证 | 9:16 字幕预览与烧录位置一致；台词与时长保持 |
| 3 | 接缝重叠与 plan_join | 计算函数可复用 | 可选转场、硬切默认、稳定镜头 ID、统一 overlap 时间轴 | cut/dissolve 混合、短镜、字幕/原声对齐、源视频不改 |
| 4 | sidechain 混音图 | 算法可复用 | typed role 保留、H3 原声触发显式选择、峰值检查 | 短语音长 BGM 不截尾；不同 role 听感/音量正确 |
| 5 | Skill 白名单章节摘录 | 可提取标准库 helper | 沿用现有 loader/hash/JSON；仅增真实所需章节 | 不读白名单外文件、围栏标题正确、来源哈希可追溯 |
| 6 | 风格适用条件/验收范例 | 借数据结构与内容方法 | 复用已有项目快照；不搬广告时长/事实兜底 | 老风格快照不漂移、人物原事实不变、草稿不冒充验收 |
| 后置 | 多图候选批次 | 重写调度集成 | 明确次数/成本、每次持久状态、逐张保留、用户采用 | 部分失败/未知提交不重发、不吞成功结果 |
| 不建议 | 完整 Studio 固定模板 | 不搬 | 商品广告与通用漫剧不匹配 | 无 |

文档未修改业务代码、配置或数据。以上均是迁移候选与静态审计；真实模型画质、成本、字幕视觉效果、FFmpeg 版本兼容和许可证，不能用源码存在来宣称已验收。

## 8. 尾帧差异的本地离线证据

主任务随后用同一份约 2 秒测试视频做了离线对照（0–1.7 秒红色，1.7–2.0 秒蓝色），没有启动业务服务、没有调用模型、没有修改业务源码。ComicFlow 当前 `FrameExtractor._extract_last_frame()` 结果像素为红色 `[254, 0, 0]`；iToVideo 的 `-sseof -1` + `-update 1` + `-fps_mode passthrough` 结果为蓝色 `[0, 0, 254]`。证据目录为 [result.json](C:/Users/lmk/Documents/ChatGPT/comicflow/output/research/itovideo-tailframe-2026-10-13/result.json)（及同目录测试视频/两张帧图）。

这把“源码看起来有差异”提升为可复现的实现差异。最高价值候选是只替换尾帧抽取策略，并保留 ComicFlow 的对象键隔离、作业版本和历史媒体不回写；仍不能根据此单点差异断言既有漫剧的停顿或跳变根因，必须由用户观片和独立样例继续验证。
