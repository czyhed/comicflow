# CompShare MiniMax-H3 提示词语言：一手资料核查

核查日期：2026-09-16。范围：CompShare 官方 H3 文档、MiniMax-AI/MiniMax-H3 上游 GitHub 文档与 Skill、ComicFlow 本地规则及实现，以及用户提供的仙宫云页面与其链接的新版说明。主代理与研究子代理分工核查；唯一新增文件为本笔记。没有请求密钥、读取凭据、调用生成/账户接口、改变配置或代码，没有部署镜像或下载替换 Skill。

## 结论

**按 CompShare 官方文档，MiniMax-H3 接口支持以中文描述作为输入；“描述章节必须英文”是上游提示词扩写 Skill 的输出规则，并被 ComicFlow 实现为提交前的硬校验，不能等同于 CompShare API 只接收英文。**

需要保留一个关键限定：CompShare 的完整中文文生视频、首帧生视频示例均显式设置 `use_context_ir: true`。官方同时说明该字段默认 `false`，省略时直接使用原始提示词。本地适配器当前没有发送这个字段。因此，“接口有官方中文输入示例”证据充分；“现有本地流程不变即可发送中文描述”“关闭优化后中文与英文质量等价”均没有得到证明。

| 问题 | 结论与证据强度 |
| --- | --- |
| CompShare H3 是否允许中文描述输入？ | 文档支持，高置信度：请求参数表及完整请求示例都直接使用中文描述。[S1] |
| 是否有 API 必须英文的声明？ | 在本次读取的 H3 请求参数及示例中未发现；不能把 Skill 输出规则推断为 API 拒绝中文的规则。[S1][S2] |
| 上游 Skill 是否明确要求英文？ | 是。不是仅根据英文例子猜测，而是明确的 Output Rules；Ref2VA 指南再次明确要求六个章节英文。[S2][S3] |
| 当前项目为何拒绝中文描述？ | 项目采用同一 Skill，并在 `h3_skill.py` 中以 `language` 原因拒绝含中文正文的章节，发生在视频提交之前。[L1][L2][L3] |
| 不用 Context-IR 的中文实际质量如何？ | 未验证。文档说明原始提示词可以直接进入生成，但本次没有做付费实测，也没有中英文对照质量证据。[S1] |
| 中文对白是否证明中文描述能力？ | 不能单凭对白能力推断。上游 README 的 11 语言支持明确说的是 dialogue languages。[S5] |
| Hailuo 2.3 文档能否证明 H3 行为？ | 不能。模型、地址、字段和优化开关均不同。[S6] |

## 1. CompShare H3：中文输入与可选优化

来源：[MiniMax H3 视频任务 API][S1]，本次公开 GET 返回 HTTP 200。以下引文来自页面实际内容；表格单元之间的排版换行已合并，文字未翻译。

接口地址为：

```text
POST https://cp.compshare.cn/minimax/v2/video_generation
```

请求参数 `content` 的示例值是：

```json
[{"type":"text","text":"一只猫在海边奔跑"}]
```

`content` 元素的 `text` 说明：

> type=text 时填写。纯文生视频必须包含非空文本；所有文本合并后最多 7000 个字符

完整“文生视频示例”的关键原文：

```json
"model": "MiniMax-H3",
"text": "一只橘猫戴着墨镜，在海边驾驶红色跑车，阳光明媚，电影质感，镜头缓慢向前推进"
```

该示例同时包含：

```json
"use_context_ir": true
```

“首帧生视频示例”也直接使用中文描述：

```json
"text": "人物缓慢转头看向镜头，背景中的树叶随风摆动"
```

同样设置 `"use_context_ir": true`，图片 `role` 是 `"first_frame"`。这些是主体、动作、环境、运镜的描述，不是对白或画面中的汉字，因此直接回答了本次“中文描述”问题。

优化开关的参数说明：

> 是否启用 Context-IR 提示词优化，默认 false；只有显式传入 true 才会启用

补充说明：

> use_context_ir 省略时按 false 处理，系统会直接使用原始提示词生成视频。如需启用 Context-IR 提示词优化，创建请求必须显式包含 "use_context_ir": true；启用后，系统会先优化提示词，再进入视频生成阶段。

平台 Skill 的语义：

> Skill 用于保存可复用的镜头语言、叙事规则和提示词优化规范。Skill 不会单独生成视频；创建任务时传入 skill_id，并显式设置 use_context_ir=true 后，平台会在 Context-IR 阶段应用对应 Skill。

**解释边界：**参数表与原始提示词说明支持“页面未限制输入语言”的判断；完整中文示例直接证明的是官方推荐使用方式包含中文输入并开启优化。页面没有展示优化后的文本，也没有在上述段落保证它一定转为英文，不能替平台推断内部实现。没有实际中文请求的成功响应或视频质量验收。

## 2. MiniMax-AI 上游：明确的英文扩写输出规则

核查仓库：[MiniMax-AI/MiniMax-H3](https://github.com/MiniMax-AI/MiniMax-H3)。为使引文可复查，以下链接固定到本次 `main` 树对应的提交 `d21241f0a4b3acbb34c97dae47fa417b7065e438`，不把未来 `main` 的变化混入结论。

[上游 `skills/h3-prompt-writing/SKILL.md` 第 33 行][S2]：

> Write rewrite sections in English; preserve dialogue, lyrics, and visible scene text in their original language.

含义是**扩写后的章节用英文**，对白、歌词和画面可见文字保留原语言。它不等于用户最初只能用英文提出需求，也不是 CompShare 请求 schema 的语言限制。

[上游 `ref-en.txt` 第 5 行][S3]：

> Write all six rewrite sections in English. Preserve the original language only for dialogue and lyrics inside `<d>` and for text visibly present in the scene.

同文件第 217 行：

> Write the body in English. Preserve the original language of dialogue, lyrics, and visible text.

[上游 `base-en.txt` 第 154 行][S4]，声音环境章节的原文首句：

> Use 1–4 English sentences in one continuous paragraph to summarize the ambient sound, physical action sounds, and non-verbal human sounds across the full video, such as wind, rain, traffic, footsteps, fabric movement, impacts, breathing, laughter, or panting.

第 162 行，配乐章节的原文首句：

> Use 1–3 English sentences to describe background music that the characters cannot hear and only the audience can hear.

因此不能把英文要求弱化为“只是例子恰好用英文”。它是选择这套 Skill 后必须遵循的输出契约；但从 API 能力层面说，这套扩写/预处理方式仍区别于接口的输入接收能力。

[README 第 90 行][S5] 对预处理的推荐原文：

> H3-Context-IR is critical to the quality of the final output, so we strongly recommend incorporating it into your generation pipeline or following the “Prompting Guidance” to build your own context-processing system.

README 将 Context-IR 描述为理解和精炼多模态输入、转换为 H3 易于理解的中间表示。这支持“采用预处理有质量上的理由”，不构成“中文请求在 API 层非法”或“英文必然优于中文”的对照实验。

README 第 78 行的语言能力描述：

> Stable support for 11 languages: Arabic, Chinese, English, French, German, Italian, Japanese, Korean, Portuguese, Russian, and Spanish. Additional languages are also supported to varying degrees

该表行标题是 **Supported dialogue languages**。中文 README 对应表行标题是“支持的对话语言”，正文为：

> 稳定支持 11 种语言：阿拉伯语、中文、英语、法语、德语、意大利语、日语、韩语、葡萄牙语、俄语和西班牙语。其他语言也有不同程度的支持

这是对白能力，不能用它单独证明描述正文语言支持。

## 3. 本地为何比 API 输入要求更严格

本次读取了工程规约、`CONTEXT.md`、ADR 0003/0006、当前创建阶段计划与规格、H3 实施文档和 `.scratch/h3-validation/spec.md`。ADR 0006 仍记载最初 Wan 候选策略；工程规约 2026-09-09 后续决策明确将本阶段视频改为 CompShare H3。这里依据后续 H3 决策与当前源码判断，不把旧候选当作当前端点。

- [本地 Skill 第 33 行][L1] 与上游同句。逐文件读取比较后，`SKILL.md`、`references/base-en.txt`、`references/ref-en.txt` 三份本地内容与上述上游提交一致（仅归一化 CRLF/LF 后比较）。
- [工程规约][L2] 2026-09-09 决策：“中文可编辑剧本与 H3 视频 Prompt 分离。”并要求每次 H3 生成执行本地 Skill；2026-09-10 决策规定“表外中文一律保持原样并拒绝，不翻译、不猜测、不删除半个句子”。这是项目策略。
- [校验代码][L3] 第 370 行起：

```python
for key in sections:
    if contains_chinese_prose(values[key]):
        raise H3PromptValidationError('language', section=key)
```

- [语言检测][L4] 第 113 行使用 `HAN.search(PROTECTED_TEXT.sub('', text))`，在排除受保护文本后检测汉字。中文对白由应用通过 `<d>[Chinese] ...</d>` 注入，和中文描述正文不同。
- [视频适配器][L5] 默认地址是 `https://cp.compshare.cn`、模型 `MiniMax-H3`、提交路径 `/minimax/v2/video_generation`。`generate()` 先等待 `_prompt_writer.write()`，成功后才构建载荷并执行 `client.post()`，所以 `language` 错误是本地提交前拒绝，不是 H3 服务端返回的语言错误。
- 同一适配器 `_build_request()` 将 `shot['h3Prompt']` 放进 `content[0].text`，目前只构造模型、内容、时长、分辨率、比例及参考素材；没有 `use_context_ir` 或 `skill_id`。按当前官方文档，这对应平台不启用 Context-IR；本地文本 Adapter 承担 Skill 扩写。**CompShare 平台 Skill 与仓库 Markdown Skill 是两个不同机制。**

本次没有读取当前运行时配置或用户账户。因此上述端点对应用户指定端点及仓库当前实现，不另行宣称已确认部署进程使用的实时配置。

## 4. Hailuo 2.3 是另一套 API

只为确认边界，读取了同一 CompShare 官方站点的 [MiniMax/Hailuo-2.3-T2V 页面][S6]，HTTP 200。该页面列出：

| 项目 | H3 页面 | Hailuo 2.3 T2V 页面 |
| --- | --- | --- |
| 请求地址 | `https://cp.compshare.cn/minimax/v2/video_generation` | `https://api.modelverse.cn/v1/tasks/submit` |
| 模型 | `MiniMax-H3` | `MiniMax-Hailuo-2.3` |
| 文本字段 | `content[].text` | `input.prompt` |
| 文本上限 | 合计 7000 字符 | 2000 字符 |
| 优化开关 | `use_context_ir`，默认 `false` | `parameters.prompt_optimizer`，默认 `true` |

Hailuo 页面的原文：

> 视频文本描述，最大长度 2000 字符

它也给出中文运镜示例：

```json
"prompt": "一只猫在草地上跑[左摇,上升]"
```

**这条示例、2000 字符限制和默认优化行为都不能搬到 H3。**本笔记判断 H3 中文输入时使用的是 H3 自己的中文示例，而不是 Hailuo 2.3 文档。项目旧实施文档中的通用 MiniMax `video-generation-v2-create` 链接也未被用作 CompShare H3 的替代证据。

## 5. 未取得或不能推断的证据

- `raw.githubusercontent.com` 在本环境发生 DNS 解析失败；改用公开 GitHub Contents API，成功取得固定提交的 README、Skill 和两个指南。没有把本地副本假冒成在线证据。
- 上游 README 的 “Prompting Guidance” 第 442 行明确写道：“Prompting guidance documents from the HuggingFace release are not copied into this repository to keep the markdown layout minimal.” 本次未另行核验 Hugging Face 的完整发布文档；这里的具体英文规则来自上游 GitHub 实际可读的 Skill 及引用文件。
- 仓库保存的《🐚MiniMax H3 模型 - 使用手册》第 54 行写有“支持多语言提示词输入与输出”，且有中文描述示例。其飞书来源 https://vrfi1sk8a0.feishu.cn/wiki/FIWjwgL33ipnkekzk30crmKUnIh 本次访问遇到重定向循环，未完成在线核验，故不以该本地副本单独认定官方实时能力。
- 没有付费调用、免费试生成、连通性模型请求、任务查询或余额查询，因此不能给出实际生成成功率、中英文画质对比、中文原始描述绕过优化后的效果，或历史失败唯一根因。
- 未取得 CompShare 内部 Context-IR 的输出或翻译实现，不声称它必然把中文改为英文。

**对后续决策的意义：**可以纠正“CompShare H3 不支持中文描述”的表述；不能据此直接删掉现有英文校验。是否采用平台 Context-IR、中文直传或继续本地英文扩写，是后续需明确质量目标和契约的设计选择。本次仅记录证据，不变更该选择。

## 6. 用户提供的仙宫云工作流

主代理通过只读浏览器查看[原始页面](https://www.xiangongyun.com/image/detail/8517a83f-a46c-4ed0-b529-4910d97bcf80?r=WAE8YM)，标题为“MiniMax H3 最强开源视频模型 (体验版)”，再沿其实际链接查看[新版说明](https://www.xiangongyun.com/image/detail/245c01fc-b57f-4279-880f-d9f501d8e002?r=PQKE3B)，标题为“海螺 MinMax H3 全功能 音频大升级版本”，页面显示更新日期 2026-09-16。这是第三方工作流说明，不是 MiniMax 或 CompShare 的接口规范。

新版明确写道：

> 本手册面向普通创作者，无需学习复杂格式，使用中文自然语言即可创作。

> 内置提示词增强｜正常描述创意即可，自动理解人物、素材、台词、动作和镜头关系

因此可以确认它支持中文创作输入，并有提示词增强步骤；页面没有公开增强后的最终提示词或实际推理请求，无法据此认定最终正文必然为中文，也没有证据证明其内部增强就是 CompShare Context-IR。

值得借鉴的写法：

1. 分清每份参考资产的职责。页面例子要求女主图锁定脸型、五官、发型、肤色和年龄，允许姿势和光线变化；动作视频只参考动作、节奏、运镜和构图，排除人物身份、服装等。
2. 用时间段表达可见动作与结果，避免只有剧情总结。图像里是什么、角色接下来做什么、结尾停在哪里，要分别说明。
3. 指定谁准确说什么、语气如何；明确无对白时不要增加人声。
4. 环境声、对白和配乐给出优先级；声音不能盖住对白。不要同时要求同一音频“只参考音色”又“完整复制原话”。
5. 别名在开始处绑定一次，避免反复堆叠相同约束。该工具的 `@女主` 是其素材引用方式，ComicFlow 必须映射到真实 manifest 的 `<Picture N>` / `<Subject N>`，不能照抄为悬空标签。

针对“推门却没有进去”的中文创作示例（不是可直接绕过现有校验提交的最终 H3 载荷）：

```text
5秒，中景固定机位，从便利店内侧拍向玻璃门，门向店内推开。
0–1秒：男子在门外站定，右手握住门把手。
1–3秒：他把门向店内推开，迈步穿过门口；镜头持续看见门与双脚。
3–5秒：他的双脚和身体完全进入店内，松开把手，停在门内一步处。
结束时人已在店内，不停在推门或跨门槛中途。无对白，只保留门铃和脚步声。
```

这类写法将动作终态变得可验收，但不保证模型每次执行成功。画面质感、角色一致性还依赖参考资产质量、引用匹配、镜头负载及画面风格，不能归因于中文或英文单一因素。

后续设计建议（尚未实施）：先让用户看清并编辑中文创作意图、参考图职责和动作终态，同时能检查实际提交提示词。当前继续保留本地 Skill 扩写；如评估平台 Context-IR，应作为明确的另一条提示词处理路径，先核对费用、Skill 格式、参考标签和输出可观测性，不在本地已扩写后默认再做一遍平台优化，也不直接删除现有语言校验。本次没有质量对照试生成。

## 7. 两个仙宫云版本追加对比

2026-09-16 根据用户追加的两个链接再次读取公开页面。第一份是上述音频升级版；第二份为[长视频版](https://www.xiangongyun.com/image/detail/df4942db-ce48-4488-a878-c35e02819aa2?r=PQKE3B)，标题“海螺 MinMax H3 全功能（支持长视频）”，显示更新于 2026-09-08。以下均是作者页面声明，未部署或实测。

| 项目 | 音频升级版 | 长视频版 |
| --- | --- | --- |
| 视频组织 | 全能参考、文生视频、首尾帧；连续投递、排队、批量顺序生成 | 另加长视频，目标时长 15 秒起；自动分段、顺序生成、合成整片，页面宣传上限 10 分钟 |
| 单段修订 | 历史预览与下载 | 分段完成即可预览；整片完成后可修改单段提示词重新生成，确认替换后更新完整版 |
| 音频 | 音画同生、音色参考、保留原声、关闭音频、独立配音；独立配音逐句试听后生成视频 | 同样宣传五种音频模式与配音工作台，不是音频升级版独占 |
| 提示词辅助 | 内置提示词增强 | 提示词助手“智能诊断、优化建议” |
| 素材管理 | 角色资产、`@` 引用 | 资产库与本次上传统一 `@` 引用、彩色高亮、悬浮预览 |
| 画质选项 | 极速、平衡、质量；最高 768P | 同样宣传三档和最高 768P |

两页下方使用相同的基础手册，包括“最长 15 秒”和六类提示词信息。长视频页的新增功能明确说明分段合成，不能将顶部“10 分钟”解读为模型一次推理可生成 10 分钟。基础手册未完整说明长视频实现与参数，不能推断它每段使用尾帧、参考视频或其他隐藏状态。

另外，三档“画质”没有公开对应的请求参数/采样设置，不能直接映射到 CompShare API，也不能推断等于三个分辨率。页面的 GPU 镜像租赁工作流与现有优云 API 是不同运行方式；当前继续使用优云时仍依其官方参数选择 768P。

### 当前源码对照

本节是源码核查，不代表已核实运行中的容器与源码完全一致。

- 已有逐镜顺序生成、失败停止和有效资产复用：`frontend/src/use-batch-generation.ts:43`、`backend/src/comicflow/production/pipeline.py:1900`。真实视频拼接位于 `backend/src/comicflow/providers/video_composition.py:77`。
- **当前连续性条件比既有工程规约更宽。** `pipeline.py:1210` 的 `h3_reference_reanchor` 只要发现同场景后续镜头有角色参考且没有显式关键帧，就采用全能参考；并非仅在新增角色时启用。上一尾帧作为普通连续性图片，与角色/场景参考共同传入。`introduced_reference_inputs` 仍被计算但未用于此分支。不能沿用旧文档宣称所有普通后续镜头都是严格尾帧级联。没有角色参考等其他级联条件下才走 `i2va`；相关分支见 `pipeline.py:1321`、`:1336`。本轮没有更改该策略。
- 已有 H3 视频原声提取与按源资产复用：`pipeline.py:1491`、`:1568`。它解决已有视频合成的声音复用，不等于新视频能参考固定角色音色。目前 `providers/minimax_h3.py:175` 的请求组装只有文本和图片，未接入页面宣传的通用视频/音频参考。
- 图片引用编号与角色别名已有：`providers/h3_skill.py:203`、`:316`，但属于请求内映射。未见页面那样可编辑、悬浮预览的通用 `@素材` 编辑器。
- `frontend/src/features/visuals/VisualWorkspace.tsx:104` 仅展示只读 `visualDescription`，不是最终 H3 扩写提示词或实际参考清单。`providers/minimax_h3.py:144` 在成功资产中保存扩写信息；未见生成前的完整准备、检查、确认提交入口。
- 视频重新生成按钮已有，但 `pipeline.py:1457` 成功后直接使旧视频失效并加入新资产，没有“新视频候选→确认替换→更新整片”的完整流程。因此不能将现有重生成按钮视为候选确认已经完成。

### 对 ComicFlow 的建议，尚未实施

1. **先补足生成前可检查的信息。** 每段集中呈现中文创作意图、实际引用的角色/场景/连续性图片、素材用途、起止状态、对白和处理后的最终提示词。引用展示必须与真正提交的 manifest 一致。若准备提示词需要文本 API，要单独提示费用，不能包装成免费预览。
2. **把连续动作与切镜区分开。** 连续动作核对前段实际尾帧与后段起始状态；换场景、换机位或新增角色时，明确引用策略与空间关系，而非强求所有镜头首尾像素相接。全能参考中的尾帧只是参考，不等于严格首帧约束。
3. **优先人工确认后续段。** 对当前 30 秒目标，保留逐段预览、确认后继续的选择，先停止错误向后传播。不要为复刻十分钟演示先做无人值守批量生成。分段时长由动作和对白需要决定，不固定认定 6×5 秒或 2×15 秒必然更好。
4. **局部重生成采用候选确认。** 用户接受后才替换旧片；若新片尾帧发生变化，标记依赖它的后续段需核查，避免只重合成便宣称连续性恢复。已生成资产应保留，后续重新生成需显式操作。
5. **音频增强后置。** 当前先使用 H3 音画同生并复用原声。只有出现稳定的跨段音色问题或对白控制需求时，再评估固定音色资产、独立配音试听和参考音频链路；需确认网关支持及额外费用，不能由页面广告推断已经可用。

这些是从公开产品行为提炼的改进建议，不是对其内部代码的复刻，也不是画质已经优于当前项目的证据。两页没有公开 API 接入 Skill 正文、最终增强 Prompt 或采样配置，未下载、执行或替换任何 Skill。

## 来源

[S1]: https://www.compshare.cn/docs/modelverse/models/video_api/minimax-h3-video-api
[S2]: https://github.com/MiniMax-AI/MiniMax-H3/blob/d21241f0a4b3acbb34c97dae47fa417b7065e438/skills/h3-prompt-writing/SKILL.md#L33
[S3]: https://github.com/MiniMax-AI/MiniMax-H3/blob/d21241f0a4b3acbb34c97dae47fa417b7065e438/skills/h3-prompt-writing/references/ref-en.txt#L5
[S4]: https://github.com/MiniMax-AI/MiniMax-H3/blob/d21241f0a4b3acbb34c97dae47fa417b7065e438/skills/h3-prompt-writing/references/base-en.txt#L154
[S5]: https://github.com/MiniMax-AI/MiniMax-H3/blob/d21241f0a4b3acbb34c97dae47fa417b7065e438/README.md#L78
[S6]: https://www.compshare.cn/docs/modelverse/models/video_api/MiniMax-Hailuo-2.3-T2V
[L1]: /C:/Users/lmk/Documents/ChatGPT/comicflow/skills/h3-prompt-writing/SKILL.md:33
[L2]: /C:/Users/lmk/Documents/ChatGPT/comicflow/docs/PROJECT_ENGINEERING_RULES.md
[L3]: /C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/providers/h3_skill.py:370
[L4]: /C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/providers/h3_language.py:113
[L5]: /C:/Users/lmk/Documents/ChatGPT/comicflow/backend/src/comicflow/providers/minimax_h3.py:55

补充可复查链接：[上游中文 README](https://github.com/MiniMax-AI/MiniMax-H3/blob/d21241f0a4b3acbb34c97dae47fa417b7065e438/README.zh-CN.md#L78)、[Context-IR 推荐](https://github.com/MiniMax-AI/MiniMax-H3/blob/d21241f0a4b3acbb34c97dae47fa417b7065e438/README.md#L90)、[Prompting Guidance 可用性说明](https://github.com/MiniMax-AI/MiniMax-H3/blob/d21241f0a4b3acbb34c97dae47fa417b7065e438/README.md#L440)。
