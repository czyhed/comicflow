# 任务3：角色提示词按用途生成与编写规则优化

日期：2026-09-20。本地离线完成06A；06B一次整板与03B图片持久记录尚未实施。用户要求借鉴小红书等平台优秀提示词，改善人物质感；本批结合既定任务3实现，没有真实生成图片或视频。

## 依据和取舍

[公开来源调研](character-prompt-source-research-2026-09-20.md)记录实际可见证据：Black Forest Labs官方提示指南、Google Gemini官方Cookbook、Seedream官方视角案例、ZHO作者公开提示词集合。小红书只取得公开搜索框架，未取得可引用笔记正文；部分来源配图未能加载，报告逐项标注，不将其包装为实测高质量案例。

原文本系统提示和character-assets参考文件重复要求八段输出，混入武侠饰物、烟雾背景、侧身站姿、35/50/85mm等不同用途示例。后续主图生成又要求正面、全身、中性背景，存在模型照搬示例或产生冲突的风险；这不是已经证明的画质唯一原因。

本批改用“人物事实/项目画风→实际服装材质→全身清晰构图→可辨认的光影→简洁背景”。让模型描述棉布哑光与织纹、衣料厚薄与接缝、主光方向和暗侧补光等具体视觉关系，减少泛化赞美词及相互竞争的摄影参数。写实、二维、三维、厚涂、水墨、漫画按项目媒介表达，不能全部套用真人毛孔或一律禁止三维感。

提示词质量规则是生成意图；程序只能验证字段、上下文和调用行为，不能证明真实模型会忠实遵循或实际画质已改善。

## 用户操作与接口

沿用`POST /api/projects/{project_id}/characters/prompt-preview`，没有新建提示词平台。

| 操作 | 请求与输出 | 上下文 |
| --- | --- | --- |
| 完善角色设定 | `purpose=settings`；`outputFields`选择appearance/clothing/personality中的非空、不重复子集；只返回所选字段 | 原角色设定、已保存故事、相关出场镜头、当前画风、补充要求；不带旧生图提示词 |
| 仅润色主图提示词 | `purpose=reference-image`；只返回referenceImagePrompt | 名字、外观、服装、已写提示词、当前画风、补充要求；不带性格、故事、镜头或运动要求 |
| 未指定用途的旧调用 | 默认`full`，仍返回四字段 | 保留原上下文兼容；使用新的编写规则 |

新用途只携带name/medium/rendering/lighting/avoid风格信息，不重复发送完整风格快照和相同指令。图片润色前需要已有外观、服装；未填写时页面解释，服务端在供应商调用前拒绝。

字段集合、中文/长度校验在API及文本结果处理处一致执行。模型多返回或漏返回字段时拒绝草稿；失败、429、超时等不自动重试，不付费修复JSON。原权限和项目/角色版本冲突检查保留。返回draft中的name由服务端取输入，不让模型重命名人物。

角色页新增用途选择。未填设定优先勾选缺失字段；已具备外观/服装时默认图片润色。只展示本次返回的草稿，采用时合并指定字段，其他设定保留；采用与保存仍分开。切换用途/选项会丢弃当前预览，不自动生成；保存、刷新、切换角色不调用模型。

**资产处理增量：** 只保存referenceImagePrompt不再清空已确认主图/视角/板。图片仍代表原先确认的结果，新提示词作用于下一次用户生成；角色revision照常更新，过时请求仍拒绝。修改外观/服装维持原清理逻辑，其旧板失效缺口交06B处理。

## Skill与模型实际路径

`CharacterEditor → api/characters → CharacterAssets.preview_character_prompt → 请求级character-prompt文本用途绑定 → BailianTextProvider兼容文本Adapter → JSON校验 → 草稿`。

文本模型仍由API管理的角色提示词用途决定；未硬编码豆包/百炼模型或切换配置。每次点击是1次显式文本调用，0次图片/视频调用；三视图没有新增文本扩写。

仍使用XiaoLuo视觉资产Skill适配，`character-prompt`改读`skills/xiaoluo-visual-assets/references/character-prompt-writing.md`，不再注入旧八段海报式示例。Skill路由主文件和stage映射同步更新，未下载或替换外部仓库。现有图片提交的确定性追加规则、Provider参数及三次视角生成不变；旧character-assets文档仍供旧图片阶段使用，不宣称全部历史规则已重写。

原图片请求冻结夹具保留。共享Skill路由文件更新会改变来源SHA；契约测试校验新SHA与实际载入文件一致，再比较其余完整图片请求与原夹具，未放宽提示词、素材顺序或调用次数断言。

## 不扣费验证

先写新用途、草稿保留和Skill路由的失败用例：7失败/4通过，日志`var/character-prompt-purpose-red.txt`。完成后聚焦63通过，覆盖六种风格、指定字段、越权字段拒绝、单次调用、空身份提交前阻断、保存草稿保留图片和旧入口兼容。

| 检查 | 结果 |
| --- | --- |
| 完整后端 | 773通过，3条件跳过；`var/character-prompt-purpose-backend.txt` |
| Ruff / Mypy | 通过；81个源文件 |
| 前端生产构建 | 通过 |
| 前端Node | 27通过；`var/character-prompt-purpose-node.txt` |
| 角色浏览器 | 3通过；用途切换、失败后显式重试、部分草稿采用、保存及刷新 |
| 全部Playwright | 74通过；`var/character-prompt-purpose-playwright.txt` |

3项条件跳过是2项外部脱敏项目夹具测试及1项未启用Docker冒烟。本批没有重新执行真实数据栈/Worker联调，也没有启动业务消费者。浏览器使用拦截API；个别既有场景有到未启动18001的只读事件请求日志，不代表业务服务已可用。

来源复核后补充“光影表达服从媒介、二维不统一强制赛璐璐”的规则措辞，再跑同组63项通过；仅规则文字微调，没有无理由重复全量测试。

后端命令：`.venv/Scripts/python.exe -m pytest backend/tests -q --tb=short`、`-m ruff check backend/src backend/tests`、`-m mypy backend/src`。前端目录：`pnpm build`、`node --test tests/*.test.mjs`、`pnpm exec playwright test`。页面截图已查看：`frontend/test-results/characters-purpose-scoped--e46a3-ds-and-never-generate-media/character-prompt-purpose.png`。

### 请求长度比较，非账单

使用同一合成角色、六个相关镜头和电影写实风格，HTTP请求全部由MockTransport接管。旧系统文本由修改前副本重建，旧user上下文与兼容full实际请求一致。完整消息和方法说明在`var/character-prompt-purpose-request-comparison.json`，没有用户项目或密钥。

| 请求 | system字符 | user字符 | 合计字符 | 显式文本调用 |
| --- | ---: | ---: | ---: | ---: |
| 修改前完整草稿 | 5239 | 1973 | 7212 | 1 |
| 新规则兼容完整草稿 | 2907 | 1973 | 4880 | 1 |
| 仅润色主图提示词 | 2856 | 436 | 3292 | 1 |
| 仅完善服装设定 | 2838 | 1565 | 4403 | 1 |

这是Unicode字符数，不是token计数、供应商usage或节省金额。每个模式仍有一次文本请求；节省来自避免无关上下文和无用输出，并非提示词本地复用就不收费。实际输出长度由模型决定。

## 下一步与运行边界

用户后续使用：角色页选择用途→填写要求→生成草稿→检查身份/衣服与风格→采用到编辑区→保存。要检查图片效果再主动生成候选，不会自动重画旧角色或替换主图。源码尚未加载到业务运行环境，需要实际试用时更新API和前端；本批不要求付费验证。

下一项仍按任务书为任务4：确认主图后一次图生图整张正面/侧面/背面板，配套最小图片持久记录、防重、候选/采用与来源失效；处理旧referenceBoard残留和旧部分三图重试问题。当前仍为三个视角分别生成后本地拼板，不能说一次整板已完成。

修改前回溯副本：`var/change-backups/character-prompt-purpose-20260920-213843/`。原未提交内容保留；本批未提交/推送、部署、迁移、重启业务API/Worker/Beat。真实文本/图片/视频调用均0，画质待用户后续验收。
