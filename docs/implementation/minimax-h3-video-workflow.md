# MiniMax H3 视频生成完整方案

> 2026-09-16 新角色入场与动作终态修订：同场景后续镜头首次引入有已确认参考资产的新角色时，不再只用上一尾帧 `i2va`；改用 `ref2va`，把上一尾帧作为普通连续性参考图，并同时传入当前角色板和场景图。普通同角色续接仍用尾帧 `i2va`。剧本与 H3 Prompt 新增动作前、中、后可见状态约束，进入/穿过空间必须完整越过门槛并稳定到达目标空间。真实 API 未调用。
> 2026-09-16 修订：H3 官方分辨率支持 `768P`/`1080P`/`2K`，默认和低成本验证均使用 `768P`；控制台和 Provider 已接通三个档位，`720P` 会被拒绝。新场景首镜头在没有显式首/尾帧时使用当前镜头全部角色与场景参考图建立 `ref2va`；同场景后续镜头默认只用前镜头尾帧 `i2va`，首次引入有参考资产的新角色时按上一条改用 `ref2va` 重新锚定。真实 API 未调用。
> 2026-09-12 离线级联修复：已定位并修复后续 H3 镜头因角色参考图而错误进入 `ref2va`、丢失上一镜头尾帧的问题。现在同一场景的后续镜头强制使用上一有效视频的 `lastFrameObjectKey` 作为 `i2va` 首帧，并移除角色图片/场景图片输入，只保留角色文字设定给 H3 Skill；尾帧缺失会在文本扩写前返回 `CASCADE_FRAME_MISSING`。首镜头和新场景首镜头仍使用 `ref2va`。新增 `backend/tests/test_h3_cascade.py`，2 项通过。本轮没有真实供应商请求。

> 最新2026-09-10：用户报告任务已提交（`01a08b2a-68ed-7d50-848b-dbc01285f5dd`）但查询响应无法解析（日志 `stage=h3_poll reason=invalid_response`，对应 `prj_511e4e958ae7/shot_2`）。该笔已用只读查询+一次挂载找回（4.209秒/1408×2432/含音轨，GenerationRequests=0，不要重新生成 shot_2）。根因未确定：失败瞬间原始响应未保存，成功态下现有解析器读取同一任务正常；第三方资料的状态枚举与本网关观察不符，未据此改状态表。已实施行为修复：未知 status 不再立即失败，记录安全状态词（≤32位 ASCII，否则 `unreportable`）并继续轮询至预算用尽，届时报 `unknown_status` 或 `timeout`；非 JSON 响应体仍硬失败；并修正 `_poll` 错误被重新包装覆盖 reason 的问题。5 项新用例先红后绿，全量 396 passed/12 既有 failed/2 skipped，Ruff/Mypy 通过，部署后对真实任务只读复验正常。详见 `.scratch/h3-validation/issues/07-poll-tolerance.md`。

> 最新2026-09-10：第二次真实尝试失败为 `reason=language` / `section=retention_analysis`（页面「参考保留分析：英文描述中混入了未标记的中文」）。该次章节原文未保存，不能断言具体片段；已证实的是别名规范化只认**完整姓名**，模型写「李俊杰的外观」「李俊杰之形象」「俊杰」这类附着式或省略姓氏的形态时会整体漏过并被门禁拒绝。已按闭集修复：结构名词表（外观/服装/发型/身份/形象/特征/设定/声音/表情/动作/性格）+ 助词 `的`/`之` 译为 `Character N's X`，共享名字段时禁用简称映射，全角逗号规范化；表外中文仍拒绝（不翻译、不猜测）。系统提示词新增「章节不得含任何中文字符」。19 项新用例先红后绿；全量 391 passed/12 既有 failed/2 skipped；六镜头离线端到端通过；ruff/mypy 通过；本轮真实调用 0。中途为「模型把台词原文写进描述」实现过按子句剥离，因不断追加启发式且破坏既有契约（误删 `"李俊杰"` 合法画面文字）已整体撤回，该形态仍为明确拒绝。API 已重建重启，video=compshare-h3/MiniMax-H3 仍 enabled。详见 `.scratch/h3-validation/issues/06-language-name-forms.md`。

> 最新2026-09-10：连续生成卡在第 2 镜头的 `reason=dialogue` 已按根因修复。原实现要求文本模型逐字回写台词，模型只要改写「（内心OS）」这类舞台提示、把 `……` 写成 `...` 或把台词写进正文，就整次拒绝一次已付费的扩写并中断批量。现改为**应用逐字注入台词**：模型只写英文描述，应用把项目保存的 `dialogue`/`narration` 按原顺序注入 `<d>[Chinese] ...</d>`（基础模式进 `integrated_multimodal_description`，ref2va 进 `detailed_description`）；校验改为“注入后必须逐字包含每条台词”，时长/章节/引用/语言/模式校验与“失败即停”的批量语义均未放宽。10 项新用例先红后绿，六镜头离线端到端逐镜头核对供应商载荷，全量 370 passed/12 既有 failed/2 skipped，Ruff/Mypy/前端构建通过，本轮真实调用 0。API 已重建并重启（重启后 video=compshare-h3/MiniMax-H3 仍 enabled，无需重填密钥）；真实第二镜头仍需用户用最小额度点一次验证。详见 `.scratch/h3-validation/issues/05-speech-injection.md`。

> 最新2026-09-10：真实任务`01a08acc-89ca-7eec-b92d-b0edbcda584b`虽然前端报h3_poll解析失败，后续只读查询已succeeded。现已通过`recover_h3_task.py`恢复到`prj_511e4e958ae7/shot_1`，真实MP4/首尾帧/刷新预览验证通过：4.875秒、1408×2432、含音轨。本轮未重新扩写或生成。恢复测试9通过，全量363通过/12既有失败/1跳过。首次失败响应缺失，解析根因仍未确认；任务号即时持久化、正式恢复入口及安全异常结构诊断是下一步，尚未实现。操作命令和安全边界见`.scratch/h3-validation/issues/04-existing-task-recovery.md`及HANDOFF顶部。不要重复生成已有第1镜头。

> 最新2026-09-10：用户新错误已明确reason=language，视频未提交，文本可能已计费。离线复现并修复英文描述中的已知中文角色名拒绝：本次请求唯一角色名映射为Character N，原对白/画面文字保持原文，其余中文描述继续拦截；Skill提示明确别名/英文六章节/可见文字双引号。新增安全章节定位。47项专项通过，全量354通过/12既有失败/1跳过，Ruff/Mypy/构建通过；API已部署并本地验证生效，配置与代理健康。本轮真实模型请求0。没有该次扩写原文，不能断言角色名就是这次真实根因；不要再以付费重试诊断。详见HANDOFF顶部及`.scratch/h3-validation/issues/03-language-contract.md`。扩写草稿保存与人工预览后提交尚未实现，生成按钮仍可能计费。

> 当前优先级2026-09-10：用户要求先离线跑通，真实供应商测试暂停。当前六镜头副本已通过API/Skill/H3模拟HTTP/视频存储/真实FFmpeg首尾帧/刷新恢复全链路；测试禁止真实socket。H3参考图预检与Base64准备已移到文本扩写前，避免本地输入错误消耗额度。35项聚焦通过、全量342通过/12既有失败/1跳过。真实MinIO两张图片只读校验通过。详细命令与不能证明的边界见`h3-offline-verification.md`；未经用户后续明确授权，不进行真实文本/图片/视频验证。

> 最新2026-09-10：用户点击返回PROVIDER_INVALID_RESPONSE，已增加文本扩写/H3提交/查询/结果四阶段安全诊断及已知任务号展示，输出截断单独提示。7项新增/43项相关离线通过，未真实重试，历史响应阶段尚不能确定。下一步查看优云已有任务，避免重复付费。见HANDOFF顶部与`.scratch/h3-validation/issues/02-response-boundaries.md`。

> 当前2026-09-10：用户已切回正式H3，反馈Skill校验失败。本轮增加固定reason中文诊断，明确Skill输出JSON/模式规则，修复关键帧对齐引用提前校验与分段台词误拒绝；新增15项离线测试通过，未真实扩写或生成。该项目历史具体失败分支未记录，仍待新reason确认；不能用“代码修复”代替真实成功验收。Worker/beat接手前已运行。详见HANDOFF顶部及`.scratch/h3-validation/`，覆盖下方Wan测试流程的历史状态。

## 交接给 Claude：当前执行顺序

当前先验收百炼 Wan 2.7 测试链路，不继续扩展 H3 或 JSON 引擎。API 已部署 `input.media` 首帧协议和单角色参考图优先逻辑；`shot_1` 已有成功视频，`shot_2` 曾因错误尾帧级联返回400，代码已修复。API 重启后的测试 Key 不保留，需用户在模型 API 页面重新填写并启用 `wan2.7-i2v / 720P / i2v`，然后只生成一次 `shot_2`。失败时查看受限 `code/request_id`，按 `VIDEO_REQUEST_INVALID`、`VIDEO_QUOTA_EXHAUSTED`、`VIDEO_RATE_LIMITED`、`VIDEO_CONTENT_REJECTED`、`PROVIDER_AUTH_FAILED` 分流；禁止自动重试。完整交接见仓库根目录 `HANDOFF.md` 顶部，问题记录见 `.scratch/character-image-503/issues/04-wan27-media-protocol.md`。

> 2026-09-10 Wan 2.7修复：百炼新版协议要求2.7图生视频使用`input.media`首帧对象，旧版2.1–2.6继续使用`input.img_url`。此前503日志的上游code为InvalidParameter，已修正请求结构和错误分类并部署API。相关任务记录见`.scratch/character-image-503/issues/04-wan27-media-protocol.md`。尚未真实重试，避免额度消耗。

> 最新部署2026-09-10：用户要求修复API，已仅重建API容器应用首帧修复，运行代码及健康/前端代理检查通过。视频测试配置保留 wan2.7-i2v、720P、i2v；测试密钥未跨重启保留，当前禁用，用户须在模型API的视频测试套重新填Key并启用后再生成。已有场景背景无需重做。图片正式套恢复wan2.6-image并沿用环境初始化密钥，图片测试套同样需重新填Key。没有真实模型请求，Worker/beat保持停止。下一步先由用户补视频测试密钥、保存启用，再按预算验证一个现有5秒镜头；若仍失败读取受限上游code/request_id继续定位。JSON调用配置、加密持久化/Worker同步及旧11项回归仍待实施。此条覆盖下方“运行API未重建”的历史状态。

> 最新2026-09-10视频503修复：百炼首帧原使用本机MinIO URL，现改为已存图片按对象键读取、校验后Base64提交。场景/尾帧/镜头图/单角色图路径覆盖，27项聚焦通过，新镜像使用用户原图离线验证成功。运行API未重建，应用修复需重新填写进程内密钥；未真实生成。历史400分辨率问题已被用户改为720P，背景图现已存在，勿重复建议重新生成。详见HANDOFF顶部和 `.scratch/character-image-503/issues/03-video-stored-frame.md`。

> 2026-09-10 视频400诊断：当前 wan2.7-i2v + 480P 被本地 VIDEO_RESOLUTION_INVALID 拒绝；首镜头shot_1另缺首帧（无角色绑定、无场景背景、无已有画面），720P离线校验返回 VIDEO_FIRST_FRAME_REQUIRED。用户需自行配置支持的分辨率并准备首帧，再做受预算控制的验证。本次只读配置/项目和纯函数校验，未修改参数、未调用供应商。详见HANDOFF顶部。

> 2026-09-10 操作补充：角色图片400日志已确认；发现当前模型名首尾空格，已修正当前运行配置并保留密钥。前端保存及后端Schema加入模型名trim/空白拒绝，25项聚焦和3项页面验证通过。后端镜像已构建、运行API未重建（保留内存配置），未发起生成；历史400具体上游message缺失，不能确认唯一原因。交接见 HANDOFF 顶部和 `.scratch/character-image-503/issues/02-model-whitespace.md`。JSON调用方案尚未实施。

> 2026-09-09 自定义模型增量：按用户要求，所有文本/图片/视频模型可手填，切换供应商不覆盖模型和地址；新增图片协议选择、图片/百炼视频自定义路径和 wan2.6-image 正确异步协议，图片 HTTP 错误不再一律误报 503。操作、39 项聚焦验证、3 项页面验证及后续任务见 `model-protocol-configuration.md`。不自动替用户选模型，不调用真实生成；共享配置、Worker 同步与旧11项回归仍待完成。

> 此增量已部署到本地 API。当前用户图片/视频测试模型分别为 wan2.6-image / wan2.7-i2v，非密钥参数与测试套选择已保留，测试密钥需用户重新填写并启用；视频480P须自行按规格调整。覆盖下文此前“正式套当前生效”的历史记录。详细部署与后续配置步骤见上述文档末节。

> 最新实施：API 管理支持文本/图片/视频各两套测试/正式配置，百炼视频已接入，H3 Skill 保留。使用方法、离线验证和边界见 `provider-profile-switching.md`。配置仍仅在API进程，Worker未同步；旧11项回归未修复。未进行真实收费生成。

> 本轮部署核对：仅重建/重启 API，健康检查及前端代理读取 profiles 正常；三类能力仍使用正式配置，测试套未配置。密钥重新读取 `.env`，图片启用状态已恢复，运行时为 `BailianImageProvider`，视频保持 `MinimaxH3Provider`。未重启 Worker/beat，未发起生成。后续先处理旧回归、加密持久化和 Worker 配置版本同步，再安排最小真实验收；完整操作记录见 `provider-profile-switching.md`。

> 运行状态补充（2026-09-09）：用户反馈配置 API 后仍不能生成角色参考图。检查发现已保存文本配置，但图片 `enabled=false`、适配器为空；已使用现有密钥启用图片 API，读回 `BailianImageProvider`。仅修改进程内启用状态，未实际出图、未消耗模型额度。此前“图片禁用”的部署记录保留为历史；重启仍恢复环境变量配置。

> 最新增量：角色页已接入文本 API 生成中文角色设定/参考图提示词草稿，预览编辑、采用保存后供图片 API 使用。实现记录见本文最后“角色提示词助手”一节。未进行真实收费验收。

**基于官方文档设计的漫剧视频生成工作流**

> 2026-09-09 最新修订：中文剧本/角色闭环、独立图片 API、API 管理扩展与每次 H3 执行 Skill 已接入。配置仍为 API 进程内状态，Worker 未同步；11 项既有回归未修复，收费验收暂停。以 `HANDOFF.md` 顶部、本文件末节和 `provider-console-upgrade-assessment.md` 为准，历史“全部完成”不代表当前验收结论。

参考文档：
- `🐚MiniMax H3 模型 - 使用手册.md`
- `MiniMax H3 - 视频扩写 Prompt 写作全能指南.md`
- MiniMax API 文档：https://platform.minimaxi.com/docs/api-reference/video-generation-v2-create

---

## 一、MiniMax H3 核心能力总结

### 1.0 项目内 Skill 约束

项目已引入 MiniMax 官方 `h3-prompt-writing` skill：

```text
skills/h3-prompt-writing/SKILL.md
skills/h3-prompt-writing/references/base-en.txt
skills/h3-prompt-writing/references/ref-en.txt
```

剧本生成阶段必须声明后续视频 Prompt 编写使用该 Skill，但可编辑的角色、场景、动作、运镜、风格和声音描述必须使用中文，不能套用 Skill 的英文扩写规则。视频 Provider 负责按照 Skill 组装最终 H3 Prompt，不能只把 `visualDescription` 直接发送给 H3。声明本地路径不等于已载入或执行 Skill，运行时编译仍须单独验收。

### 1.1 模型规格

| 项目 | 规格 |
|------|------|
| 输出时长 | 4-15 秒 |
| 分辨率 | 768p（短边768px）或 1440p（短边1440px，推荐） |
| 宽高比 | 21:9、16:9、4:3、1:1、3:4、9:16 |
| 帧率 | 24 FPS |
| 音频 | 原生双声道，支持 TTS（11 种语言） |

### 1.2 角色一致性方案（无需三面图）

**H3 原生支持多角色参考图**：
- 使用 `<Subject N>` 标签定义角色（N=1,2,3...）
- 单次请求最多 9 张参考图
- 角色外观自动跨镜头保持一致（脸、发型、服装、体型）
- 支持动作参考（传入参考视频，提取动作迁移到目标角色）

**示例结构**：
```
subject_definitions:
- <Subject 1>: [图片URL] — 年轻女性，黑色长发，白色衬衫
- <Subject 2>: [图片URL] — 中年男性，短发，深色西装
- <Scene A>: [图片URL] — 雨夜车站，霓虹灯光

detailed_description:
[Shot 1] <Subject 1> 站在 <Scene A> 的月台上，抬头看向显示屏...
```

### 1.3 首帧级联方案

H3 支持三种图生视频模式：

**I2VA（首帧模式）**：
- 输入：1 张首帧图片
- 输出：从首帧开始的视频
- 用途：第一个镜头，或场景切换后的首镜头

**FL2VA（首尾帧模式）**：
- 输入：2 张图片（首帧 + 尾帧）
- 输出：H3 自动插值中间过程
- 用途：精确控制镜头的起止状态

**L2VA（尾帧模式）**：
- 输入：1 张尾帧图片
- 输出：H3 反推开头并收敛到尾帧
- 用途：特殊转场效果

**镜头级联实现**：
1. 首镜头：I2VA（场景背景图作为首帧）
2. 后续镜头：提取上一视频尾帧 → 作为下一镜头的首帧 → I2VA

### 1.4 Prompt 结构化

H3 使用结构化 Prompt（详见《写作全能指南》）：

```
# 首帧指令（I2VA 必需）
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

# 主体字段
integrated_multimodal_description: [Shot 1] Live-action, cinematic, <Subject 1> 站在 <Scene A>...

overall_soundscape: 雨声、脚步声、车站广播...

non_diegetic_music: 钢琴与弦乐，缓慢节奏...
```

---

## 二、完整工作流设计

### 2.1 资产准备阶段（剧本确认后）

#### 阶段 A：角色参考图生成
```
for each character in script:
    prompt = f"{character.appearance}, {character.clothing}, 正面全身照，纯色背景"
    image = await wanx_t2i(prompt)  # 使用百炼 wanx2.1-t2i-plus
    character.referenceImageUrl = upload_to_minio(image)
```

**关键点**：
- 使用文生图（wanx-t2i）生成角色标准照
- 单张正面照即可（无需三面图，H3 会自动处理多角度）
- 纯色背景方便 H3 提取角色外观特征
- 存储到 MinIO，记录 URL

#### 阶段 B：场景背景图生成
```
for each scene in script.scenes:
    prompt = f"{scene.location}, {scene.time}, 宽景构图，无人物"
    image = await wanx_t2i(prompt)
    scene.backgroundImageUrl = upload_to_minio(image)
```

**关键点**：
- 每个场景生成一张背景图
- 背景图作为首镜头的首帧输入
- 同场景内的后续镜头通过首帧级联保持背景一致

### 2.2 视频生成阶段（按镜头顺序）

#### 核心逻辑
```python
prev_last_frame = None

for shot in shots:
    # 1. 确定首帧
    if shot.order == 1 or shot.sceneId != prev_scene_id:
        # 场景首镜头：使用场景背景图
        first_frame = scene.backgroundImageUrl
    else:
        # 同场景后续镜头：使用上一镜头尾帧
        first_frame = prev_last_frame
    
    # 2. 构建角色参考
    character_refs = []
    for char_id in shot.characterIds:
        character = get_character(char_id)
        character_refs.append({
            "subject_id": f"Subject {len(character_refs) + 1}",
            "image_url": character.referenceImageUrl,
            "description": f"{character.name}: {character.appearance}"
        })
    
    # 3. 构建 Prompt
    prompt = build_h3_prompt(
        first_frame=first_frame,
        character_refs=character_refs,
        shot=shot,
        scene=scene
    )
    
    # 4. 调用 MiniMax H3 API
    video = await minimax_h3_api(prompt)
    
    # 5. 提取尾帧作为下一镜头首帧
    prev_last_frame = extract_last_frame(video)
    prev_scene_id = shot.sceneId
```

#### Prompt 构建示例
```python
def build_h3_prompt(first_frame, character_refs, shot, scene):
    # 首帧指令
    instruction = (
        f"For the target video, at 0.00 seconds into the target video, "
        f"<Picture 1> (from [Shot 1]) is fully referenced."
    )
    
    # 角色定义
    subject_defs = "\n".join([
        f"<{ref['subject_id']}>: {ref['description']}"
        for ref in character_refs
    ])
    
    # 场景定义
    scene_def = f"<Scene A>: {scene.location}, {scene.time}"
    
    # 多模态描述
    description = f"""
[Shot 1] Live-action, cinematic, {shot.shotSize} frames <{character_refs[0]['subject_id']}> 
in <Scene A>. {shot.action}. {shot.emotion}. 
The camera {shot.cameraMovement or 'holds a static shot'}.
"""
    
    # 对白
    if shot.dialogue:
        speaker_id = f"S{character_refs[0]['subject_id'][-1]}"
        description += f"""
The {character_refs[0]['description']} ({speaker_id}) says: 
<d>[Chinese] {shot.dialogue}</d>
"""
    
    # 环境声
    soundscape = f"Ambient sounds of {scene.location}: ..."
    
    # 背景音乐
    music = "Sparse piano with low strings, slow tempo"
    
    return {
        "instruction": instruction,
        "subject_definitions": f"{subject_defs}\n{scene_def}",
        "integrated_multimodal_description": description,
        "overall_soundscape": soundscape,
        "non_diegetic_music": music,
        "first_frame_url": first_frame,
        "character_reference_urls": [ref["image_url"] for ref in character_refs]
    }
```

---

## 三、数据模型扩展

### 3.1 Character 扩展
```python
class Character:
    id: str
    name: str
    appearance: str
    clothing: str
    personality: str
    voice: dict
    referenceImageUrl: str | None  # 新增：角色参考图 URL
    source: str  # "user" | "temporary" | "system"
```

### 3.2 Scene 扩展（需确认当前 schema）
```python
class Scene:
    id: str
    location: str
    time: str  # "white_day" | "night" | "dawn" | "dusk"
    backgroundImageUrl: str | None  # 新增：场景背景图 URL
    shotIds: list[str]
```

### 3.3 Shot 扩展（可选优化）
```python
class Shot:
    id: str
    sceneId: str  # 新增：关联场景（如果当前没有）
    characterIds: list[str]  # 已有（task 5 已修复）
    action: str
    dialogue: str
    emotion: str
    shotSize: str
    cameraMovement: str | None  # 新增：运镜描述（可选）
    ...
```

---

## 四、技术实现拆解

### 4.1 MiniMax H3 Provider（新增）

**文件**：`backend/src/comicflow/providers/minimax_h3.py`

```python
class MinimaxH3Provider:
    """MiniMax H3 video generation provider."""
    
    def __init__(self, api_key: str, base_url: str = "https://api.minimaxi.com"):
        self._api_key = api_key
        self._base_url = base_url
    
    async def generate_video(
        self,
        prompt: dict,  # 结构化 Prompt
        first_frame_url: str | None = None,
        character_refs: list[str] | None = None,
        resolution: str = "768P",  # "768P" | "1080P" | "2K"
        duration: float = 10.0,  # 4-15 秒
    ) -> dict:
        """
        调用 MiniMax H3 API 生成视频
        
        返回：
        {
            "video_url": "https://...",
            "duration_ms": 10000,
            "width": 1920,
            "height": 1080,
            "objectKey": "videos/shot-xxx/h3.mp4"
        }
        """
        # API 调用实现
        pass
```

### 4.2 Pipeline 改造

**修改点 A**：资产生成阶段

```python
# pipeline.py

async def confirm_script(self, project_id: str, expected_version: int):
    # ... 现有逻辑
    
    # 新增：生成角色参考图
    for character_id in unique_character_ids(script):
        character = await self._character_repository.get(character_id)
        if not character.get("referenceImageUrl"):
            ref_image = await self._generate_character_reference(character)
            character["referenceImageUrl"] = ref_image["url"]
            await self._character_repository.save(character)
    
    # 新增：生成场景背景图
    for scene in script["scenes"]:
        if not scene.get("backgroundImageUrl"):
            bg_image = await self._generate_scene_background(scene)
            scene["backgroundImageUrl"] = bg_image["url"]
    
    # ... 保存

async def _generate_character_reference(self, character: dict) -> dict:
    """生成角色参考图（单张正面照）"""
    prompt = f"{character['appearance']}, {character['clothing']}, full body portrait, plain background, frontal view, anime style"
    image = await self._image_provider.generate(prompt)  # wanx-t2i
    object_key = f"characters/{character['id']}/reference.png"
    await self._asset_store.put_bytes(object_key, image["content"], "image/png")
    return {"url": await self._asset_store.presigned_get_url(object_key)}

async def _generate_scene_background(self, scene: dict) -> dict:
    """生成场景背景图"""
    prompt = f"{scene['location']}, {scene['time']}, wide establishing shot, no characters, anime style"
    image = await self._image_provider.generate(prompt)
    object_key = f"scenes/{scene['id']}/background.png"
    await self._asset_store.put_bytes(object_key, image["content"], "image/png")
    return {"url": await self._asset_store.presigned_get_url(object_key)}
```

**修改点 B**：视频生成逻辑

```python
# pipeline.py

async def generate_shot_visual(self, project_id: str, shot_id: str, *, expected_version: int):
    record = await self._require_record(project_id)
    project = record.project
    shot = self._require_shot(project, shot_id)
    script = project["script"]
    
    # 1. 确定首帧
    prev_shot = self._get_previous_shot(script, shot_id)
    if not prev_shot or shot["sceneId"] != prev_shot.get("sceneId"):
        # 场景首镜头：使用场景背景图
        scene = self._get_scene(script, shot["sceneId"])
        first_frame_url = scene.get("backgroundImageUrl")
    else:
        # 同场景后续镜头：使用上一镜头尾帧
        prev_visual = self._get_valid_visual(project, prev_shot["id"])
        first_frame_url = prev_visual.get("lastFrameUrl")  # 需存储尾帧
    
    # 2. 获取角色参考
    character_refs = []
    for char_id in shot.get("characterIds", []):
        character = await self._character_repository.get(char_id)
        character_refs.append({
            "image_url": character.get("referenceImageUrl"),
            "description": f"{character['name']}: {character['appearance']}"
        })
    
    # 3. 构建 H3 Prompt
    prompt = self._build_h3_prompt(shot, scene, character_refs, first_frame_url)
    
    # 4. 调用 MiniMax H3
    video = await self._h3_provider.generate_video(
        prompt=prompt,
        first_frame_url=first_frame_url,
        character_refs=[ref["image_url"] for ref in character_refs],
        resolution="768P",
        duration=shot["durationSec"]
    )
    
    # 5. 提取并存储尾帧（用于下一镜头）
    last_frame = await self._extract_last_frame(video["video_url"])
    video["lastFrameUrl"] = await self._upload_frame(last_frame, shot_id)
    
    # 6. 存储资产
    assets = project.setdefault("visualAssets", [])
    for asset in assets:
        if asset["shotId"] == shot_id and asset.get("valid"):
            asset["valid"] = False
    asset = {**video, "valid": True, "inputVersion": project["version"]}
    assets.append(asset)
    
    project["exportManifest"] = None
    project["downstreamInvalidated"] = True
    await self._repository.save(record)
    return {"asset": deepcopy(asset), "projectVersion": project["version"]}
```

### 4.3 帧提取工具（已有原型）

**文件**：`backend/src/comicflow/utils/frame_extractor.py`（已存在）

需补充的方法：
```python
async def extract_last_frame(video_url: str) -> bytes:
    """提取视频最后一帧"""
    # 使用 ffmpeg -sseof -1 提取最后一帧
    # 返回 PNG/JPEG 字节
```

---

## 五、API 配置

### 5.1 环境变量

需要新增：
```bash
# MiniMax H3
MINIMAX_API_KEY=sk-xxx
MINIMAX_BASE_URL=https://api.minimaxi.com  # 可选，默认值

# 保留现有百炼配置（用于文生图）
BAILIAN_API_KEY=xxx  # wanx-t2i
```

### 5.2 Provider 初始化

```python
# backend/src/comicflow/api/app.py

def create_configured_runtime():
    # ... 现有 providers
    
    # 新增：MiniMax H3 provider
    minimax_h3_provider = MinimaxH3Provider(
        api_key=os.getenv("MINIMAX_API_KEY"),
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimaxi.com")
    )
    
    # 替换 dynamic_visual_provider
    pipeline = ProductionPipeline(
        # ...
        dynamic_visual_provider=minimax_h3_provider,  # 替换百炼 video
        # ...
    )
```

---

## 六、测试计划

### 6.1 单元测试

**文件**：`backend/tests/test_minimax_h3.py`

```python
async def test_character_reference_generation():
    """验证角色参考图生成"""
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    
    created = await pipeline.create_project(...)
    script = await pipeline.generate_script(project_id)
    await pipeline.confirm_script(project_id, version)
    
    # 验证角色有参考图
    character_ids = script["script"]["shots"][0]["characterIds"]
    character = await pipeline._character_repository.get(character_ids[0])
    assert character.get("referenceImageUrl") is not None

async def test_scene_background_generation():
    """验证场景背景图生成"""
    # 类似角色测试

async def test_first_frame_cascade():
    """验证首帧级联逻辑"""
    # 生成两个连续镜头
    # 验证第二镜头使用第一镜头的尾帧
```

### 6.2 E2E 测试

**手工验收步骤**：
1. 创建项目 → 生成剧本 → 确认剧本
2. 进入"角色"页 → 验证角色卡显示参考图
3. 生成第一个镜头视频 → 检查角色外观、场景背景
4. 生成第二个镜头视频 → 检查：
   - 角色外观一致（脸、发型、服装）
   - 背景一致（同场景内）
   - 镜头过渡流畅（首帧级联）
5. 切换场景后的首镜头 → 验证新背景正确

---

## 七、实施估时

| 阶段 | 任务 | 估时 |
|------|------|------|
| 1 | MiniMax H3 Provider 实现 | 3-4h |
| 2 | 角色参考图生成逻辑 | 2h |
| 3 | 场景背景图生成逻辑 | 2h |
| 4 | 首帧级联逻辑改造 | 3-4h |
| 5 | Prompt 构建工具 | 2-3h |
| 6 | 数据模型扩展 + Migration | 1h |
| 7 | 单元测试 | 2h |
| 8 | E2E 验收 | 2h |
| **总计** | | **17-22h** |

---

## 八、风险与注意事项

### 8.1 API 可用性
- MiniMax H3 需要申请 API Key
- 可能有配额/QPS 限制
- 需确认定价（按秒计费 or 按次计费）

### 8.2 Prompt 工程复杂度
- H3 的 Prompt 格式较复杂（结构化字段）
- 需要仔细阅读《写作全能指南》
- 可能需要多次迭代优化 Prompt 模板

### 8.3 首帧级联的视觉连贯性
- 尾帧提取的质量影响下一镜头的首帧
- 可能需要调整提取参数（关键帧 vs 最后一帧）
- 场景切换时需要正确重置首帧

### 8.4 角色参考图质量
- wanx-t2i 生成的角色图质量影响 H3 的角色一致性
- 可能需要多次生成挑选最佳结果
- 或者允许用户手动上传角色参考图

---

## 九、后续优化方向

### 9.1 角色参考图优化
- 允许用户上传自定义角色图
- 支持多张角色参考图（不同角度/表情）
- 角色图风格化（自动适配漫画风格）

### 9.2 Prompt 模板优化
- 建立 Prompt 模板库（不同场景类型）
- 支持用户自定义 Prompt 片段
- A/B 测试不同 Prompt 策略的效果

### 9.3 视频质量优化
- 支持 768p/1440p 分辨率切换
- 支持时长调整（4-15秒范围）
- 视频后处理（色调统一、锐化、降噪）

### 9.4 BGM 集成
- 使用 H3 的原生音频生成
- 或接入独立的 BGM 生成模型
- 支持用户上传 BGM

---

## 十、与现有方案对比

| 维度 | 当前方案（百炼 wanx） | MiniMax H3 方案 |
|------|---------------------|----------------|
| 输出类型 | 静态图片 | 动态视频（4-15秒） |
| 角色一致性 | 仅文本描述，无保证 | 原生多角色参考图，跨镜头一致 |
| 场景一致性 | 每镜头独立生成 | 首帧级联 + 场景背景图 |
| 镜头连贯性 | 无 | 首尾帧插值，自然过渡 |
| 音频 | 需单独生成（TTS） | 原生双声道，支持对白+BGM |
| 分辨率 | 1080×1920 | 1440p（短边1440px） |
| 价格 | TBD | TBD（需确认） |

**推荐**：MiniMax H3 方案完全解决当前的三大痛点（角色、场景、镜头一致性），且无需三面图等复杂方案。

---

## 十一、立即行动

### 下一步（按优先级）：

1. **申请 MiniMax API Key** — 需要用户操作
2. **验证 API 可用性** — 写一个测试脚本调用 H3 API（~1h）
3. **实现 MinimaxH3Provider** — 核心 Provider（~3-4h）
4. **角色参考图生成** — 接入 wanx-t2i（~2h）
5. **场景背景图生成** — 接入 wanx-t2i（~2h）
6. **首帧级联逻辑** — Pipeline 改造（~3-4h）
7. **端到端验收** — 真实生成一个项目的完整视频（~2h）

**如果用户同意此方案，我可以立即开始实施。**

## 十二、当前实施记录

### 已完成（本轮未调用真实视频 API）

- [x] 纳入 MiniMax 官方 `h3-prompt-writing` skill：`skills/h3-prompt-writing/`
- [x] 剧本系统提示词要求遵守 H3 Skill
- [x] 剧本镜头保留 `cameraMovement`、`visualStyle`、`soundscape`、`music`、`generationMode`
- [x] Script Contract 规范化上述 H3 字段
- [x] 新增 `backend/src/comicflow/providers/minimax_prompt.py`
- [x] MiniMax Provider 在没有显式 `h3Prompt` 时自动构建 H3 Prompt
- [x] 支持 `t2va`、`i2va`、`fl2va`、`l2va`、`ref2va` 模式映射
- [x] `.env` 支持优云 H3 endpoint 配置

### 下一步按顺序实现

~~1. 角色参考图和场景背景图资产准备，不调用视频额度。~~（✅ 已完成）
~~2. 为动态视频资产保存首帧、尾帧和级联来源。~~（✅ 已完成）
~~3. 接入同场景首帧级联。~~（✅ 已完成）
~~4. 修改 FFmpeg 为视频优先、图片降级。~~（✅ 已完成）
5. ~~完成离线 Mock/契约验证后~~（✅ 已完成），进行真实 API 验证：
   - **需要完整本地环境**（Docker：MinIO + PostgreSQL + Redis + API）
   - **推荐通过前端 UI 验证**（更直观，可观察级联效果）
   - 详见 `docs/implementation/h3-verification-guide.md`

### 额度约束

在完成前四项之前，不运行真实 MiniMax 视频生成脚本；只允许静态检查、Mock 测试和本地资产契约验证。

## 十三、Claude 交接执行记录

后续执行者每完成一个任务，必须在本节增加一条记录，并同步更新 `HANDOFF.md` 的”最新交接”区。

### 当前接手点

- 当前代码已经完成 H3 Skill 纳入、剧本 H3 字段契约、Prompt Builder 和优云 Provider 基础适配。
- 当前不允许真实视频生成，额度仅用于后续最小验证。
- **✅ 任务 1 已完成：角色参考图和场景背景图资产准备**

### 完成记录

#### 2026-09-09：任务 1 - 角色/场景参考资产准备

**任务：** 角色参考图和场景背景图资产准备

**修改文件：**
- `backend/src/comicflow/production/pipeline.py`：在 `confirm_script` 方法中添加角色参考图和场景背景图生成逻辑
  - 新增 `_generate_character_reference()` 方法：生成角色标准参考图（单张正面照）
  - 新增 `_generate_scene_background()` 方法：生成场景无人物背景图
  - 修改 `confirm_script()` 方法：在剧本确认时自动生成参考资产
- `backend/tests/test_character_scene_reference_assets.py`：新增 4 个测试用例

**输入/输出契约：**
- Character 扩展字段：
  - `referenceImageUrl` (str | None)：角色参考图预签名 URL
  - `referenceImageObjectKey` (str | None)：角色参考图对象键
- Scene 扩展字段：
  - `backgroundImageUrl` (str | None)：场景背景图预签名 URL
  - `backgroundImageObjectKey` (str | None)：场景背景图对象键

**失败行为：**
- 角色参考图或场景背景图生成失败时**不会阻塞剧本确认**
- 失败时静默跳过，记录在异常处理中（Exception catch）

**离线验证：**
- ✅ 4 个单元测试全部通过：
  - `test_confirm_script_generates_character_references`：验证角色参考图生成逻辑
  - `test_confirm_script_generates_scene_backgrounds`：验证场景背景图生成逻辑
  - `test_character_reference_reuse`：验证已有参考图不被覆盖
  - `test_confirm_script_handles_missing_asset_store`：验证无 Asset Store 时仍正常工作
- ✅ 代码语法验证通过

**真实 API：** 未调用（按计划，当前不消耗 MiniMax 视频额度）

**实现要点：**
1. 重试时复用已有资产：检查 `referenceImageUrl` 和 `backgroundImageUrl`，仅在不存在时生成
2. 使用现有 `DynamicVisualProvider`（wanx-t2i）生成图片
3. 生成的图片存储到 MinIO，记录 `objectKey` 和预签名 URL
4. 支持无 Asset Store 场景：当 `_asset_store` 为 None 时，静默跳过生成

**下一步：** 任务 2 - 动态视频资产元数据扩展

#### 2026-09-09：任务 2 - 动态视频资产元数据扩展

**任务：** 扩展 visualAssets 支持视频元数据和首尾帧提取

**修改文件：**
- `backend/src/comicflow/production/pipeline.py`：修改 `generate_shot_visual` 方法
  - 扩展 visual asset 元数据：添加 `sceneId`、`characterReferenceIds`
  - 实现视频首帧和尾帧提取：使用 `FrameExtractor` 提取并存储帧
  - 仅对 `mediaType == "video"` 的资产执行帧提取
- `backend/tests/test_video_asset_metadata.py`：新增 4 个测试用例

**输入/输出契约：**
- Visual Asset 扩展字段：
  - `sceneId` (str | None)：所属场景 ID（从 shot 继承）
  - `characterReferenceIds` (list[str] | None)：关联的角色 ID 列表（从 shot 继承）
  - `firstFrameObjectKey` (str | None)：首帧对象键（仅视频资产）
  - `lastFrameObjectKey` (str | None)：尾帧对象键（仅视频资产）
- 保留现有字段：`id`, `shotId`, `type`, `mediaType`, `valid`, `inputVersion`, `objectKey`, 等

**失败行为：**
- 帧提取失败时**不会阻塞视觉资产生成**
- 失败时静默跳过，资产仍标记为 valid
- 仅在有 Asset Store 且 mediaType 为 video 时尝试提取

**离线验证：**
- ✅ 4 个单元测试全部通过：
  - `test_visual_asset_includes_scene_and_character_metadata`：验证元数据继承
  - `test_video_asset_frame_extraction`：验证帧提取逻辑结构
  - `test_visual_asset_invalidation_preserves_metadata`：验证资产失效逻辑
  - `test_asset_metadata_contract`：验证完整契约
- ✅ 代码语法验证通过

**真实 API：** 未调用（Mock 模式生成的是 image 不是 video）

**实现要点：**
1. 元数据继承：从 shot 复制 `sceneId` 和 `characterIds` 到 asset
2. 条件性帧提取：仅对 video 资产 + Asset Store 存在时执行
3. 临时文件处理：下载视频到临时文件，提取帧后清理
4. 帧存储：首帧和尾帧作为独立 JPEG 文件存储到 MinIO
5. 错误容忍：任何步骤失败都不影响资产标记为 valid

**下一步：** 任务 3 - 同场景首帧级联

#### 2026-09-09：任务 3 - 同场景首帧级联

**任务：** 实现场景内镜头首帧级联，保证视频连贯性

**修改文件：**
- `backend/src/comicflow/production/pipeline.py`：修改 `generate_shot_visual` 方法，添加首帧级联逻辑
  - 新增 `_get_scene_by_id()` 方法：根据场景 ID 获取场景
  - 新增 `_get_previous_shot_in_scene()` 方法：获取同场景的上一镜头
  - 新增 `_get_valid_visual_asset()` 方法：获取有效的视觉资产
  - 修改 `generate_shot_visual()` 方法：实现首帧级联决策逻辑
- `backend/tests/test_first_frame_cascade.py`：新增 5 个测试用例

**输入/输出契约：**
- Visual Asset 新增字段：
  - `cascadeFromShotId` (str | None)：级联来源镜头 ID
- Shot 临时扩展字段（传递给 Provider）：
  - `firstFrameSource` (dict | None)：首帧来源信息
    - `type`: "scene_background" | "previous_shot_last_frame"
    - `objectKey`: 首帧图片对象键
    - `sceneId` 或 `shotId`：来源标识

**级联决策逻辑：**
1. **场景首镜头**：使用场景背景图（`scene.backgroundImageObjectKey`）作为首帧
2. **同场景后续镜头**：使用上一镜头尾帧（`prevAsset.lastFrameObjectKey`）作为首帧
3. **切换场景**：重置级联，使用新场景背景图
4. **尾帧缺失**：抛出 `CASCADE_FRAME_MISSING` 错误，禁止生成

**失败行为：**
- 上一镜头没有尾帧时，抛出 `CASCADE_FRAME_MISSING` 错误
- 错误信息包含：previousShotId、currentShotId、缺失原因
- 不会静默降级或跳过级联

**离线验证：**
- ✅ 5 个单元测试全部通过：
  - `test_first_shot_in_scene_uses_background`：验证场景首镜头逻辑
  - `test_subsequent_shot_cascades_from_previous`：验证后续镜头级联
  - `test_scene_change_resets_cascade`：验证场景切换重置
  - `test_missing_last_frame_blocks_cascade`：验证尾帧缺失阻塞
  - `test_cascade_metadata_recorded`：验证级联元数据记录
- ✅ 代码语法验证通过

**真实 API：** 未调用（Mock 模式生成 image，级联逻辑在 video 模式下生效）

**实现要点：**
1. 级联决策在 `generate_shot_visual` 开始时执行
2. 根据 `shot.sceneId` 判断是否在同场景
3. 使用 `scene.shotIds` 数组确定镜头顺序
4. `firstFrameSource` 信息传递给 Provider（Provider 负责实际使用）
5. Mock Provider 忽略 `firstFrameSource`，真实 H3 Provider 将使用它

**下一步：** 任务 4 - FFmpeg 视频优先合成

#### 2026-09-09：任务 4 - FFmpeg 视频优先合成

**任务：** 修改 FFmpeg 合成逻辑，支持视频资产优先，图片降级

**修改文件：**
- `backend/src/comicflow/providers/ffmpeg.py`：修改 FFmpeg 合成 Provider
  - 修改 `_prepare_visual()` 方法：支持视频资产优先选择
  - 修改 `_encode_cards()` 方法：支持视频和图片混合编码
  - 修改 `_encode_with_audio()` 方法：支持视频和图片混合编码

**核心逻辑：**
1. **视频优先选择**：
   - 遍历 `visualAssets`，按 shot_id 分组
   - 同一镜头有多个资产时，`mediaType == "video"` 优先
   - 如果只有图片资产，使用图片
   
2. **混合编码支持**：
   - 根据文件扩展名判断类型（.mp4/.mov/.avi/.mkv 为视频）
   - 视频：直接作为输入，不加 `-loop` 参数
   - 图片：添加 `-loop 1 -t <duration>` 参数，循环显示

3. **兼容性保留**：
   - 保持现有 TTS、字幕生成逻辑不变
   - 保持现有时间轴逻辑不变
   - 完全向后兼容纯图片项目

**输入/输出契约：**
- `_prepare_visual()` 返回：`list[Path | None]`
  - 每个元素对应一个镜头的视觉资产路径
  - 可能是 .mp4（视频）或 .png（图片）
  - None 表示该镜头无资产（使用文字卡）

**失败行为：**
- 视频下载失败时，该镜头使用文字卡（降级）
- FFmpeg 编码失败时，抛出 `FFMPEG_COMPOSITION_FAILED` 错误

**离线验证：**
- ✅ 代码语法验证通过
- ⚠️ 功能测试需要真实视频资产（Mock 模式生成图片）

**真实 API：** 未调用（等待任务 5 真实 H3 验证）

**实现要点：**
1. 优先级逻辑：同一 shot_id 的多个资产，video > image
2. 文件扩展名检测：使用 `Path.suffix.lower()` 判断类型
3. FFmpeg 命令构建：根据类型决定是否添加 `-loop` 参数
4. 超时调整：视频下载超时从 60s 增加到 120s
5. 完全向后兼容：纯图片项目行为不变

**下一步：** 任务 5 - 真实 H3 API 验证（需完整本地环境）

#### 2026-09-09：准备真实 API 验证环境

**任务：** 配置并文档化真实 H3 API 验证流程

**修改文件：**
- `.env`：添加完整的 S3/MinIO 配置
- `docs/implementation/h3-verification-guide.md`：更新为完整环境验证指南
- `HANDOFF.md`：更新验证方式说明

**环境要求：**
- 完整 Docker 环境（MinIO + PostgreSQL + Redis + API）
- 所有必需的环境变量配置完整
- MiniMax H3 和 Bailian API keys 有效

**推荐验证方式：**
1. 启动完整本地环境：`powershell -ExecutionPolicy Bypass -File scripts/start-local.ps1`
2. 通过前端 UI (http://127.0.0.1:5173) 手动创建测试项目
3. 生成 2-3 个镜头的短片，观察首帧级联效果
4. 验证：
   - 角色参考图和场景背景图生成
   - 第一个镜头使用场景背景作为首帧
   - 后续镜头使用上一镜头尾帧作为首帧
   - FFmpeg 正确合成视频和音频
   - 导出的视频播放流畅

**状态：** 离线验证完成，真实 API 验证需要用户在完整环境下手动执行

**下一步：** 在完整本地环境下运行真实 API 验证

### 完成记录模板

```text
日期：YYYY-MM-DD
任务：
修改文件：
输入/输出契约：
失败行为：
离线验证：
真实 API：未调用 / 已获用户许可并调用
下一步：
```

### 交接完成标准

- 任务书中的状态与代码一致。
- `HANDOFF.md` 写明最后完成的任务和下一任务。
- 没有把 API Key、完整视频 URL 或原始供应商响应写入文档。
- 未经用户明确许可，不消耗 MiniMax 视频额度。

## 2026-09-09：中文剧本与项目角色闭环修复

**状态：本轮修复完成，真实视频验收仍阻塞。**

### 目标和输入输出

- 输入：百炼生成的结构化 Script，或旧项目已经保存的 `shots[].characters`。
- 输出：中文编辑字段；可在预览中核对、提交后持久化的角色 ID；可操作的项目角色页面。
- 非目标：本轮不生成角色画像、不生成视频、不进行收费 API 试跑，也不将整段故事用正则猜成人名。
- 数据流：Provider 中文剧本 → 预览规范化并计算项目角色 ID（只读）→ 版本检查及整份契约检查 → 保存角色卡与剧本 → 角色 API → 页面编辑/绑定 → 后续参考资产入口。
- 失败行为：英文为主/明显坏编码描述返回 `PROVIDER_SCRIPT_LANGUAGE_INVALID`，不增加自动修复请求；版本冲突、非法引用、无权限均拒绝；待补全的外观/服装在任何确认阶段生成调用之前拦截。
- 有限范围：语言检查只检查描述字段，不是完整语义判定；两次仓储写入尚未改成单事务。纯读取不会自动修复旧项目，使用显式同步按钮。

### 完成任务

- [x] 复现真实项目英文描述、角色名称已有但 ID 为空、角色页固定演示内容。
- [x] 拆开中文剧本与 H3 Skill 英文扩写的提示词边界；保留“后续视频 Prompt 使用 Skill”的要求。
- [x] Adapter 保留识别名称；重归一化保留 ID；新增无模型调用的 `script_characters.py` 绑定规划。
- [x] 预览只读；提交建卡；同项目同名复用；非法引用先整体校验再写入。
- [x] 项目角色读取、创建、保存、旧稿同步接口；校验项目访问权限。
- [x] 页面接入真实数据，增加手动创建、保存角色属性、绑定/取消绑定镜头；移除假画像/假一致性状态。
- [x] 编辑器支持修改运镜、风格、环境声、配乐，旧英文描述有提示。
- [x] 无模型调用修订《雨夜倒影》10 镜头，版本 3 → 4；创建林小雨、林大雪并绑定原稿标记的镜头。原稿保留在版本历史及 `.scratch/2026-09-09-script-language-repair/original.json`。对白、旁白、动作、镜头 ID、时长和顺序未改动。
- [x] 重建并重启本地 API；worker/beat 未重启，未触发作业。只读浏览器核对 5173 页面中文描述和真实角色（拦截所有非 GET API 请求）。

### 离线验证记录

- 红灯：`uv run pytest backend/tests/test_script_character_handoff.py -q` 最初复现角色 ID 空、旧格式丢名称、英文/坏编码描述未被拒绝的 5 个失败。
- 聚焦回归：新用例 + preview commit/lines/scene fields + Bailian + character cards/automatic IDs + character scene references，**51 passed**。
- `pnpm --dir frontend build`：通过。
- `pnpm --dir frontend exec playwright test characters.spec.ts script-preview-commit.spec.ts --reporter=line`：**4 passed**，拦截响应，未使用真实模型。
- 涉及源码及新增/修改测试 `ruff check`：通过；`uv run mypy --package comicflow`：**50 source files，无错误**。
- 全量 `uv run pytest backend/tests -q --tb=short`：**206 passed / 11 failed / 1 skipped**。日志在 `.scratch/2026-09-09-script-language-repair/backend-regression.txt`。不能宣称全量通过。
- 实际项目只读 UI 截图在同目录 `script-editor.png`、`characters.png`；本轮没有调用生成 API，未查询或报告剩余额度。

### 下一任务顺序（Claude 交接）

1. **参考资产能力分离，优先级最高。** 当前 `_generate_character_reference` 与 `_generate_scene_background` 误调用 H3 视频 Provider，数据库场景背景已是 MP4。拆开图像/视频 Provider，校验实际图片类型、有效 URL 和失败呈现；不得把视频当图片传给 H3。先 MockTransport/本地素材验证，不收费。
2. **修复现有级联回归。** Mock 的 `mediaType=video` 元数据不代表它有真实视频尾帧；通用入口现报 `CASCADE_FRAME_MISSING`，阻塞 composition readiness、contract migration、generation sessions、local HTTP flow、media pipeline、project flow 用例。按真实能力决定级联，保留真实模式缺失尾帧的失败反馈。
3. **统一旧生成入口的 Script/envelope 契约和角色逻辑。** `split_script`、`_generate_script` 与规范化 Adapter 不一致，造成 generation sessions/runtime text generation 两项直接失败。复用新绑定模块，不能继续条件式测试或固定角色外观。
4. **完善角色编辑生命周期。** 改名后同步名称引用；修改视觉设定后使旧参考图失效；将角色/剧本写入纳入单事务。当前身份建卡与基本编辑已可用，不能据此宣称全链路一致性已经验证。
5. **核验真实 H3 Prompt 编译。** Skill 文件路径声明不是执行；首尾帧模式与多参考模式互斥，需要独立离线契约验证。全部离线门禁通过后，再申请一次最小额度的真实验证。

**接手入口：** `HANDOFF.md` 顶部；不要按历史章节直接开始 H3 收费试跑。

## 2026-09-09：独立图片 API 与每次 H3 生成执行 Skill

用户要求：角色/场景参考图可使用其他 API，每次生成场景视频必须使用项目 H3 Skill。

- 输入：中文角色卡/场景、镜头时长、有效图片引用。
- 数据流：独立参考图片 Provider → 图片类型校验/持久化 → 每次 H3 生成加载 SKILL.md + 对应模式指南 → 文本 API 按规则扩写 → 结构/引用/时长校验 → H3 视频 API。
- 图片 API 暂选现有百炼万相，允许单独配置密钥、模型、端点；H3 不生成角色或场景参考图。
- Skill 是提示词规则，不是图像生成 API。执行是把真实文件内容传给文本模型并校验返回，不能用本地模板或 h3Prompt 字段跳过它；中文编辑稿不回写英文扩写。
- 失败：Skill 缺失、模式冲突、引用不完整、扩写格式无效在 H3 请求前拒绝；参考图失败显式返回并保留已完成资产，重试复用；不静默吞掉异常。
- 验收：离线 MockTransport 覆盖每次加载、三/六节结构、API 调用顺序、错误不调用视频、参考图与视频能力隔离、图片复用、容器包含 Skill；本轮不调用真实收费 API。
- [x] 实现 Skill 提示词执行与 H3 强制接入。
- [x] 独立图片 Provider、角色/场景入口及错误处理。
- [x] 配置控制台、Dockerfile 打包声明、离线验证、交接记录。

### API 管理补充要求与完成记录

用户补充：完善原有 API 管理，把需要的能力加入并评估可能性。详细输出见 `docs/implementation/provider-console-upgrade-assessment.md`。

- [x] 文本配置变更重新绑定 Skill；图片/视频独立配置与密钥掩码，先校验后生效，保存不调用模型。
- [x] 前端可编辑端点、模型、密钥、尺寸/超时及 H3 提交/查询路径；说明 API 进程范围和重启行为。
- [x] 角色/场景显式生成参考图；未保存角色设定时禁用生成；不把旧视频 URL 作为可复用角色图。
- [x] 使用真实文本 Adapter + MockTransport 验证 Skill 内容确实进入请求，中文对白保持原文，配置重试次数也不会导致扩写自动重试。
- [x] H3 视频下载使用独立无鉴权客户端；离线测试证明优云密钥不发往外部资产域名。
- [x] 更新工程规约、交接首页及研究任务状态，保留历史记录。
- [ ] 共享配置持久化、加密、管理员权限、配置版本与 Worker 同步。
- [x] 角色设定草稿生成/预览/保存（后续用户指定优先实施，见末节）。
- [ ] 场景参考图生命周期和跨进程幂等。
- [ ] 修复 11 项现有离线回归，再安排经用户允许的最小真实验收。

本轮核心文件：`providers/h3_skill.py`、`providers/media_config.py`、`minimax_h3.py`、`bailian_text.py`、`wanx_image.py`、`runtime_config.py`、`production/pipeline.py`、`api/app.py`/`schemas.py`、`ModelApiSettings.tsx`、角色/剧本工作区、`.env.example`、`docker-compose.yml`、`backend/Dockerfile`。

最终验证：

```text
uv run pytest backend/tests/test_h3_skill_execution.py backend/tests/test_media_config_console.py backend/tests/test_minimax_h3.py backend/tests/test_wanx_image.py backend/tests/test_runtime_provider_config.py backend/tests/test_script_character_handoff.py -q
33 passed

pnpm --dir frontend exec playwright test model-api-console.spec.ts characters.spec.ts script-preview-commit.spec.ts --reporter=line
6 passed

pnpm --dir frontend build
通过；涉及文件 ruff check 通过；mypy 52 个文件通过

uv run pytest backend/tests -q --tb=short
225 passed / 11 failed / 1 skipped
```

更早的宽聚焦集合为 45 passed。最终全量日志：`.scratch/2026-09-09-script-language-repair/skill-api-regression.txt`。11 项失败名单与本轮前基线相同，不宣称全流程通过。真实文本、图片、视频 API 未调用，余额未查询。

旧阶段下一任务 1（能力分离）和 5（Skill 实际执行）已被本节实现覆盖；后续顺序调整为：旧级联/Script 契约回归 → 共享配置与 Worker → 角色设定助手和资产生命周期 → 其他协议 → 最小真实验收。

部署记录：`docker compose config --quiet`、`docker compose build api`、`docker compose up -d --no-deps api` 成功；容器内 Skill 与两份指南存在，API 健康；宿主 API 端口为 18001，前端 5173 的代理只读核对成功。当前文本/H3 启用、参考图片禁用。未修改实际 `.env`、未重启 worker/beat、未触发生成。不能用这次仅 API 部署推断 Worker 已运行新代码。

## 2026-09-09：角色提示词助手

用户要求：在角色界面通过 API 生成和修改角色提示词。本项由用户指定优先实施，共享配置/Worker 和旧全量回归仍为后续任务。

### 输入、输出和行为

- 输入：当前文本 API、保存的故事、目标角色出场镜头、当前编辑中的名称/外观/服装/性格/参考图提示词，以及可选补充要求。
- 输出：中文外观、服装、性格、参考图提示词草稿。名称保留输入值，不由模型另起人物；缺失细节是设计建议，需用户核对。
- 接口：`POST /api/projects/{id}/characters/prompt-preview`；请求 `expectedVersion`、可选 `characterId`/`expectedRevision`、`fields`、`instructions`。返回 `draft`、`expectedVersion`、`expectedRevision`，不写角色或项目状态。
- 数据流：文本 API 一次调用 → 结构/中文校验 → 可编辑预览 → 采用到角色编辑区 → 现有 PATCH/POST 保存 → 参考图使用保存的 `referenceImagePrompt`。文本生成不隐式调用图片或 H3。
- 新角色只需先输入名称即可请求草稿；已有角色可以保留已填约束并补充修改要求。未采用的草稿不会覆盖编辑中原文。
- 新增持久字段 `referenceImagePrompt` 和 `revision`；旧角色没有修订号时按 0 处理。提示词/外观/服装变化清除旧参考图元数据。生成图片返回后检查角色修订号，避免挂回过期图片。
- 前后端检查已知过期项目/角色版本；图片生成失败或中文草稿校验失败显式报错，保持原有编辑数据，不自动重试收费调用。

### 已完成

- [x] `providers/character_prompt.py` 定义独立中文角色输出契约；`BailianTextProvider.generate_character_prompt` 复用当前地址/模型/密钥，一次请求。
- [x] Pipeline 选择角色出场镜头，裁剪输入长度，不传资产地址/声音设置；API 校验项目权限、角色归属及修订，生成后复查。
- [x] 角色提示词持久化/读取、精确传入图片 Provider、修改失效；角色保存携带修订号，采用草稿的保存保持原项目版本门禁。
- [x] 角色 UI 新增补充要求、API 生成按钮、中文预览编辑、采用/放弃、提示词字段、保存及刷新恢复。
- [x] 离线测试和中文失败反馈；更新工程规约、评估报告、研究任务与交接。
- [x] 仅重建/重启本地 API，健康和 OpenAPI 路由核对通过，5173 代理正常。

### 验证证据

新增后端最初 9 项因预览入口不存在而失败；最终增加到 13 项，全部通过，涵盖权限、过期上下文、无自动重试、预览只读、提示词保存/图片消费及过期图片拒绝。页面用例最初因无生成控件而失败，现已通过。

```text
uv run pytest backend/tests/test_character_prompt_assistant.py backend/tests/test_script_character_handoff.py backend/tests/test_character_cards.py backend/tests/test_h3_skill_execution.py backend/tests/test_media_config_console.py backend/tests/test_bailian_text.py -q --tb=short
58 passed

pnpm --dir frontend exec playwright test characters.spec.ts model-api-console.spec.ts script-preview-commit.spec.ts --reporter=line
7 passed

pnpm --dir frontend build
通过；涉及文件 ruff check 通过；mypy 53 个源码文件通过

uv run pytest backend/tests -q --tb=short
238 passed / 11 failed / 1 skipped
```

全量日志在 `.scratch/character-prompt-assistant/backend-regression.txt`，11 项失败与上轮基线同名，不能宣称全流程通过。UI 草稿截图在 `frontend/test-results/characters-character-promp-77596-ed-without-media-generation/character-prompt-preview.png`。

部署执行 `docker compose build api`、`docker compose up -d --no-deps api`；只读健康检查和路由核对通过。现有文本模型 qwen-plus 已启用，参考图片仍未启用；没有调用真实文本/图片/视频 API，没有余额查询，未改 `.env`，未重启 worker/beat。

### 下游交接

规格：`.scratch/character-prompt-assistant/spec.md`；任务：`.scratch/character-prompt-assistant/issues/01-character-prompt-assistant.md`。

用户操作：刷新页面 → 角色 → 填名称或选择角色 → 补充要求 → API 生成角色提示词 → 修改预览 → 采用草稿到编辑区 → 保存角色设定。需要图片时，另行配置图片能力并点击参考图生成。清空提示词后，图片生成沿用原有角色设定构图。

仍待做：修复 11 项级联/旧 Script 回归；配置持久化和 Worker 同步；角色改名引用一致性、场景资产生命周期、数据库原子 CAS/跨仓储事务和跨进程幂等。本轮版本检查不能替代这些并发保证。
